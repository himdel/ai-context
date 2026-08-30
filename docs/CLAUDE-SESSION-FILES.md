# Claude Code live session files

Reference for `~/.claude/sessions/<pid>.json`, which contexts reads to pair tmux panes
with conversations. Confirmed against Claude Code v2.1.238 - re-verify before relying on
a field, this is not a documented API.

The filename is the claude process PID.

| Field | Meaning |
|---|---|
| `pid` | same as the filename |
| `sessionId` | the conversation id |
| `cwd` | working directory |
| `procStart` | process start time - reboot-safe identity key alongside pid |
| `status` | `busy` / `idle` / `waiting`, plus `updatedAt` and `statusUpdatedAt` |
| `waitingFor` | present when `waiting`, e.g. `"input needed"` |
| `name`, `nameSource` | claude's own derived name, e.g. `contexts-bc` |
| `kind`, `version`, `peerFeatures` | `interactive`; e.g. `notify_idle` |

`waitingFor` is a native machine-readable "needs input or permission" signal - detecting
it needs no TUI scraping.

## Two behaviours that cost time

**The file is created lazily**, only once the session produces its first output - *not* at
process spawn. A fresh or untrusted folder blocks on the trust prompt first, so the file
appears late. This is why time-based cron-to-conversation pairing fired too soon and
failed, and why pairing is now deterministic instead (DECISIONS 2026-08-22).

**`status` / `waitingFor` can get stuck.** Confirmed 2026-08-24: a live session's file
read `waiting` / `waitingFor: "permission prompt"` for over five minutes while its pane
showed no prompt. Do not trust the file's waiting state alone in the UI - reconcile
against a live `tmux capture-pane` parse. The conversation session-bar does this, and
shows `waiting` only when the pane actually has a prompt.

## Pairing under tmux

`tmux list-panes -F '#{pane_pid}'` gives the claude PID directly - the pane runs `claude`
with no shell wrapper, and its children are just threads. So
`pane_pid` -> `<pane_pid>.json` -> `sessionId` is a deterministic pairing.
