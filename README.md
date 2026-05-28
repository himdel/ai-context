# context

Vibe-coded tool to browse Claude Code data in a web UI.

Reads `~/.claude/` and exposes conversation history, plans, skills, and memory
in a searchable, markdown-rendered interface with support for resuming, forking,
and starting new sessions.

(DO NOT expect this to be safe, secure, or complete)

## Features

### Conversations
- Full-text search with SQLite-backed index
- Markdown rendering with syntax highlighting and Mermaid diagram rendering
- Tool use blocks with inline results, thinking blocks, subagent threads
- Edit blocks rendered as diffs
- Skill invocations collapsed under their prompt
- Timestamps, copy-as-markdown, expand/collapse all
- Resume, fork, or start new sessions from the UI
- Active session indicator (green dot + favicon badge)
- Status bar showing running tasks and agents
- Auto-refresh on tab focus, live tailing for active conversations

### Plans
- Grouped by repo, linked back to originating conversation
- Full markdown rendering with Execute button to launch a new session

### Skills
- Browse, create, edit, and delete global and repo-scoped skills
- Open in $EDITOR, run button with repo chooser for global skills
- Recent invocations with links to originating conversations

### Memory
- Browse, edit, and delete persistent memory items (with $EDITOR support)
- Type badges (user, feedback, project, reference)
- Linked to originating conversation and project

### Git & forge integration
- GitHub, GitLab, and Gitea/Codeberg support
- PR/MR detection for current branch (status shown in header)
- Autolinks for GitHub issues (#123) and configurable Jira-style references
- Clickable commit SHAs — opens `git show` locally, with forge link
- Deterministic repo icon + color tint per repository

### Home screen
- Conversations grouped by repo with active/recent sections
- Tabs for Conversations, Plans, Skills, Memory, Activity
- Activity heatmap showing conversation frequency over time
- New session launcher per repo
- SPA with direct URL routing and browser history

## Screenshots

![](./screenshots/conversation.png)

| Home | Skill |
|---|---|
| ![](./screenshots/home.png) | ![](./screenshots/skill.png) |

| Plan | Memory |
|---|---|
| ![](./screenshots/plan.png) | ![](./screenshots/memory.png) |

## Usage

```
git clone https://github.com/himdel/ai-context
cd ai-context
make migrate # local sqlite file
make
```

```
open http://localhost:8042
```

Tweak `contexts/settings.py` if your terminal is not `rxvt-unicode`, X display not `:0`, etc.
