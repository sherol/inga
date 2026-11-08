"""`inga` command-line interface."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from . import index, store
from .schema import REPORT_TYPES, STATUSES, Report, ValidationError, new_id, now, normalize_timestamp, today

console = Console()
err = Console(stderr=True)

TEMPLATE_BODY = """
# {name}

## Summary

<!-- 2-4 sentences: what was asked, what you found. -->

## Findings

## Details

## Next steps
"""


# ---------------------------------------------------------------- helpers


class Ctx:
    def __init__(self, home: str | None):
        self._home = home
        self._root: Path | None = None
        self._conn: sqlite3.Connection | None = None

    @property
    def root(self) -> Path:
        if self._root is None:
            try:
                self._root = Path(home).resolve() if (home := self._home) else store.find_root()
            except store.NotebookNotFound as exc:
                raise click.ClickException(str(exc))
        return self._root

    @property
    def conn(self) -> sqlite3.Connection:
        """Open the index and sync it with the files on disk."""
        if self._conn is None:
            self._conn = index.connect(self.root)
            result = index.sync(self._conn, self.root)
            for path, msg in result.errors:
                err.print(f"[yellow]skipped[/] {path.relative_to(self.root)}: {msg}")
        return self._conn


pass_ctx = click.make_pass_decorator(Ctx)


def _star(on) -> str:
    return "★" if on else ""


def _fmt_date(d: str) -> str:
    return d[:16].replace("T", " ")


def _report_table(rows, show_snippet: bool = False) -> Table:
    table = Table(box=None, header_style="bold", pad_edge=False)
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("★", style="yellow", no_wrap=True)
    table.add_column("📖", no_wrap=True)
    table.add_column("date", no_wrap=True)
    table.add_column("project", style="cyan", no_wrap=True)
    table.add_column("name", style="bold")
    table.add_column("type", style="magenta", no_wrap=True)
    table.add_column("tags", style="green")
    for r in rows:
        name = r["name"]
        if r["status"] == "unread":
            name = f"• {name}"
        elif r["status"] == "archived":
            name = f"[dim]{name}[/]"
        if show_snippet and r["snippet"]:
            name += "\n[dim]" + " ".join(r["snippet"].split()) + "[/]"
        elif r["summary"]:
            name += f"\n[dim]{r['summary']}[/]"
        table.add_row(
            r["id"],
            _star(r["star"]),
            "✓" if r["reading_list"] else "",
            _fmt_date(r["date"]),
            r["project"],
            name,
            r["type"],
            (r["tags"] or "").replace(",", ", "),
        )
    return table


def _resolve(ctx: Ctx, ref: str):
    try:
        return index.resolve(ctx.conn, ref)
    except LookupError as exc:
        raise click.ClickException(str(exc))


def _update(ctx: Ctx, ref: str, **changes) -> Report:
    """Rewrite a report's frontmatter with `changes`, then re-sync the index."""
    row = _resolve(ctx, ref)
    path = ctx.root / row["path"]
    loaded = store.load(path, ctx.root)
    meta = loaded.report.to_meta()
    for key, value in changes.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    try:
        report = Report.from_meta(meta)
    except ValidationError as exc:
        raise click.ClickException(str(exc))
    store.save(path, report, loaded.body)
    index.sync(ctx.conn, ctx.root)
    return report


def _done(report: Report, what: str) -> None:
    console.print(f"[green]✓[/] {what}: [bold]{report.name}[/] [dim]({report.id})[/]")


# ---------------------------------------------------------------- root


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--home", envvar="INGA_HOME", help="Notebook folder (default: nearest parent with .inga/).")
@click.version_option(package_name="inga")
@click.pass_context
def main(click_ctx: click.Context, home: str | None):
    """Inga's Notebook: a markdown reports database for agent-written reports."""
    click_ctx.obj = Ctx(home)


@main.command()
@click.argument("folder", default=".", type=click.Path(file_okay=False))
def init(folder: str):
    """Create a new notebook in FOLDER (default: current folder)."""
    root = Path(folder).resolve()
    (root / ".inga").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    gi = root / ".inga" / ".gitignore"
    if not gi.exists():
        gi.write_text("index.db*\n")
    conn = index.connect(root)
    index.sync(conn, root)
    console.print(f"[green]✓[/] notebook ready at {root}")


# ---------------------------------------------------------------- filing reports


@main.command()
@click.option("-p", "--project", required=True, help="Project the report belongs to.")
@click.option("-n", "--name", required=True, help="Report title.")
@click.option("-t", "--type", "rtype", type=click.Choice(REPORT_TYPES), default="other", show_default=True)
@click.option("--tags", default="", help="Comma-separated tags.")
@click.option("-a", "--author", help="Agent/model/session that wrote it.")
@click.option("-s", "--summary", help="One or two sentence TL;DR.")
@click.option("--source", help="URL / PR / session link that produced the report.")
@click.option("--related", default="", help="Comma-separated ids of related reports.")
@click.option("--date", "date_", help="ISO date/datetime (default: now).")
@click.option("--body-file", type=click.File("r"), help="Read the report body from a file, or '-' for stdin.")
@pass_ctx
def new(ctx: Ctx, project, name, rtype, tags, author, summary, source, related, date_, body_file):
    """Create a new report file and print its path.

    With --body-file the report is complete; otherwise a template is written
    for you (or an agent) to fill in.
    """
    try:
        date = normalize_timestamp(date_) if date_ else now()
        report = Report.from_meta(
            dict(id=new_id(date), date=date, name=name, project=project, type=rtype, tags=tags,
                 author=author, summary=summary, source=source, related=related)
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc))
    body = body_file.read() if body_file else TEMPLATE_BODY.format(name=name)
    path = store.target_path(ctx.root, report)
    store.save(path, report, body)
    index.sync(ctx.conn, ctx.root)
    click.echo(path)


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-p", "--project", help="Project, if the file doesn't say.")
@click.option("--copy", is_flag=True, help="Copy instead of moving the file.")
@pass_ctx
def add(ctx: Ctx, files, project, copy):
    """File existing markdown report(s) into the notebook.

    Missing id/date are filled in, a name is taken from the first heading if
    absent, and the file lands in reports/<project>/<date>-<slug>.md.
    """
    for src in files:
        text = src.read_text(encoding="utf-8")
        try:
            meta, body = store.split(text)
            if project and not meta.get("project"):
                meta["project"] = project
            if not meta.get("date"):
                meta["date"] = today()
            store.fill_missing(meta, body, src, None)
            report = Report.from_meta(meta)
        except ValidationError as exc:
            raise click.ClickException(f"{src}: {exc}")
        dest = store.target_path(ctx.root, report)
        store.save(dest, report, body)
        if not copy and src.resolve() != dest.resolve():
            src.unlink()
        console.print(f"[green]✓[/] filed {report.id} → {dest.relative_to(ctx.root)}")
    index.sync(ctx.conn, ctx.root)


# ---------------------------------------------------------------- browsing


def _filter_options(f):
    opts = [
        click.option("-p", "--project", help="Only this project."),
        click.option("--starred", "-*", "starred", is_flag=True, help="Only starred."),
        click.option("--reading-list", "-r", "reading_list", is_flag=True, help="Only on the reading list."),
        click.option("--unread", "-u", is_flag=True, help="Only unread."),
        click.option("--status", type=click.Choice(STATUSES)),
        click.option("--all", "-A", "include_archived", is_flag=True, help="Include archived reports."),
        click.option("--tag", help="Only reports with this tag."),
        click.option("--type", "rtype", type=click.Choice(REPORT_TYPES)),
        click.option("--author", help="Author contains this text."),
        click.option("--since", help="On/after this date (YYYY-MM-DD)."),
        click.option("--until", help="On/before this date (YYYY-MM-DD)."),
    ]
    for opt in reversed(opts):
        f = opt(f)
    return f


def _filters(project, starred, reading_list, unread, status, include_archived, tag, rtype, author, since, until):
    return index.Filters(
        project=project, starred=starred, reading_list=reading_list,
        status="unread" if unread else status, include_archived=include_archived,
        tag=tag, type=rtype, author=author, since=since, until=until,
    )


@main.command("list")
@_filter_options
@click.option("--sort", type=click.Choice(list(index.SORTS)), default="date", show_default=True)
@click.option("-n", "--limit", type=int, help="Show at most N reports.")
@pass_ctx
def list_(ctx: Ctx, sort, limit, **kw):
    """List reports, newest first. • marks unread."""
    rows = index.list_reports(ctx.conn, _filters(**kw), sort=sort, limit=limit)
    if not rows:
        console.print("[dim]No reports match.[/]")
        return
    console.print(_report_table(rows))
    console.print(f"[dim]{len(rows)} report(s)[/]")


@main.command()
@click.argument("query")
@_filter_options
@click.option("-n", "--limit", type=int, default=20, show_default=True)
@pass_ctx
def search(ctx: Ctx, query, limit, **kw):
    """Full-text search over name, summary, tags and body.

    Supports SQLite FTS5 syntax: "exact phrase", a OR b, prefix*, name:word.
    """
    try:
        rows = index.search(ctx.conn, query, _filters(**kw), limit=limit)
    except sqlite3.OperationalError as exc:
        raise click.ClickException(f"bad search query: {exc}")
    if not rows:
        console.print("[dim]No matches.[/]")
        return
    console.print(_report_table(rows, show_snippet=True))


@main.command()
@click.argument("ref")
@click.option("--mark-read", "-m", is_flag=True, help="Mark as read after showing.")
@click.option("--raw", is_flag=True, help="Print the raw markdown file.")
@click.option("--path", "path_only", is_flag=True, help="Only print the file path.")
@pass_ctx
def show(ctx: Ctx, ref, mark_read, raw, path_only):
    """Show a report (by id, id prefix, or filename)."""
    row = _resolve(ctx, ref)
    path = ctx.root / row["path"]
    if path_only:
        click.echo(path)
        return
    if raw:
        click.echo(path.read_text(encoding="utf-8"), nl=False)
    else:
        tags = [t for (t,) in ctx.conn.execute("SELECT tag FROM report_tags WHERE report_id = ?", (row["id"],))]
        flags = " ".join(
            x for x in (
                "[yellow]★ starred[/]" if row["star"] else "",
                "📖 reading list" if row["reading_list"] else "",
                f"[dim]{row['status']}[/]",
                f"rating {'●' * row['rating']}{'○' * (5 - row['rating'])}" if row["rating"] else "",
            ) if x
        )
        header = "\n".join(
            x for x in (
                f"[cyan]{row['project']}[/] · {row['type']} · {_fmt_date(row['date'])}",
                f"by {row['author']}" if row["author"] else None,
                f"[green]{', '.join(tags)}[/]" if tags else None,
                f"source: {row['source']}" if row["source"] else None,
                flags,
                f"[dim]{row['id']} · {row['path']} · {row['word_count']} words[/]",
            ) if x
        )
        console.print(Panel(header, title=f"[bold]{row['name']}[/]", title_align="left"))
        if row["summary"]:
            console.print(f"[italic]{row['summary']}[/]\n")
        if row["notes"]:
            console.print(Panel(row["notes"], title="Inga's notes", border_style="yellow", title_align="left"))
        console.print(Markdown(row["body"]))
        out, back = index.links(ctx.conn, row["id"])
        if out or back:
            console.print()
            for r in out:
                console.print(f"[dim]→ related:[/] {r['id']} {r['name'] or '[red](missing)[/]'}")
            for r in back:
                console.print(f"[dim]← linked from:[/] {r['id']} {r['name']}")
    if mark_read and row["status"] != "read":
        _update(ctx, row["id"], status="read", read_at=now())


@main.command()
@pass_ctx
def projects(ctx: Ctx):
    """Report counts per project."""
    rows = index.project_counts(ctx.conn)
    if not rows:
        console.print("[dim]No reports yet.[/]")
        return
    table = Table(box=None, header_style="bold")
    for col in ("project", "total", "unread", "starred", "reading list", "latest"):
        table.add_column(col, justify="right" if col not in ("project", "latest") else "left")
    for r in rows:
        table.add_row(r["project"], str(r["total"]), str(r["unread"]), str(r["starred"]),
                      str(r["queued"]), _fmt_date(r["latest"]))
    console.print(table)


@main.command()
@click.option("-p", "--project")
@pass_ctx
def tags(ctx: Ctx, project):
    """Tags in use, with counts."""
    sql = """SELECT t.tag, COUNT(*) AS n FROM report_tags t JOIN reports r ON r.id = t.report_id
             {} GROUP BY t.tag ORDER BY n DESC, t.tag"""
    rows = ctx.conn.execute(sql.format("WHERE r.project = ?" if project else ""), (project,) if project else ())
    for r in rows:
        console.print(f"{r['n']:>4}  [green]{r['tag']}[/]")


# ---------------------------------------------------------------- curation


@main.command()
@click.argument("refs", nargs=-1, required=True)
@pass_ctx
def star(ctx: Ctx, refs):
    """Star report(s)."""
    for ref in refs:
        _done(_update(ctx, ref, star=True), "starred")


@main.command()
@click.argument("refs", nargs=-1, required=True)
@pass_ctx
def unstar(ctx: Ctx, refs):
    """Remove the star from report(s)."""
    for ref in refs:
        _done(_update(ctx, ref, star=False), "unstarred")


@main.command()
@click.argument("refs", nargs=-1)
@pass_ctx
def queue(ctx: Ctx, refs):
    """Add report(s) to the reading list. With no args, show the reading list."""
    if not refs:
        rows = index.list_reports(ctx.conn, index.Filters(reading_list=True))
        if rows:
            console.print(_report_table(rows))
        else:
            console.print("[dim]Reading list is empty.[/]")
        return
    for ref in refs:
        _done(_update(ctx, ref, reading_list=True), "added to reading list")


@main.command()
@click.argument("refs", nargs=-1, required=True)
@pass_ctx
def dequeue(ctx: Ctx, refs):
    """Remove report(s) from the reading list."""
    for ref in refs:
        _done(_update(ctx, ref, reading_list=False), "removed from reading list")


@main.command()
@click.argument("refs", nargs=-1, required=True)
@click.option("--keep", is_flag=True, help="Keep it on the reading list.")
@pass_ctx
def read(ctx: Ctx, refs, keep):
    """Mark report(s) as read (and take them off the reading list)."""
    for ref in refs:
        changes = dict(status="read", read_at=now())
        if not keep:
            changes["reading_list"] = False
        _done(_update(ctx, ref, **changes), "marked read")


@main.command()
@click.argument("refs", nargs=-1, required=True)
@pass_ctx
def unread(ctx: Ctx, refs):
    """Mark report(s) as unread."""
    for ref in refs:
        _done(_update(ctx, ref, status="unread", read_at=None), "marked unread")


@main.command()
@click.argument("refs", nargs=-1, required=True)
@pass_ctx
def archive(ctx: Ctx, refs):
    """Archive report(s): hidden from lists unless --all."""
    for ref in refs:
        _done(_update(ctx, ref, status="archived", reading_list=False), "archived")


@main.command()
@click.argument("ref")
@click.argument("text", required=False)
@click.option("--append", is_flag=True, help="Append to existing notes instead of replacing.")
@click.option("--clear", is_flag=True, help="Remove the notes.")
@pass_ctx
def note(ctx: Ctx, ref, text, append, clear):
    """Set Inga's margin notes on a report."""
    if clear:
        _done(_update(ctx, ref, notes=None), "notes cleared")
        return
    if not text:
        raise click.UsageError("give the note TEXT, or --clear")
    if append:
        existing = _resolve(ctx, ref)["notes"]
        text = f"{existing}\n{text}" if existing else text
    _done(_update(ctx, ref, notes=text), "noted")


@main.command()
@click.argument("ref")
@click.argument("rating", type=click.IntRange(0, 5))
@pass_ctx
def rate(ctx: Ctx, ref, rating):
    """Rate a report 1-5 (0 clears the rating)."""
    _done(_update(ctx, ref, rating=rating or None), f"rated {rating}" if rating else "rating cleared")


@main.command()
@click.argument("ref")
@click.option("--add", "add_tags", default="", help="Comma-separated tags to add.")
@click.option("--remove", "remove_tags", default="", help="Comma-separated tags to remove.")
@pass_ctx
def tag(ctx: Ctx, ref, add_tags, remove_tags):
    """Add or remove tags on a report."""
    row = _resolve(ctx, ref)
    current = [t for (t,) in ctx.conn.execute("SELECT tag FROM report_tags WHERE report_id = ?", (row["id"],))]
    add_list = [t.strip().lower() for t in add_tags.split(",") if t.strip()]
    remove_set = {t.strip().lower() for t in remove_tags.split(",") if t.strip()}
    new_tags = [t for t in current + [t for t in add_list if t not in current] if t not in remove_set]
    _done(_update(ctx, row["id"], tags=new_tags or None), f"tags: {', '.join(new_tags) or '(none)'}")


# ---------------------------------------------------------------- maintenance


@main.command()
@pass_ctx
def reindex(ctx: Ctx):
    """Rebuild the SQLite index from the markdown files."""
    conn = index.connect(ctx.root)
    result = index.sync(conn, ctx.root, full=True)
    for path, msg in result.errors:
        err.print(f"[yellow]skipped[/] {path.relative_to(ctx.root)}: {msg}")
    console.print(f"[green]✓[/] indexed {result.added} report(s)"
                  + (f", {len(result.errors)} skipped" if result.errors else ""))


@main.command()
@pass_ctx
def validate(ctx: Ctx):
    """Check every report file against the schema. Exits 1 on problems."""
    problems = 0
    ids: dict[str, Path] = {}
    for path in store.iter_report_files(ctx.root):
        rel = path.relative_to(ctx.root)
        try:
            meta, body = store.split(path.read_text(encoding="utf-8"))
            if not meta.get("id"):
                err.print(f"[yellow]warn[/] {rel}: no id (one will be assigned on next sync)")
            store.fill_missing(meta, body, path, ctx.root)
            report = Report.from_meta(meta)
        except (ValidationError, ValueError) as exc:
            err.print(f"[red]error[/] {rel}: {exc}")
            problems += 1
            continue
        if report.id in ids:
            err.print(f"[red]error[/] {rel}: duplicate id {report.id} (also {ids[report.id]})")
            problems += 1
        ids.setdefault(report.id, rel)
        expected = store.reports_dir(ctx.root) / report.project
        if path.parent != expected:
            err.print(f"[yellow]warn[/] {rel}: project is {report.project!r} but file is not in reports/{report.project}/")
    if problems:
        raise SystemExit(1)
    console.print(f"[green]✓[/] {len(ids)} report(s) valid")


if __name__ == "__main__":  # pragma: no cover
    main()
