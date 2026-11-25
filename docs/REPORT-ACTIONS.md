# Local report actions

Saved proposals let an ordinary Markdown report offer a confirmed follow-up in
the context of its originating coding-agent conversation. The bundled
[`report-actions` skill](../contrib/skills/report-actions/SKILL.md) is the authoring
guide. It is optional: Contexts itself does not require installing the skill.

## API

All new endpoints and the confirmation page require a loopback socket peer,
including IPv6 and IPv4-mapped loopback addresses. Forwarded headers cannot grant
access. This is deliberately stricter than the rest of Contexts when `BIND` serves
the LAN. Do not expose these routes through a loopback reverse proxy: the socket
check cannot identify a remote client behind it. This is not broader API hardening.

Every route works with or without a trailing slash.

- `POST /api/report-actions`: register an immutable group and its proposals.
  Required: `title`, `source`, `conversation_id`, `actions` (1-30 objects with
  `label` and `text`). Optional: `mode` (`independent`, default, or `exclusive`),
  `report_path`, `report_created_at` (timezone-aware ISO-8601, defaults to now).
  Returns `group_id`, `mode`, `actions` with stable UUIDs, labels and page URLs,
  plus `conversation_id` and an absolute originating `conversation_url`.
  The original project is resolved from the source conversation, not caller input.
  Registration never launches anything.
- `GET /actions/<UUID>`: inert confirmation page. Missing saved IDs show an
  explanation once the page requests its record; nothing is launched.
- `GET /api/report-actions/<UUID>`: proposal, group/choice status, original context,
  age band, changed-history/live-source hints, current launch availability and
  saved outcome, source `conversation_url`, and optional mdview `report_url`.
  Responses are not cached.
- `POST /api/report-actions/<UUID>/submit`: explicit JSON confirmation with
  `{"confirm":"fork"}` and optional edited `text`. For reports at least seven days
  old, also require `"acknowledge_stale":true`. Browser requests must be same-origin.
  Success means **launch confirmed**, not agent work completed.

Action records live in the selected Contexts database, not the report file. Keep
that database and port/instance stable for old links. No automatic expiry or pruning.
Opening a link on a different host cannot find the original database.

## Report and session navigation

The confirmation page makes the report path a link into mdview and the source
session ID a link into Contexts. These and known follow-up IDs open new tabs, so
reviewing evidence does not discard an edited confirmation message.

Set `MDVIEW_URL` in `contexts/settings_local.py` (or the named instance's settings)
to the mdview HTTP(S) origin; the default is `http://localhost:6821`. Set it to `""`
to keep report paths unlinked. mdview remains optional: preparing a backlink never
contacts it, reads the report file, or registers a viewer root.

Home-relative and absolute report paths beneath the server user's home are
supported; project-relative paths are resolved against the recorded source project.
Paths are normalized/URL-encoded without resolving symlinks, so existing symlink
aliases keep their mdview meaning. Empty/unrepresentable paths stay plain text.
This works for already-registered actions without a migration.

Backlinks open the **current file**, not a preserved report snapshot; the page
explicitly warns that a recurring report may have overwritten it. Prefer timestamped
report filenames when retaining evidence from multiple runs.

Reports themselves should include an **Originating session** link whose label is
the exact session ID, even without action proposals. The bundled registration helper
includes that link in its normal Markdown output. `--provenance-only` prints it
without any API request or registration; the author still needs the exact source
session and correct instance, not a guessed recent conversation.

## Forks and delivery

Every confirmed proposal forks, regardless of whether its source is live or idle.
Use the existing harness fork contract: create a known fork ID first where supported
(OpenCode V2), otherwise use the harness CLI's explicit fork flag (Claude/V1). Pass
the confirmed text as the initial prompt. Never send keys to the source, resume it,
or choose a different conversation/directory when the original is unavailable.
The fork uses source history at confirmation time; it is not pinned to the report's
message boundary. The page calls that out and warns when history has changed.
Project files are shared and may change between report generation and execution.

Claims are persisted **before** invoking a harness, using conditional writes in a
short transaction:

- Independent group: each action transitions once from `pending` to `submitting`.
- Exclusive group: the first confirmation claims `selected_action` as well; every
  sibling becomes unavailable even if launch fails.
- A confirmed launch becomes `submitted`, retaining the exact submitted message,
  timestamp, fork ID where known, and tmux/pid result.
- A failed or ambiguous launch becomes `uncertain`. A crash after claiming may
  leave `submitting`; both are consumed and instruct the reader to inspect first.

This guarantees at-most-one launch attempt per saved proposal, not exactly-once
prompt delivery across arbitrary CLI/process failures. There is intentionally no
automatic retry/reset API. Re-registering a report creates new proposals, so
authors must retain existing links rather than bypassing submission state.

When the harness only discovers its fork ID after launch, the result gives the tmux
session name; normal Contexts conversation pairing makes it visible in the main UI.
With tmux enabled, report actions launch detached without an extra terminal viewer.
If tmux is disabled/unavailable, the existing launcher falls back to a terminal.

## Age and visual convention

The original `report_created_at` controls age, not the registration or click time:

| Age | Notice |
|---|---|
| 0-2 days | Normal date and age |
| 3-6 days | Aging notice with stronger border/background |
| 7-29 days | Prominent stale warning plus acknowledgement |
| 30+ days | Strongest old-report warning plus acknowledgement |

Age is refreshed on page focus and checked again by the submit API. It does not
expire links. Missing sessions/projects are a separate hard refusal.

**Continuation violet** is `#8B3DFF`, with `#B987FF` for readable link text on dark
surfaces. It is reserved for links to proposed continuations and their review page.
Ordinary Markdown links work anywhere; mdview recognizes HTTP(S) loopback
`/actions/<UUID>` links on any port, adds a review tooltip, and styles normal,
visited, hover and focus states. Contexts uses the same convention in transcripts.
Neither renderer fetches action metadata or triggers work while rendering.
Purple is not an authentication or approval signal.

## Optional authoring/browser tooling

Install the bundled skill by linking `contrib/skills/report-actions` into your
agent's global skills directory. Its registration helper uses only Python's
standard library and never submits actions.

Backend checks live in `api/tests/test_report_actions.py` and
`api/tests/test_report_action_skill.py`. `python3 tools/report_actions_smoke.py`
checks the running UI with a separate headless Chrome/profile and mocked action
APIs: it never registers or executes real proposals. **Optional test dependencies:**
`google-chrome` and the Python `websockets` package. Override `CONTEXTS_UI` and
`CONTEXTS_DEBUG_PORT` to target another instance/free debugging port.
