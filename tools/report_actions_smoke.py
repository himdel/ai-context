#!/usr/bin/env python3
"""Check the running confirmation UI in isolated Chrome, with every action API mocked.

No proposals are registered or submitted to Contexts. Requires google-chrome and
the optional websockets Python package. CONTEXTS_UI defaults to localhost:8062.
"""

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

UI = os.environ.get("CONTEXTS_UI", "http://localhost:8062").rstrip("/")
PORT = int(os.environ.get("CONTEXTS_DEBUG_PORT", "9351"))
ACTION_ID = "00000000-0000-4000-8000-000000000001"

FIXTURE = r"""
const kind = new URL(location.href).searchParams.get('case') || 'recent';
const age = {recent: 1, aging: 4, stale: 8, old: 90}[kind] || 1;
window.__posts = [];
const action = {
  id: '00000000-0000-4000-8000-000000000001',
  label: 'Investigate <img src=x onerror=alert(1)>',
  text: 'Review only; do not modify anything.',
  submitted_text: '', submitted_at: null, result: {},
  title: 'Fixture report', report_path: '~/reports/fixture.md',
  report_created_at: new Date(Date.now() - age * 86400000).toISOString(),
  freshness: {days: age, level: ['recent', 'aging', 'stale', 'old'].includes(kind) ? kind : 'recent',
    requires_acknowledgement: age >= 7},
  mode: kind === 'exclusive' ? 'exclusive' : 'independent',
  status: kind === 'uncertain' ? 'uncertain' : 'pending',
  selected_action: kind === 'exclusive' ? '00000000-0000-4000-8000-000000000002' : null,
  choices: [
    {id: '00000000-0000-4000-8000-000000000001', label: 'Investigate', status: 'pending', url: '#inert'},
    {id: '00000000-0000-4000-8000-000000000002', label: 'Defer', status: 'submitted', url: '#inert'}
  ],
  source: 'opencode', project: '/fixture/project', conversation_id: 'ses_source',
  conversation_url: '/conversations/ses_source', source_active: true,
  source_changed: kind === 'changed', problem: '',
  can_submit: !['uncertain', 'exclusive'].includes(kind)
};
window.fetch = async (input, options = {}) => {
  const url = new URL(input, location.href);
  if (!url.pathname.startsWith('/api/report-actions/')) throw new Error('Unexpected fetch: ' + input);
  if (kind === 'missing') return new Response(JSON.stringify({error: 'Saved action missing. Nothing was submitted.'}), {status:404});
  if (options.method === 'POST') {
    window.__posts.push(JSON.parse(options.body));
    action.status = 'submitted';
    action.submitted_text = window.__posts[0].text;
    action.can_submit = false;
    action.result = {conversation_id: 'ses_fixture_fork'};
    if (kind === 'network-loss') throw new Error('Simulated lost response after claim');
    return new Response(JSON.stringify({status: 'submitted'}));
  }
  return new Response(JSON.stringify(action));
};
"""


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.errors = []

    async def call(self, method, **params):
        self.n += 1
        await self.ws.send(
            json.dumps({"id": self.n, "method": method, "params": params})
        )
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("method") == "Runtime.exceptionThrown":
                self.errors.append(message["params"])
            if message.get("id") == self.n:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    async def js(self, expression):
        result = await self.call(
            "Runtime.evaluate",
            expression=expression,
            awaitPromise=True,
            returnByValue=True,
        )
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result["result"].get("value")

    async def until(self, expression):
        try:
            async with asyncio.timeout(10):
                while not await self.js(expression):
                    await asyncio.sleep(0.05)
        except TimeoutError:
            body = await self.js("document.body?.innerText")
            raise AssertionError(
                f"Timed out: {expression}\n{body}\n{self.errors}"
            ) from None


async def checks(page):
    await page.call("Page.enable")
    await page.call("Runtime.enable")
    await page.call("Page.addScriptToEvaluateOnNewDocument", source=FIXTURE)

    async def visit(kind):
        await page.call("Page.navigate", url=f"{UI}/actions/{ACTION_ID}?case={kind}")
        await page.until("!!document.getElementById('submit')")
        await page.until(
            "!document.getElementById('error').hidden"
            if kind == "missing"
            else "!document.getElementById('proposal').hidden"
        )
        assert await page.js("window.__posts.length === 0"), (
            "Viewing triggered submission"
        )

    await visit("recent")
    assert await page.js("!document.getElementById('submit').disabled")
    assert await page.js("!document.querySelector('#label img')"), (
        "Label HTML was not inert"
    )
    assert await page.js(
        "document.getElementById('source-state').textContent.includes('left untouched')"
    )
    for theme, expected in (
        ("light", "rgb(139, 61, 255)"),
        ("dark", "rgb(185, 135, 255)"),
    ):
        await page.call(
            "Emulation.setEmulatedMedia",
            features=[{"name": "prefers-color-scheme", "value": theme}],
        )
        assert await page.js(
            f"getComputedStyle(document.getElementById('source')).color === {expected!r}"
        )
    await page.call("Emulation.setEmulatedMedia", features=[])
    await page.js("""
      document.getElementById('message').value = 'An edited, specific instruction.';
      document.getElementById('submit').click();
      document.getElementById('submit').click();
    """)
    await page.until(
        "document.getElementById('status').textContent.includes('Already submitted')"
    )
    assert await page.js(
        "window.__posts.length === 1 && window.__posts[0].text === 'An edited, specific instruction.'"
    )
    assert await page.js(
        "document.getElementById('submit').disabled && document.getElementById('message').readOnly"
    )
    assert await page.js(
        "document.querySelector('#result a').getAttribute('href') === '/conversations/ses_fixture_fork'"
    )
    print(
        "ok  recent action, exact edited message, double-click guard, result link, purple in both themes"
    )

    for kind in ("aging", "stale", "old"):
        await visit(kind)
        assert await page.js(f"document.getElementById('age').className === {kind!r}")
        assert await page.js(
            "document.getElementById('age').textContent.includes('Report generated')"
        )
        if kind != "aging":
            assert await page.js(
                "document.getElementById('submit').disabled && !document.getElementById('stale-ack').hidden"
            )
            await page.js("document.getElementById('ack').click()")
            assert await page.js("!document.getElementById('submit').disabled")
    print("ok  progressively stronger age bands and explicit stale acknowledgement")

    for kind, text in (
        ("exclusive", "Another choice"),
        ("uncertain", "could not be confirmed"),
    ):
        await visit(kind)
        assert await page.js(
            f"document.getElementById('status').textContent.includes({text!r})"
        )
        assert await page.js("document.getElementById('submit').disabled")
    await visit("changed")
    assert await page.js(
        "document.getElementById('source-state').textContent.includes('changed since')"
    )
    await visit("missing")
    assert await page.js(
        "document.getElementById('error').textContent.includes('Nothing was submitted')"
    )
    print(
        "ok  exclusive-choice lockout, uncertain result, changed source, explanatory missing action"
    )

    await visit("network-loss")
    await page.js("document.getElementById('submit').click()")
    await page.until(
        "document.getElementById('status').textContent.includes('Already submitted')"
    )
    assert await page.js(
        "window.__posts.length === 1 && document.getElementById('submit').disabled"
    )
    print("ok  lost response reconciles consumed state without resubmitting")


async def main():
    # Fail rather than accidentally connecting to another browser's debugging port.
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", PORT))
    profile = Path(tempfile.mkdtemp(prefix="contexts-action-browser-"))
    chrome = subprocess.Popen(
        [
            "google-chrome",
            "--headless=new",
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={profile}",
            "--window-size=1200,900",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/json"
                ) as response:
                    targets = [t for t in json.load(response) if t["type"] == "page"]
                if targets:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Isolated Chrome did not start")
        async with websockets.connect(
            targets[0]["webSocketDebuggerUrl"], max_size=None
        ) as ws:
            await checks(Page(ws))
    finally:
        os.killpg(chrome.pid, signal.SIGTERM)
        chrome.wait(timeout=10)
        shutil.rmtree(profile)


if __name__ == "__main__":
    asyncio.run(main())
