"""Reading and writing report markdown files (YAML frontmatter + body).

The body is preserved byte-for-byte; only the frontmatter block is rewritten.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .schema import DEFAULT_TOPICS, Report, ValidationError, new_id, normalize_timestamp, slugify, today

FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
H1_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


class NotebookNotFound(RuntimeError):
    pass


# ---------------------------------------------------------------- notebook root


def find_root(start: Path | None = None) -> Path:
    """Locate the notebook: $INGA_HOME, else the nearest parent with a `.inga/` dir."""
    env = os.environ.get("INGA_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".inga").is_dir():
            return candidate
    raise NotebookNotFound(
        "No notebook found. Run `inga init` here, or set INGA_HOME to the notebook folder."
    )


def reports_dir(root: Path) -> Path:
    return root / "reports"


# ---------------------------------------------------------------- config

CONFIG_NAME = "config.yaml"

DEFAULT_CONFIG = """\
# Inga's Notebook settings.

# Allowed values for a report's `topic` (what it's about).
# Edit freely. Delete this list to allow any topic.
topics:
""" + "".join(f"  - {t}\n" for t in DEFAULT_TOPICS)


def config_path(root: Path) -> Path:
    return root / ".inga" / CONFIG_NAME


def load_config(root: Path) -> dict[str, Any]:
    path = config_path(root)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValidationError(f"{path} must be a YAML mapping")
    return data


def allowed_topics(root: Path) -> list[str] | None:
    """The notebook's topic list, or None if any topic is allowed."""
    topics = load_config(root).get("topics")
    if not topics:
        return None
    return [slugify(str(t)) for t in topics]


def write_default_config(root: Path) -> bool:
    path = config_path(root)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return True


def iter_report_files(root: Path):
    base = reports_dir(root)
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*.md")):
        if path.is_file() and not path.name.startswith("."):
            yield path


# ---------------------------------------------------------------- parse / dump


def split(text: str) -> tuple[dict[str, Any], str]:
    """Split a file into (frontmatter dict, body). Files without frontmatter get {}."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValidationError("frontmatter must be a YAML mapping")
    return meta, text[m.end():]


class _Dumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str_representer)


def _yaml_value(key: str, value: Any) -> Any:
    # Dates are stored as ISO strings; dump them as real YAML timestamps so
    # they appear unquoted (e.g. `date: 2026-11-08T10:30:00`).
    if key in ("date", "read_at", "obsolete_at") and isinstance(value, str):
        try:
            if len(value) == 10:
                return dt.date.fromisoformat(value)
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def dump(meta: dict[str, Any], body: str) -> str:
    meta = {k: _yaml_value(k, v) for k, v in meta.items()}
    head = yaml.dump(meta, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000)
    if body and not body.startswith("\n"):
        body = "\n" + body
    return f"---\n{head}---\n{body}"


# ---------------------------------------------------------------- load / save


@dataclass
class LoadedReport:
    report: Report
    body: str
    path: Path
    changed: bool  # True if fallbacks filled in fields that should be written back


def fill_missing(meta: dict[str, Any], body: str, path: Path | None, root: Path | None) -> bool:
    """Fill fields agents may have omitted, using the file itself as a hint.

    Returns True if `id` was added (the only fill that's written back to disk,
    since the index needs a stable id).
    """
    if not meta.get("date") and path is not None:
        m = FILENAME_DATE_RE.match(path.name)
        if m:
            meta["date"] = m.group(1)
    if not meta.get("name"):
        m = H1_RE.search(body)
        if m:
            meta["name"] = m.group(1)
    if not meta.get("project") and path is not None and root is not None:
        try:
            rel = path.resolve().relative_to(reports_dir(root).resolve())
            if len(rel.parts) >= 2:
                meta["project"] = rel.parts[0]
        except ValueError:
            pass
    if not meta.get("id"):
        date = normalize_timestamp(meta["date"]) if meta.get("date") else today()
        meta["id"] = new_id(date)
        return True
    return False


def load(path: Path, root: Path | None = None) -> LoadedReport:
    text = path.read_text(encoding="utf-8")
    meta, body = split(text)
    added_id = fill_missing(meta, body, path, root)
    report = Report.from_meta(meta)
    return LoadedReport(report=report, body=body, path=path, changed=added_id)


def save(path: Path, report: Report, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dump(report.to_meta(), body), encoding="utf-8")
    tmp.replace(path)


def target_path(root: Path, report: Report) -> Path:
    """reports/<project>/<YYYY-MM-DD>-<slug>.md, de-duplicated."""
    folder = reports_dir(root) / report.project
    stem = f"{report.date[:10]}-{slugify(report.name)}"
    path = folder / f"{stem}.md"
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}.md"
        n += 1
    return path
