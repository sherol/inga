# inga

**Inga's Notebook**: a markdown reports database for the reports agents write.

Agents drop markdown files into `reports/<project>/`. Inga browses them, stars the good ones, keeps a reading list, and writes notes in the margins.

## Who is Inga?

Inga comes from a thought experiment in Andy Clark and David Chalmers' 1998 paper *The Extended Mind*.

Inga hears about an exhibition at the Museum of Modern Art. She remembers the museum is on 53rd Street, and she walks there. Otto has Alzheimer's disease, so he writes everything down in a notebook he always carries. When he hears about the same exhibition, he looks up the address in his notebook and walks there too.

Clark and Chalmers argue that Otto's notebook does the same job as Inga's memory: it is reliable, always to hand, and he trusts what's in it. So the notebook is part of how Otto thinks. The mind doesn't have to stop at the skull.

This project gives Inga a notebook as well. Agents do work and write it up, and the notebook keeps it findable, trusted and to hand, so their work becomes part of what she knows. The reports are the notebook's pages. Stars, the reading list and margin notes are how she makes it hers.

- **Markdown files are the source of truth.** Each report is a `.md` file with YAML frontmatter. Everything (including stars and the reading list) lives in the files, so git tracks it all.
- **SQLite is just an index.** `.inga/index.db` is built from the files for fast filtering and full-text search. It's gitignored, and you can delete it any time and rebuild it with `inga reindex`.

## Install

```bash
pip install -e .
```

## Quick tour

```bash
inga list                         # newest first; • = unread
inga list --starred               # also: --reading-list, --unread, --project, --topic, --tag, --type, --since, --until, --all
inga search "cold start"          # full-text search (FTS5 syntax: "phrase", a OR b, pref*)
inga show 20261108-ab             # id, unique id prefix, or part of the filename
inga show 20261108-ab -m          # ...and mark it read

inga star <id>    / unstar
inga queue <id>   / dequeue       # reading list; `inga queue` alone shows it
inga read <id>    / unread        # marking read also takes it off the reading list
inga archive <id>                 # hidden from lists unless --all
inga obsolete <id> --by <newer-id> --reason "figures updated"   # out of date; hidden unless --all
inga unobsolete <id>
inga rate <id> 4                  # 1–5, 0 clears
inga note <id> "follow up with Sam"
inga tag <id> --add a,b --remove c
inga set-topic <id> grants

inga projects                     # counts per project
inga topics                       # counts per topic, including unused ones on the list
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
| `topic` | one value from the topic list | agent / Inga |
| `author` | string | agent |
| `type` | research · review · summary · status · analysis · other | agent |
| `summary` | string | agent |
| `tags` | list | agent / Inga |
| `source` | URL / PR / session link | agent |
| `related` | list of ids | agent / Inga |
| `supersedes` | ids of reports this one replaces | agent / Inga |
| `superseded_by` | id of the report that replaced this one | agent / Inga |
| `star` | bool | Inga |
| `reading_list` | bool | Inga |
| `status` | unread · read · archived · obsolete | Inga |
| `read_at` | datetime | auto |
| `rating` | 1–5 | Inga |
| `notes` | string | Inga |
| `obsolete_reason` | string | Inga |
| `obsolete_at` | datetime | auto |

### Project, topic, type and tags

- **project**: which piece of work it's for (`spring-gala-2027`).
- **topic**: what it's about (`fundraising`). This comes from the list in `.inga/config.yaml`, which you can edit. Delete the list to allow any topic.
- **type**: what kind of report it is (`research`, `review`, …).
- **tags**: any extra labels (`q1`, `follow-up`).

### Obsolete reports

A report is obsolete when it's out of date. Obsolete reports are hidden from `list` and `search` unless you pass `--all`, and `show` puts a red banner on them that says what replaced them. There are three ways to mark one:

- `inga obsolete <old> --by <new>` from the CLI.
- An agent writes a newer report with `supersedes: [<old id>]`, or uses `inga new --supersedes <old id>`.
- Someone sets `superseded_by: <new id>` in the old report's file.

The last two are picked up on the next command you run, and the change is written into the old report's file.

The index also stores `path`, `word_count`, `content_hash`, `created_at` and `updated_at`.

## Development

```bash
pip install -e '.[dev]'
pytest
```

Next up: a local web UI on top of the same index, and an MCP server so agents can file and search reports as tool calls.
