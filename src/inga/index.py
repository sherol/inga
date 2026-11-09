"""SQLite index built from the markdown files.

The files are the source of truth; this index can be deleted and rebuilt at any
time with `inga reindex`. Every CLI command runs an incremental `sync` first.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import store
from .schema import HIDDEN_STATUSES, Report, ValidationError, now

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id            TEXT PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    date          TEXT NOT NULL,
    name          TEXT NOT NULL,
    project       TEXT NOT NULL,
    topic         TEXT,
    author        TEXT,
    type          TEXT NOT NULL,
    summary       TEXT,
    source        TEXT,
    star          INTEGER NOT NULL DEFAULT 0,
    reading_list  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'unread',
    read_at       TEXT,
    rating        INTEGER,
    notes         TEXT,
    superseded_by   TEXT,
    obsolete_reason TEXT,
    obsolete_at     TEXT,
    body          TEXT NOT NULL,
    word_count    INTEGER NOT NULL,
    content_hash  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    indexed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_date    ON reports(date);
CREATE INDEX IF NOT EXISTS reports_project ON reports(project);
CREATE INDEX IF NOT EXISTS reports_topic   ON reports(topic);

CREATE TABLE IF NOT EXISTS report_tags (
    report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    tag       TEXT NOT NULL,
    PRIMARY KEY (report_id, tag)
);
CREATE INDEX IF NOT EXISTS report_tags_tag ON report_tags(tag);

CREATE TABLE IF NOT EXISTS report_links (
    report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL,
    PRIMARY KEY (report_id, target_id)
);

-- report_id replaces old_id
CREATE TABLE IF NOT EXISTS report_supersedes (
    report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    old_id    TEXT NOT NULL,
    PRIMARY KEY (report_id, old_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(
    id UNINDEXED, name, summary, tags, body, tokenize = 'porter unicode61'
);
"""


def db_path(root: Path) -> Path:
    return root / ".inga" / "index.db"


def connect(root: Path) -> sqlite3.Connection:
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        # The index is disposable: on a schema change just start over.
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table') AND name NOT LIKE 'sqlite_%'"
        ).fetchall():
            if not name.startswith("reports_fts_"):
                conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- sync


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)
    obsoleted: list[str] = field(default_factory=list)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _upsert(conn: sqlite3.Connection, rel: str, report: Report, body: str, digest: str, path: Path) -> None:
    stat = path.stat()
    created = getattr(stat, "st_birthtime", stat.st_ctime)
    conn.execute("DELETE FROM reports WHERE path = ? OR id = ?", (rel, report.id))
    conn.execute("DELETE FROM reports_fts WHERE id = ?", (report.id,))
    conn.execute(
        """INSERT INTO reports (id, path, date, name, project, topic, author, type, summary, source,
                                star, reading_list, status, read_at, rating, notes,
                                superseded_by, obsolete_reason, obsolete_at, body,
                                word_count, content_hash, created_at, updated_at, indexed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            report.id, rel, report.date, report.name, report.project, report.topic, report.author,
            report.type, report.summary, report.source, int(report.star),
            int(report.reading_list), report.status, report.read_at, report.rating,
            report.notes, report.superseded_by, report.obsolete_reason, report.obsolete_at, body, len(body.split()), digest,
            datetime.fromtimestamp(created).replace(microsecond=0).isoformat(),
            datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat(),
            now(),
        ),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO report_tags (report_id, tag) VALUES (?, ?)",
        [(report.id, t) for t in report.tags],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO report_links (report_id, target_id) VALUES (?, ?)",
        [(report.id, r) for r in report.related],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO report_supersedes (report_id, old_id) VALUES (?, ?)",
        [(report.id, r) for r in report.supersedes if r != report.id],
    )
    conn.execute(
        "INSERT INTO reports_fts (id, name, summary, tags, body) VALUES (?,?,?,?,?)",
        (report.id, report.name, report.summary or "", " ".join(report.tags), body),
    )


def _delete(conn: sqlite3.Connection, report_id: str) -> None:
    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.execute("DELETE FROM reports_fts WHERE id = ?", (report_id,))


def sync(conn: sqlite3.Connection, root: Path, full: bool = False) -> SyncResult:
    """Bring the index in line with the files on disk."""
    result = SyncResult()
    if full:
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM reports_fts")

    known = {
        row["path"]: (row["id"], row["content_hash"])
        for row in conn.execute("SELECT id, path, content_hash FROM reports")
    }
    seen_paths: set[str] = set()
    seen_ids: dict[str, str] = {}

    for path in store.iter_report_files(root):
        rel = _rel(root, path)
        seen_paths.add(rel)
        raw = path.read_bytes()
        digest = _hash(raw)
        if rel in known and known[rel][1] == digest:
            seen_ids[known[rel][0]] = rel
            result.unchanged += 1
            continue
        try:
            loaded = store.load(path, root)
        except (ValidationError, ValueError) as exc:
            result.errors.append((path, str(exc)))
            if rel in known:
                _delete(conn, known[rel][0])
            continue
        report = loaded.report
        if report.id in seen_ids and seen_ids[report.id] != rel:
            result.errors.append((path, f"duplicate id {report.id} (also in {seen_ids[report.id]})"))
            continue
        if loaded.changed:
            # Persist the generated id so it's stable across rebuilds.
            store.save(path, report, loaded.body)
            digest = _hash(path.read_bytes())
        seen_ids[report.id] = rel
        _upsert(conn, rel, report, loaded.body, digest, path)
        if rel in known:
            result.updated += 1
        else:
            result.added += 1

    for rel, (rid, _) in known.items():
        if rel not in seen_paths:
            _delete(conn, rid)
            result.removed += 1

    result.obsoleted = _apply_supersedes(conn, root)
    conn.commit()
    return result


def _apply_supersedes(conn: sqlite3.Connection, root: Path) -> list[str]:
    """Mark reports obsolete when something says they've been replaced.

    Two ways that can happen, both usually written by agents:
    - a report has `superseded_by: <newer id>` but isn't marked obsolete yet;
    - a newer report lists it in `supersedes: [...]`.
    The change is written to the old report's file, so it survives a reindex.
    """
    todo: dict[str, str | None] = {}
    for row in conn.execute(
        "SELECT id, superseded_by FROM reports WHERE superseded_by IS NOT NULL AND status != 'obsolete'"
    ):
        todo[row["id"]] = row["superseded_by"]
    for row in conn.execute(
        """SELECT s.old_id, s.report_id FROM report_supersedes s
           JOIN reports old ON old.id = s.old_id
           WHERE old.status != 'obsolete' OR old.superseded_by IS NULL"""
    ):
        todo.setdefault(row["old_id"], row["report_id"])

    done = []
    for old_id, new_id in todo.items():
        row = conn.execute("SELECT path FROM reports WHERE id = ?", (old_id,)).fetchone()
        path = root / row["path"]
        loaded = store.load(path, root)
        report = mark_obsolete(loaded.report, by=new_id)
        store.save(path, report, loaded.body)
        _upsert(conn, row["path"], report, loaded.body, _hash(path.read_bytes()), path)
        done.append(old_id)
    return done


def mark_obsolete(report: Report, by: str | None = None, reason: str | None = None) -> Report:
    """Return `report` marked obsolete (keeps any existing reason/link if not given)."""
    if report.status != "obsolete" or not report.obsolete_at:
        report.obsolete_at = now()
    report.status = "obsolete"
    report.reading_list = False
    if by:
        report.superseded_by = by
    if reason:
        report.obsolete_reason = reason
    return report


# ---------------------------------------------------------------- queries


@dataclass
class Filters:
    project: str | None = None
    topic: str | None = None
    starred: bool = False
    reading_list: bool = False
    status: str | None = None
    include_archived: bool = False
    tag: str | None = None
    type: str | None = None
    author: str | None = None
    since: str | None = None
    until: str | None = None


SORTS = {
    "date": "r.date DESC, r.name",
    "name": "r.name COLLATE NOCASE, r.date DESC",
    "project": "r.project, r.date DESC",
    "rating": "COALESCE(r.rating, 0) DESC, r.date DESC",
}


def _where(f: Filters) -> tuple[str, list]:
    clauses, params = [], []
    if f.project:
        clauses.append("r.project = ?")
        params.append(f.project)
    if f.topic:
        clauses.append("r.topic = ?")
        params.append(f.topic)
    if f.starred:
        clauses.append("r.star = 1")
    if f.reading_list:
        clauses.append("r.reading_list = 1")
    if f.status:
        clauses.append("r.status = ?")
        params.append(f.status)
    elif not f.include_archived:
        clauses.append(f"r.status NOT IN ({','.join('?' * len(HIDDEN_STATUSES))})")
        params.extend(HIDDEN_STATUSES)
    if f.tag:
        clauses.append("r.id IN (SELECT report_id FROM report_tags WHERE tag = ?)")
        params.append(f.tag.lower())
    if f.type:
        clauses.append("r.type = ?")
        params.append(f.type)
    if f.author:
        clauses.append("r.author LIKE ?")
        params.append(f"%{f.author}%")
    if f.since:
        clauses.append("r.date >= ?")
        params.append(f.since)
    if f.until:
        clauses.append("substr(r.date, 1, 10) <= ?")
        params.append(f.until)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


_TAGS = "(SELECT group_concat(tag, ',') FROM report_tags t WHERE t.report_id = r.id) AS tags"


def list_reports(conn: sqlite3.Connection, f: Filters, sort: str = "date", limit: int | None = None):
    where, params = _where(f)
    sql = f"SELECT r.*, {_TAGS} FROM reports r{where} ORDER BY {SORTS[sort]}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def search(conn: sqlite3.Connection, query: str, f: Filters, limit: int = 20):
    where, params = _where(f)
    where = where.replace(" WHERE ", " AND ", 1) if where else ""
    sql = f"""
        SELECT r.*, {_TAGS},
               snippet(reports_fts, 4, '[bold yellow]', '[/]', ' … ', 12) AS snippet
        FROM reports_fts
        JOIN reports r ON r.id = reports_fts.id
        WHERE reports_fts MATCH ?{where}
        ORDER BY bm25(reports_fts, 0, 10.0, 5.0, 3.0, 1.0)
        LIMIT ?
    """
    return conn.execute(sql, [query, *params, limit]).fetchall()


def project_counts(conn: sqlite3.Connection):
    return conn.execute(
        """SELECT project,
                  COUNT(*) AS total,
                  SUM(status = 'unread') AS unread,
                  SUM(star) AS starred,
                  SUM(reading_list) AS queued,
                  MAX(date) AS latest
           FROM reports GROUP BY project ORDER BY latest DESC"""
    ).fetchall()


class AmbiguousId(LookupError):
    pass


def resolve(conn: sqlite3.Connection, ref: str) -> sqlite3.Row:
    """Find a report by id, unique id prefix, or filename stem."""
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (ref,)).fetchone()
    if row:
        return row
    rows = conn.execute(
        "SELECT * FROM reports WHERE id LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\'",
        (_like_escape(ref) + "%", "%/%" + _like_escape(ref) + "%.md"),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise LookupError(f"no report matches {ref!r}")
    raise AmbiguousId(f"{ref!r} matches {len(rows)} reports: " + ", ".join(r["id"] for r in rows[:5]))


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def links(conn: sqlite3.Connection, report_id: str):
    """Reports this one links to, and reports linking to it."""
    out = conn.execute(
        """SELECT l.target_id AS id, r.name FROM report_links l
           LEFT JOIN reports r ON r.id = l.target_id WHERE l.report_id = ?""",
        (report_id,),
    ).fetchall()
    back = conn.execute(
        """SELECT r.id, r.name FROM report_links l
           JOIN reports r ON r.id = l.report_id WHERE l.target_id = ?""",
        (report_id,),
    ).fetchall()
    return out, back


def topic_counts(conn: sqlite3.Connection, project: str | None = None):
    sql = """SELECT COALESCE(topic, '') AS topic, COUNT(*) AS total,
                    SUM(status = 'unread') AS unread, MAX(date) AS latest
             FROM reports {} GROUP BY topic ORDER BY total DESC, topic"""
    if project:
        return conn.execute(sql.format("WHERE project = ?"), (project,)).fetchall()
    return conn.execute(sql.format("")).fetchall()


def supersession(conn: sqlite3.Connection, report_id: str):
    """(reports this one replaces, the report that replaced this one or None)."""
    replaces = conn.execute(
        """SELECT DISTINCT r.id, r.name FROM reports r
           WHERE r.superseded_by = ?
              OR r.id IN (SELECT old_id FROM report_supersedes WHERE report_id = ?)""",
        (report_id, report_id),
    ).fetchall()
    row = conn.execute(
        """SELECT n.id, n.name FROM reports o JOIN reports n ON n.id = o.superseded_by
           WHERE o.id = ?""",
        (report_id,),
    ).fetchone()
    return replaces, row
