from pathlib import Path

import pytest
from click.testing import CliRunner

from inga import index, store
from inga.cli import main
from inga.schema import Report, ValidationError


@pytest.fixture
def nb(tmp_path, monkeypatch):
    monkeypatch.setenv("INGA_HOME", str(tmp_path))
    monkeypatch.setenv("COLUMNS", "200")
    runner = CliRunner()
    result = runner.invoke(main, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output

    def run(*args, input=None):
        r = runner.invoke(main, list(args), input=input, catch_exceptions=False)
        return r

    run.root = tmp_path
    return run


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


BODY = "\n# Title\n\nSome body text with  odd   spacing.\n\n- a\n- b\n"


def new_report(nb, project="alpha", name="First report", *extra):
    r = nb("new", "-p", project, "-n", name, "--body-file", "-", *extra, input=BODY)
    assert r.exit_code == 0, r.output
    path = Path(r.output.strip())
    return path, store.load(path).report


# ---------------------------------------------------------------- schema / store


def test_required_fields():
    with pytest.raises(ValidationError, match="name"):
        Report.from_meta({"id": "x", "date": "2026-01-01", "project": "p"})


def test_rating_bounds():
    with pytest.raises(ValidationError):
        Report.from_meta({"id": "x", "date": "2026-01-01", "name": "n", "project": "p", "rating": 7})


def test_roundtrip_preserves_body_and_extra_keys(tmp_path):
    text = "---\nid: abc\ndate: 2026-11-08\nname: N\nproject: P\ncustom_key: 42\n---\n" + BODY
    path = write(tmp_path, "r.md", text)
    loaded = store.load(path)
    assert loaded.report.project == "p"
    loaded.report.star = True
    store.save(path, loaded.report, loaded.body)
    meta, body = store.split(path.read_text())
    assert body == BODY
    assert meta["star"] is True and meta["custom_key"] == 42
    assert "'2026" not in path.read_text()  # dates unquoted


# ---------------------------------------------------------------- CLI flows


def test_new_and_list(nb):
    path, rep = new_report(nb, "alpha", "First report", "--tags", "Perf,db", "-t", "research")
    assert path.parent == nb.root / "reports" / "alpha"
    assert path.read_text().split("---\n", 2)[2] == BODY
    out = nb("list").output
    assert "First report" in out and rep.id in out
    assert rep.tags == ["perf", "db"]


def test_star_queue_read_write_back_to_file(nb):
    path, rep = new_report(nb)
    nb("star", rep.id[:10])
    nb("queue", rep.id)
    meta, _ = store.split(path.read_text())
    assert meta["star"] is True and meta["reading_list"] is True

    assert "First report" in nb("list", "--starred").output
    assert "First report" in nb("queue").output

    nb("read", rep.id)
    meta, _ = store.split(path.read_text())
    assert meta["status"] == "read" and meta["reading_list"] is False and meta.get("read_at")
    assert "No reports" in nb("list", "--unread").output

    nb("rate", rep.id, "4")
    nb("note", rep.id, "worth a reread")
    meta, _ = store.split(path.read_text())
    assert meta["rating"] == 4 and meta["notes"] == "worth a reread"


def test_state_survives_reindex(nb):
    _, rep = new_report(nb)
    nb("star", rep.id)
    (nb.root / ".inga" / "index.db").unlink()
    assert nb("reindex").exit_code == 0
    assert rep.id in nb("list", "--starred").output


def test_sync_handles_add_edit_delete(nb):
    root = nb.root
    p = write(root, "reports/beta/2026-11-01-handwritten.md", "---\ndate: 2026-11-01\nname: Handwritten\n---\nbody\n")
    out = nb("list").output
    assert "Handwritten" in out
    meta, _ = store.split(p.read_text())
    assert meta["id"].startswith("20261101-") and meta["project"] == "beta"

    p.write_text(p.read_text().replace("name: Handwritten", "name: Renamed"))
    assert "Renamed" in nb("list").output

    p.unlink()
    assert "No reports" in nb("list").output


def test_name_from_heading_and_bad_file_skipped(nb):
    write(nb.root, "reports/p/2026-11-02-x.md", "# From Heading\n\ntext\n")
    write(nb.root, "reports/p/broken.md", "---\nname: no date\n---\n")
    r = nb("list")
    assert "From Heading" in r.output
    assert nb("validate").exit_code == 1


def test_search_and_filters(nb):
    new_report(nb, "alpha", "Database tuning", "--tags", "db")
    _, other = new_report(nb, "beta", "Frontend review", "-t", "review")
    write(nb.root, "reports/beta/2026-01-01-old.md", "---\ndate: 2026-01-01\nname: Old thing\n---\nzebra\n")
    assert "Old thing" in nb("search", "zebra").output
    out = nb("list", "--project", "beta", "--type", "review").output
    assert "Frontend review" in out and "Database" not in out
    assert "Database tuning" in nb("list", "--tag", "db").output
    assert "Old thing" not in nb("list", "--since", "2026-06-01").output
    nb("archive", other.id)
    assert "Frontend review" not in nb("list").output
    assert "Frontend review" in nb("list", "--all").output


def test_add_moves_file_into_place(nb, tmp_path_factory):
    src = tmp_path_factory.mktemp("out") / "draft.md"
    src.write_text("# Agent Draft\n\nhello\n")
    r = nb("add", str(src), "--project", "Gamma Project")
    assert r.exit_code == 0, r.output
    assert not src.exists()
    files = list((nb.root / "reports" / "gamma-project").glob("*-agent-draft.md"))
    assert len(files) == 1
    assert "Agent Draft" in nb("show", "agent-draft").output


def test_duplicate_ids_reported(nb):
    hdr = "---\nid: 20261108-aaaaaa\ndate: 2026-11-08\nname: {}\nproject: p\n---\n"
    write(nb.root, "reports/p/a.md", hdr.format("A"))
    write(nb.root, "reports/p/b.md", hdr.format("B"))
    r = nb("validate")
    assert r.exit_code == 1


def test_projects_and_ambiguous_prefix(nb):
    new_report(nb, "alpha", "One")
    new_report(nb, "alpha", "Two")
    assert "alpha" in nb("projects").output
    r = CliRunner().invoke(main, ["star", "2"])
    assert r.exit_code != 0 and "matches" in r.output
