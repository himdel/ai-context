"""Harness registry.

`settings.HARNESSES` lists the adapters to enable, in list order. An adapter
whose data is not present reports `available() is False` and is skipped
silently, so enabling one on a machine that does not have it is not an error.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_ADAPTERS = {}


def _build():
    if _ADAPTERS:
        return _ADAPTERS
    from api.harness.claude import ClaudeHarness
    from api.harness.opencode import OpencodeHarness

    for cls in (ClaudeHarness, OpencodeHarness):
        _ADAPTERS[cls.key] = cls()
    return _ADAPTERS


def enabled():
    """The available adapters named by settings.HARNESSES, in order."""
    adapters = _build()
    out = []
    for key in getattr(settings, "HARNESSES", ["claude"]):
        adapter = adapters.get(key)
        if adapter is None:
            logger.warning("unknown harness %r in settings.HARNESSES", key)
            continue
        try:
            if adapter.available():
                out.append(adapter)
        except Exception:
            logger.exception("harness %s failed its availability check", key)
    return out


def claude_adapter():
    """The Claude adapter, whether or not it is in settings.HARNESSES.

    Plans, skills, memories and the tmux session substrate are Claude-only
    features that reach into CLAUDE_DIR directly. They go through here so those
    paths stay in one module, and they keep working even if someone drops
    "claude" from the enabled list.
    """
    return _build()["claude"]


def get(key):
    for adapter in enabled():
        if adapter.key == key:
            return adapter
    return None


def owner_of(conversation_id, source=""):
    """The adapter owning an id - by recorded source, else by probing."""
    if source:
        adapter = get(source)
        if adapter is not None:
            return adapter
    for adapter in enabled():
        try:
            if adapter.owns(conversation_id):
                return adapter
        except Exception:
            logger.exception("harness %s failed owns()", adapter.key)
    return None


def load(conversation_id, source=""):
    adapter = owner_of(conversation_id, source)
    if adapter is None:
        return None
    try:
        return adapter.load(conversation_id)
    except Exception:
        logger.exception("harness %s failed to load %s", adapter.key, conversation_id)
        return None


def active_ids():
    ids = set()
    for adapter in enabled():
        try:
            ids |= adapter.active_ids()
        except Exception:
            logger.exception("harness %s failed active_ids()", adapter.key)
    return ids


def launch_argv(source, *, conversation_id="", prompt="", fork=False):
    """Argv starting `source`, or None when it is enabled but not launchable."""
    adapter = get(source or "claude")
    if adapter is None:
        return None
    try:
        return adapter.launch_argv(
            conversation_id=conversation_id, prompt=prompt, fork=fork
        )
    except Exception:
        logger.exception("harness %s failed launch_argv()", adapter.key)
        return None


def can_launch(source):
    return launch_argv(source) is not None
