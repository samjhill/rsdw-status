#!/usr/bin/env python3
"""LAN page for an rsdw-dedicated server: running or not, and the current invite code.

Unofficial. Not part of the Jagex image.
"""

import json
import os
import re
import socket
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONTAINER = os.environ.get("RSDW_CONTAINER", "rsdw-dedicated")
LOG = Path("/logs/RSDragonwilds.log")
INI = Path("/config/DedicatedServer.ini")
PORT = int(os.environ.get("RSDW_STATUS_PORT", "8791"))
DIRECT_HOST = os.environ.get("RSDW_DIRECT_HOST", "").strip()
GAME_PORT = int(os.environ.get("RSDW_GAME_PORT", "7777"))
CODE_RE = re.compile(r'JoinCode"\] written with key\[[^\]]+\] value\[([A-Z0-9-]+)\]')

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dragonwilds</title>
<style>
  :root { color-scheme: light; }
  body {
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    font-family: ui-sans-serif, system-ui, sans-serif;
    background: #f3efe7; color: #1c1915;
  }
  main { width: min(26rem, calc(100% - 2rem)); padding: 1.5rem 0 2rem; }
  h1 { margin: 0; font-size: 0.85rem; letter-spacing: 0.14em; text-transform: uppercase; color: #6d645b; font-weight: 650; }
  .row { display: flex; align-items: center; gap: 0.55rem; margin-top: 0.85rem; font-size: 1.15rem; }
  .dot { width: 0.7rem; height: 0.7rem; border-radius: 50%; background: #b7aea4; flex: none; }
  .up .dot { background: #2c7a45; }
  .down .dot { background: #a33b32; }
  .code {
    margin: 1.35rem 0 0.85rem; font-size: clamp(2.4rem, 12vw, 3.4rem);
    letter-spacing: 0.06em; font-weight: 680; font-variant-numeric: tabular-nums;
  }
  .actions { display: flex; flex-wrap: wrap; gap: 0.6rem; }
  button {
    font: inherit; font-size: 1rem; padding: 0.75rem 1.15rem; border: 0; border-radius: 999px;
    background: #1c1915; color: #f3efe7; cursor: pointer;
  }
  button.secondary { background: transparent; color: #1c1915; box-shadow: inset 0 0 0 1px #1c1915; }
  button:disabled { opacity: 0.45; cursor: default; }
  .meta { margin-top: 1.6rem; color: #6d645b; line-height: 1.55; }
  .err { color: #a33b32; }
</style>
</head>
<body>
<main>
  <h1 id="title">Dragonwilds</h1>
  <div class="row" id="state"><span class="dot"></span><span id="label">Checking…</span></div>
  <div class="code" id="code">····-····</div>
  <div class="actions">
    <button id="copy" type="button" disabled>Copy invite code</button>
    <button id="copy-password" class="secondary" type="button" disabled>Copy password</button>
  </div>
  <p class="meta" id="meta"></p>
</main>
<script>
const titleEl = document.getElementById("title");
const codeEl = document.getElementById("code");
const labelEl = document.getElementById("label");
const stateEl = document.getElementById("state");
const copyEl = document.getElementById("copy");
const copyPasswordEl = document.getElementById("copy-password");
const metaEl = document.getElementById("meta");
let code = "";
let joinPassword = "";

function uptime(seconds) {
  if (seconds == null) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h) return h + "h " + m + "m";
  if (m) return m + "m";
  return seconds + "s";
}

async function refresh() {
  try {
    const res = await fetch("/api/status", { cache: "no-store" });
    const data = await res.json();
    const up = data.running === true;
    const name = data.name || "Dragonwilds";
    titleEl.textContent = name;
    document.title = name;
    stateEl.className = "row " + (up ? "up" : "down");
    labelEl.textContent = up ? "Up for " + uptime(data.uptime_seconds) : "Not running";
    code = data.invite_code || "";
    joinPassword = data.join_password || "";
    codeEl.textContent = code || "No code yet";
    copyEl.disabled = !code;
    copyPasswordEl.disabled = !joinPassword;
    copyPasswordEl.textContent = joinPassword ? "Copy password" : "No password";
    const bits = [joinPassword ? "Join password is " + joinPassword + "." : "No join password."];
    if (!up && code) bits.unshift("That code is from the last run. It changes when the server starts.");
    if (data.direct) bits.push("Direct connect " + data.direct + ", UDP " + data.port + ".");
    metaEl.className = "meta";
    metaEl.textContent = bits.join(" ");
  } catch (err) {
    stateEl.className = "row down";
    labelEl.textContent = "Status page error";
    metaEl.className = "meta err";
    metaEl.textContent = "Could not read the server.";
  }
}

async function copyText(value, button, label) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
  } catch (err) {
    const area = document.createElement("textarea");
    area.value = value;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = label; }, 1200);
}

copyEl.addEventListener("click", () => copyText(code, copyEl, "Copy invite code"));
copyPasswordEl.addEventListener("click", () => copyText(joinPassword, copyPasswordEl, "Copy password"));

refresh();
setInterval(refresh, 8000);
</script>
</body>
</html>
"""


def docker_get(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect("/var/run/docker.sock")
        sock.sendall(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    finally:
        sock.close()
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, body


def ini_value(key):
    if not INI.exists():
        return ""
    prefix = key + "="
    for line in INI.read_text(errors="replace").splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
    return ""


def container_state():
    status, body = docker_get(f"/containers/{CONTAINER}/json")
    if status != 200:
        return {"running": False, "status": "missing", "uptime_seconds": None}
    info = json.loads(body)
    state = info.get("State") or {}
    started = state.get("StartedAt") or ""
    uptime = None
    if state.get("Running") and started:
        stamp = started.replace("Z", "+00:00")
        if "." in stamp:
            left, right = stamp.split(".", 1)
            frac, zone = right[:6], right[6:]
            zone = zone[zone.find("+") if "+" in zone else zone.find("-"):] or "+00:00"
            stamp = f"{left}.{frac}{zone}"
        uptime = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds()))
    return {
        "running": bool(state.get("Running")),
        "status": state.get("Status") or "unknown",
        "uptime_seconds": uptime,
    }


def invite_code():
    if not LOG.exists():
        return None
    data = LOG.read_bytes()[-262144:].decode("utf-8", "replace")
    found = CODE_RE.findall(data)
    return found[-1] if found else None


def snapshot():
    try:
        state = container_state()
    except Exception:
        state = {"running": False, "status": "unknown", "uptime_seconds": None}
    return {
        "name": ini_value("ServerName") or "Dragonwilds",
        "running": state["running"],
        "status": state["status"],
        "uptime_seconds": state["uptime_seconds"],
        "invite_code": invite_code(),
        "join_password": ini_value("WorldPassword"),
        "direct": DIRECT_HOST,
        "port": GAME_PORT,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/status":
            body = json.dumps(snapshot()).encode()
            ctype = "application/json"
        elif self.path.split("?", 1)[0] == "/":
            body = PAGE.encode()
            ctype = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
