---
name: report-actions
description: Link local Markdown reports to their originating Contexts sessions, and optionally add explicitly confirmed follow-up actions or decision choices. Covers mdview reports and Contexts cronjobs.
---

# Local report actions

Use for local Markdown report provenance and, when useful, concrete next actions
or choices. Do not pad reports with invented follow-ups.

## Link the originating session

Include an **Originating session** link to the exact conversation in the correct
Contexts instance, even when the report offers no actions. Make the session ID
itself the link label so it remains identifiable when copied. Never guess the
session or use whichever instance happens to answer.

For a report with no actions, the helper prints that Markdown without registering
anything or making an HTTP request:

```sh
uv run --no-project python ~/.claude/skills/report-actions/register.py --provenance-only
```

It uses `OPENCODE_SESSION_ID` and `CONTEXTS_URL` as described below. For other
harnesses, pass the exact `--source` and `--conversation`. If session identity or
instance is unknown, say provenance is unavailable rather than inventing a link.

## Contract

- A report action is a **proposal**, not permission to execute. Registering it and
  opening its link are inert. Never call the submit API on the reader's behalf.
- Confirmation always **forks** the source conversation with the exact editable
  user message. Never take over a live session. Forks inherit conversation history,
  not a filesystem snapshot or isolated worktree.
- Choose `independent` for several useful actions (each can run once), or
  `exclusive` for alternatives (one choice consumes the whole group). Use separate
  registrations for separate decision groups within the same report.
- Contexts owns durable records, grouping and submission status. A submitted or
  uncertain action stays consumed; do not re-register it to bypass that guard.
- Links are local to the host **and Contexts instance** that created them. Do not
  put them in shared/published reports or assume localhost on another machine
  points to the same service.
- Ordinary Markdown links are enough. mdview and Contexts recognize the local
  `/actions/<UUID>` URL shape and apply continuation violet (`#8B3DFF`, light text
  variant `#B987FF` on dark surfaces). Color means "review a proposed continuation",
  not "trusted" or "already approved". No inline HTML, scripts or custom URI scheme.

## Prepare the proposal

Identify the **exact source session** and harness. In OpenCode the current session
ID is `OPENCODE_SESSION_ID`; the helper uses it automatically. For Claude or a
different source, supply the actual harness session ID explicitly. Never choose
the most recent conversation, a tmux name, or the latest cron run as a guess.

Use the Contexts instance that can read that session:
`CONTEXTS_URL` or `--base-url` (default `http://localhost:8062`; a personal instance
may use a different port). Only loopback destinations are accepted.

Create a JSON object like this in the report's workspace:

```json
{
  "title": "Weekly review",
  "report_path": "~/reports/weekly-review.md",
  "mode": "exclusive",
  "actions": [
    {
      "label": "Investigate the failures",
      "text": "Follow up on the failures in ~/reports/weekly-review.md. Recheck the evidence against the current project before making changes, then investigate the cause. Do not publish or push changes without asking."
    },
    {
      "label": "Record a deferral",
      "text": "Review ~/reports/weekly-review.md and help me record a reasoned deferral of the reported failures. Do not modify the affected code."
    }
  ]
}
```

These examples only describe investigation/documentation; they do not authorize
destructive operations. Write messages that say what this particular action means,
reference the durable report, include relevant scope/exclusions, and ask the
follow-up to revalidate evidence. Avoid vague prompts such as "do option 2".

For an existing report, include its **original** `report_created_at` as an ISO-8601
timestamp with timezone. Never reset an old report's age by registering it today.
If omitted, the API uses the registration time, suitable for a newly generated report.

## Register and include the links

```sh
uv run --no-project python ~/.claude/skills/report-actions/register.py proposals.json
```

Or pass the exact source explicitly:

```sh
uv run --no-project python ~/.claude/skills/report-actions/register.py proposals.json \
  --source claude --conversation ACTUAL_SESSION_ID
```

`register.py` only calls the registration endpoint. It prints Markdown links ready
to include under "Follow-up actions" or "Choose one next step". `--json` prints the
registration result instead. Source fields can also be stored in the JSON object.
Its normal output starts with the originating-session link; put that in the
report's metadata/header rather than duplicating it for every action group.

Supply `report_path` as a home-relative (`~/...`) or absolute path, or relative to
the source project. The confirmation page links it back into mdview, alongside a
clickable source session ID in Contexts. Those links open new tabs to preserve
edited messages. The mdview origin is configurable through Contexts' `MDVIEW_URL`
(default `http://localhost:6821`; empty disables report backlinks).

The report backlink opens the **current file**, not a report-time snapshot.
Prefer timestamped report filenames so a later cron run does not overwrite the
evidence linked by earlier actions. Keep the original timestamp when linking an
existing report.

Use the URLs returned by Contexts verbatim. Do not invent UUIDs, put prompts in
URLs, embed API submit links, or request the action endpoints while rendering.
Preserve existing links when editing a report rather than registering duplicates.

If Contexts is unavailable or cannot load the exact source session, finish the
report with clearly labeled **plain-text suggestions** and state that actionable
links could not be prepared. Do not silently create a fresh context-free session,
start Contexts, run migrations, or change configuration from a report cronjob.

## What the reader sees

The confirmation page shows the original report/date, project, harness, source
conversation, exact editable message, group semantics, and current submission
status. A changed source-history warning is separate from report age.

- 0-2 days: normal date/age notice.
- 3-6 days: more visible aging warning.
- 7-29 days: prominent stale warning and explicit acknowledgement.
- 30+ days: strongest old-report warning, also requiring acknowledgement.

These are warnings, not expiration: old evidence can still be useful after review.
Missing sessions/projects get a refusal, not a fallback. Confirmation is local-only,
even when the rest of Contexts serves a LAN. Remote readers must use the originating
host; changing a hostname in the link does not grant execution.

Implementation/API reference: `docs/REPORT-ACTIONS.md` in the Contexts checkout.
