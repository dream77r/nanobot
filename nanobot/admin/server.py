"""Admin web panel for nanobot — aiohttp server with inline SPA."""

import base64
import json
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from loguru import logger

_START_TIME = time.time()


class AdminServer:
    """Lightweight admin panel served via aiohttp."""

    def __init__(
        self,
        port: int = 18791,
        password: str = "",
        agent_loop: Any = None,
        session_manager: Any = None,
        cron_service: Any = None,
        channels: list[str] | None = None,
    ):
        self.port = port
        self.password = password
        self.agent_loop = agent_loop
        self.session_manager = session_manager
        self.cron_service = cron_service
        self.channels = channels or []
        self._runner: web.AppRunner | None = None

    # ── Auth middleware ───────────────────────────────────────────────

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        if not self.password:
            return await handler(request)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode()
                _, pwd = decoded.split(":", 1)
                if pwd == self.password:
                    return await handler(request)
            except Exception:
                pass
        return web.Response(
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="nanobot admin"'},
            text="Unauthorized",
        )

    # ── Routes ────────────────────────────────────────────────────────

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(content_type="text/html", text=_INDEX_HTML)

    async def _handle_status(self, request: web.Request) -> web.Response:
        uptime = int(time.time() - _START_TIME)
        model = getattr(self.agent_loop, "model", "unknown") if self.agent_loop else "unknown"

        cron_info: dict[str, Any] = {}
        if self.cron_service:
            cron_info = self.cron_service.status()

        data = {
            "model": model,
            "uptime_seconds": uptime,
            "uptime_human": _format_uptime(uptime),
            "channels": self.channels,
            "cron": cron_info,
        }
        return web.json_response(data)

    async def _handle_sessions(self, request: web.Request) -> web.Response:
        if not self.session_manager:
            return web.json_response([])

        raw = self.session_manager.list_sessions()
        # Enrich with message count
        result = []
        for s in raw:
            key = s.get("key", "")
            session = self.session_manager.get_or_create(key)
            result.append({
                "key": key,
                "messages": len(session.messages),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
            })
        return web.json_response(result)

    async def _handle_session_detail(self, request: web.Request) -> web.Response:
        key = request.match_info["key"]
        if not self.session_manager:
            return web.json_response({"error": "no session manager"}, status=500)

        session = self.session_manager.get_or_create(key)
        messages = []
        for m in session.messages[-100:]:  # last 100
            messages.append({
                "role": m.get("role"),
                "content": (m.get("content") or "")[:500],
                "timestamp": m.get("timestamp"),
                "tools_used": m.get("tools_used"),
            })
        return web.json_response({"key": key, "messages": messages})

    async def _handle_files(self, request: web.Request) -> web.Response:
        root = Path.home() / ".nanobot"
        tree = _build_file_tree(root, depth=3)
        return web.json_response(tree)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/api/status", self._handle_status)
        app.router.add_get("/api/sessions", self._handle_sessions)
        app.router.add_get("/api/sessions/{key}", self._handle_session_detail)
        app.router.add_get("/api/files", self._handle_files)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(f"Admin panel started on http://0.0.0.0:{self.port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None


# ── Helpers ───────────────────────────────────────────────────────────

def _format_uptime(seconds: int) -> str:
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def _build_file_tree(root: Path, depth: int = 3) -> list[dict]:
    """Build a file tree up to given depth."""
    if depth <= 0 or not root.is_dir():
        return []
    result = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    except PermissionError:
        return []
    for entry in entries:
        if entry.name.startswith("__pycache__"):
            continue
        node: dict[str, Any] = {"name": entry.name, "type": "dir" if entry.is_dir() else "file"}
        if entry.is_file():
            try:
                node["size"] = entry.stat().st_size
            except OSError:
                node["size"] = 0
        if entry.is_dir():
            node["children"] = _build_file_tree(entry, depth - 1)
        result.append(node)
    return result


# ── Inline SPA HTML ───────────────────────────────────────────────────

_INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nanobot admin</title>
<style>
  :root { --bg: #1a1b26; --surface: #24283b; --border: #3b4261; --text: #c0caf5; --dim: #565f89; --accent: #7aa2f7; --green: #9ece6a; --red: #f7768e; --orange: #e0af68; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: 'SF Mono', 'Fira Code', monospace; background: var(--bg); color: var(--text); min-height: 100vh; }
  .header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; gap: 16px; }
  .header h1 { font-size: 18px; color: var(--accent); }
  .header .uptime { color: var(--dim); font-size: 13px; margin-left: auto; }
  .tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); background: var(--surface); }
  .tab { padding: 10px 24px; cursor: pointer; color: var(--dim); border-bottom: 2px solid transparent; transition: all 0.2s; font-size: 14px; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .content { padding: 24px; max-width: 960px; margin: 0 auto; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
  .card h3 { color: var(--accent); margin-bottom: 12px; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; }
  .row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 14px; }
  .row:last-child { border-bottom: none; }
  .label { color: var(--dim); }
  .value { color: var(--text); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
  .badge-green { background: rgba(158,206,106,0.15); color: var(--green); }
  .badge-orange { background: rgba(224,175,104,0.15); color: var(--orange); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--dim); padding: 8px; border-bottom: 1px solid var(--border); font-weight: normal; text-transform: uppercase; font-size: 11px; letter-spacing: 1px; }
  td { padding: 8px; border-bottom: 1px solid var(--border); }
  tr:hover td { background: rgba(122,162,247,0.05); }
  .clickable { cursor: pointer; color: var(--accent); }
  .clickable:hover { text-decoration: underline; }
  .msg { padding: 8px 12px; margin: 4px 0; border-radius: 6px; font-size: 13px; line-height: 1.5; }
  .msg-user { background: rgba(122,162,247,0.1); border-left: 3px solid var(--accent); }
  .msg-assistant { background: rgba(158,206,106,0.1); border-left: 3px solid var(--green); }
  .msg-role { font-size: 11px; color: var(--dim); margin-bottom: 4px; }
  .back { color: var(--accent); cursor: pointer; font-size: 13px; margin-bottom: 12px; display: inline-block; }
  .back:hover { text-decoration: underline; }
  .tree { font-size: 13px; }
  .tree-item { padding: 3px 0; padding-left: 20px; }
  .tree-dir { color: var(--accent); cursor: pointer; }
  .tree-dir::before { content: '▶ '; font-size: 10px; }
  .tree-dir.open::before { content: '▼ '; }
  .tree-file { color: var(--dim); }
  .tree-size { color: var(--dim); font-size: 11px; margin-left: 8px; }
  .hidden { display: none; }
  #loading { text-align: center; padding: 40px; color: var(--dim); }
</style>
</head>
<body>
<div class="header">
  <h1>nanobot</h1>
  <span id="model-badge" class="badge badge-green"></span>
  <span class="uptime" id="uptime"></span>
</div>
<div class="tabs">
  <div class="tab active" onclick="switchTab('status')">Status</div>
  <div class="tab" onclick="switchTab('sessions')">Sessions</div>
  <div class="tab" onclick="switchTab('files')">Files</div>
</div>
<div class="content" id="app">
  <div id="loading">Loading...</div>
</div>
<script>
let currentTab = 'status';
let sessionData = null;

async function api(path) {
  const r = await fetch(path);
  return r.json();
}

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach((t, i) => {
    t.classList.toggle('active', ['status','sessions','files'][i] === tab);
  });
  if (tab === 'status') loadStatus();
  else if (tab === 'sessions') loadSessions();
  else if (tab === 'files') loadFiles();
}

async function loadStatus() {
  const d = await api('/api/status');
  document.getElementById('uptime').textContent = d.uptime_human;
  document.getElementById('model-badge').textContent = d.model;
  let cronHtml = '';
  if (d.cron && d.cron.jobs > 0) {
    cronHtml = `<div class="card"><h3>Cron</h3>
      <div class="row"><span class="label">Jobs</span><span class="value">${d.cron.jobs}</span></div>
      <div class="row"><span class="label">Running</span><span class="value">${d.cron.running ? 'yes' : 'no'}</span></div>
    </div>`;
  }
  document.getElementById('app').innerHTML = `
    <div class="card"><h3>Bot</h3>
      <div class="row"><span class="label">Model</span><span class="value">${d.model}</span></div>
      <div class="row"><span class="label">Uptime</span><span class="value">${d.uptime_human}</span></div>
      <div class="row"><span class="label">Channels</span><span class="value">${d.channels.join(', ') || 'none'}</span></div>
    </div>${cronHtml}`;
}

async function loadSessions() {
  const data = await api('/api/sessions');
  sessionData = data;
  let rows = data.map(s => `<tr>
    <td class="clickable" onclick="loadSession('${s.key}')">${s.key}</td>
    <td>${s.messages}</td>
    <td>${s.updated_at ? s.updated_at.slice(0,16).replace('T',' ') : '-'}</td>
  </tr>`).join('');
  document.getElementById('app').innerHTML = `<div class="card"><h3>Sessions</h3>
    <table><tr><th>Key</th><th>Messages</th><th>Updated</th></tr>${rows || '<tr><td colspan="3" style="color:var(--dim)">No sessions</td></tr>'}</table></div>`;
}

async function loadSession(key) {
  const d = await api('/api/sessions/' + encodeURIComponent(key));
  let msgs = d.messages.map(m => `<div class="msg msg-${m.role}">
    <div class="msg-role">${m.role}${m.timestamp ? ' · ' + m.timestamp.slice(11,16) : ''}${m.tools_used ? ' · ' + m.tools_used.join(', ') : ''}</div>
    ${escHtml(m.content)}
  </div>`).join('');
  document.getElementById('app').innerHTML = `
    <span class="back" onclick="loadSessions()">← Back to sessions</span>
    <div class="card"><h3>${escHtml(d.key)}</h3>${msgs || '<div style="color:var(--dim)">No messages</div>'}</div>`;
}

async function loadFiles() {
  const data = await api('/api/files');
  document.getElementById('app').innerHTML = `<div class="card"><h3>~/.nanobot/</h3><div class="tree">${renderTree(data)}</div></div>`;
}

function renderTree(items) {
  return items.map(i => {
    if (i.type === 'dir') {
      const id = 'dir-' + Math.random().toString(36).slice(2);
      return `<div class="tree-item"><span class="tree-dir" onclick="toggleDir('${id}', this)">${escHtml(i.name)}</span>
        <div id="${id}" class="hidden">${i.children ? renderTree(i.children) : ''}</div></div>`;
    }
    const size = i.size < 1024 ? i.size + 'B' : (i.size / 1024).toFixed(1) + 'KB';
    return `<div class="tree-item"><span class="tree-file">${escHtml(i.name)}</span><span class="tree-size">${size}</span></div>`;
  }).join('');
}

function toggleDir(id, el) {
  const div = document.getElementById(id);
  div.classList.toggle('hidden');
  el.classList.toggle('open');
}

function escHtml(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

loadStatus();
</script>
</body>
</html>
"""
