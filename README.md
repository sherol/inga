# inga

**Inga's Notebook**: a markdown reports database for the reports agents write.

Agents drop markdown files into `reports/<project>/`. Inga browses them, stars the good ones, keeps a reading list, and writes notes in the margins.

- **Markdown files are the source of truth.** Each report is a `.md` file with YAML frontmatter. Everything (including stars and the reading list) lives in the files, so git tracks it all.
- **SQLite is just an index.** `.inga/index.db` is built from the files for fast filtering and full-text search. It's gitignored, and you can delete it any time and rebuild it with `inga reindex`.

## Install

```bash
pip install -e .
```

## Quick tour

```bash
inga list                         # newest first; • = unread
inga list --starred               # also: --reading-list, --unread, --project, --tag, --type, --since, --until, --all
inga search "cold start"          # full-text search (FTS5 syntax: "phrase", a OR b, pref*)
inga show 20261108-ab             # id, unique id prefix, or part of the filename
inga show 20261108-ab -m          # ...and mark it read

inga star <id>    / unstar
inga queue <id>   / dequeue       # reading list; `inga queue` alone shows it
inga read <id>    / unread        # marking read also takes it off the reading list
inga archive <id>                 # hidden from lists unless --all
inga rate <id> 4                  # 1–5, 0 clears
inga note <id> "follow up with Sam"
inga tag <id> --add a,b --remove c

inga projects                     # counts per project
inga tags                         # tags in use
inga validate                     # check every file against the schema (exit 1 on errors)
inga reindex                      # rebuild the index from scratch
```

The notebook is the nearest parent folder that contains `.inga/`, or whatever `$INGA_HOME` / `--home` points to. Run `inga init` to start a new one.

## Filing reports (for agents)

See [AGENTS.md](AGENTS.md). In short:

```bash
inga new -p my-project -n "Title" -t research --tags a,b -a "claude" -s "TL;DR" --body-file report.md
```

You can also write `reports/<project>/<date>-<slug>.md` directly using [templates/report.md](templates/report.md), or file an existing file with `inga add file.md -p my-project`.

## Report fields

| Field | Type | Set by |
|---|---|---|
| `id` | string, `YYYYMMDD-xxxxxx` | auto |
| `date` | ISO date/datetime (required) | agent |
| `name` | string (required) | agent |
| `project` | slug (required) | agent |
| `author` | string | agent |
| `type` | research · review · summary · status · analysis · other | agent |
| `summary` | string | agent |
| `tags` | list | agent / Inga |
| `source` | URL / PR / session link | agent |
| `related` | list of ids | agent / Inga |
| `star` | bool | Inga |
| `reading_list` | bool | Inga |
| `status` | unread · read · archived | Inga |
| `read_at` | datetime | auto |
| `rating` | 1–5 | Inga |
| `notes` | string | Inga |

The index also stores `path`, `word_count`, `content_hash`, `created_at` and `updated_at`.

## Development

```bash
pip install -e '.[dev]'
pytest
```

Next up: a local web UI on top of the same index, and an MCP server so agents can file and search reports as tool calls.
