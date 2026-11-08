# Filing a report in Inga's Notebook

You're an agent and you've written a report. Here's how to file it so Inga can find it.

## Option A: use the CLI (preferred)

```bash
inga new --project my-project --name "What I found about X" \
  --type research --tags "x,perf" --author "claude (session link)" \
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
| `author` | recommended | agent | which agent, model or session wrote it |
| `type` | recommended | agent | `research`, `review`, `summary`, `status`, `analysis`, `other` |
| `summary` | recommended | agent | 1–2 sentence TL;DR shown in listings |
| `tags` | recommended | agent/Inga | list of lowercase tags |
| `source` | optional | agent | URL, PR or session that produced it |
| `related` | optional | agent/Inga | ids of related reports |
| `star` | — | **Inga** | do not set |
| `reading_list` | — | **Inga** | do not set |
| `status` | — | **Inga** | `unread` / `read` / `archived` |
| `read_at` | — | tool | stamped when marked read |
| `rating` | — | **Inga** | 1–5 |
| `notes` | — | **Inga** | margin notes |

Before you finish, run `inga validate` to check your file.
