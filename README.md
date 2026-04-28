# context

vibe-coded tool to show claude conversations in a web ui

(DO NOT expect this to be safe, secure, or complete)

This reads `~/.claude/` and exposes conversation history in a nice markdown-rendered web UI,
including plans, tool uses, subagents, etc.

For any git repos used as a base dir for a conversation, it also extracts the list of git remotes,
and enables autolinks when a github issue is mentioned. (upstream is preferred over origin, when both remotes are present)

Each conversation can be resumed/forked, and new conversations can be started - will run a new terminal with claude in that repo.

Conversations get rendered with different visual fingerprint per repo.
Also has a view for plans, and skills.

Indicators for active conversations, ability to tail -f a conversation,
copy as markdown button for messages,
shows the number of active conversations in the favicon.

---

Usage:

```
git clone https://github.com/himdel/ai-context
cd ai-context
make
```

```
open http://localhost:8042
```

Tweak `contexts/settings.py` if your terminal is not `rxvt-unicode`, X display not `:0`, etc.
