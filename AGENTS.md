# Filing a report in Inga's Notebook

You're an agent and you've written a report. Here's how to file it so Inga can find it.

## Option A: use the CLI (preferred)

```bash
inga new --project my-project --name "What I found about X" \
  --type research --topic fundraising --tags "x,perf" --author "claude (session link)" \
  --summary "One or two sentences." --body-file report-body.md
```

Pipe the body in with `--body-file -`. The command prints the path of the new file. Without `--body-file` it writes a template for you to fill in.

## Option B: write the file yourself

Create `reports/<project>/<YYYY-MM-DD>-<slug>.md`, starting with YAML frontmatter:

```markdown
---
date: 2026-11-08T14:30:00
name: What I found about X
project: my-project
topic: fundraising
author: claude (session link)
type: research
summary: One or two sentences.
tags: [x, perf]
source: https://github.com/owner/repo/pull/123
---

# What I found about X
...
```

Or write the file anywhere and run `inga add path/to/file.md --project my-project`. The CLI fills in the id and date, and moves the file into place.

## Fields

| Field | Required | Set by | Notes |
|---|---|---|---|
| `id` | auto | tool | assigned on first sync if missing (`YYYYMMDD-xxxxxx`) |
| `date` | yes | agent | ISO date or datetime |
| `name` | yes | agent | title; falls back to the first `# heading` |
| `project` | yes | agent | lowercase slug; falls back to the folder name |
| `topic` | recommended | agent | what it's about; must be on the list in `.inga/config.yaml` (see `inga topics`) |
| `author` | recommended | agent | which agent, model or session wrote it |
| `type` | recommended | agent | `research`, `review`, `summary`, `status`, `analysis`, `other` |
| `summary` | recommended | agent | 1–2 sentence TL;DR shown in listings |
| `tags` | recommended | agent/Inga | list of lowercase tags |
| `source` | optional | agent | URL, PR or session that produced it |
| `related` | optional | agent/Inga | ids of related reports |
| `supersedes` | optional | agent | ids of older reports this one replaces; they get marked obsolete |
| `superseded_by` | — | tool/Inga | set on the old report when it's replaced |
| `star` | — | **Inga** | do not set |
| `reading_list` | — | **Inga** | do not set |
| `status` | — | **Inga** | `unread` / `read` / `archived` / `obsolete` |
| `read_at` | — | tool | stamped when marked read |
| `rating` | — | **Inga** | 1–5 |
| `notes` | — | **Inga** | margin notes |
| `obsolete_reason`, `obsolete_at` | — | **Inga**/tool | set when a report is marked obsolete |

## Replacing an older report

If your report updates or replaces an earlier one, list the older report's id under `supersedes:` (or pass `--supersedes <id>` to `inga new`). The older report is then marked obsolete and links to yours. Find ids with `inga list` or `inga search`.

Before you finish, run `inga validate` to check your file.
