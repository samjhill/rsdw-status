#!/usr/bin/env python3
"""LAN page for an rsdw-dedicated server: running or not, and the current invite code.

Unofficial. Not part of the Jagex image.
"""

import json
import os
import re
import socket
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONTAINER = os.environ.get("RSDW_CONTAINER", "rsdw-dedicated")
LOG = Path("/logs/RSDragonwilds.log")
INI = Path("/config/DedicatedServer.ini")
PORT = int(os.environ.get("RSDW_STATUS_PORT", "8791"))
DIRECT_HOST = os.environ.get("RSDW_DIRECT_HOST", "").strip()
GAME_PORT = int(os.environ.get("RSDW_GAME_PORT", "7777"))
STAMP = r"\[(\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}):\d{3}\]"
SAVE_RE = re.compile(STAMP + r".*Save completed SUCCESSFULLY")
READY_RE = re.compile(STAMP + r'.*ReadyToJoin"\] written with key\[[^\]]+\] value\[([01])\]')
ACCEPT_RE = re.compile(STAMP + r".*NotifyAcceptingConnection accepted from: (\S+)")
CLOSE_RE = re.compile(STAMP + r".*ControlChannelClose")
JOIN_RE = re.compile(STAMP + r'.*JoinCode"\] written with key\[[^\]]+\] value\[([A-Z0-9-]+)\]')
JOINED_RE = re.compile(r"Join succeeded:\s*(\S+)")
LOGIN_NAME_RE = re.compile(r"Name=([^\s?]+)")
LOGIN_PF_RE = re.compile(r"pf=([^?&\s]+)")
USER_ID_RE = re.compile(r"userId:\s*(\S+)")
UNIQUE_ID_RE = re.compile(r"UniqueId:\s*([^,\s]+)")
CONN_CLOSE_RE = re.compile(STAMP + r".*UNetConnection::Close:")
SAVES = Path(os.environ.get("RSDW_SAVES", "/saves"))
STALE_AFTER = 600

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
  .code.not-ready { opacity: 0.45; }
  .facts { margin: 1.4rem 0 0; padding: 0; list-style: none; color: #6d645b; line-height: 1.55; }
  .facts .warn { color: #a33b32; }
  .meta { margin-top: 1rem; color: #6d645b; line-height: 1.55; }
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
  <ul class="facts" id="facts"></ul>
  <p class="meta" id="meta"></p>
</main>
<script>
const titleEl = document.getElementById("title");
const codeEl = document.getElementById("code");
const labelEl = document.getElementById("label");
const stateEl = document.getElementById("state");
const copyEl = document.getElementById("copy");
const copyPasswordEl = document.getElementById("copy-password");
const factsEl = document.getElementById("facts");
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

function ago(seconds) {
  if (seconds == null) return "";
  if (seconds < 45) return "just now";
  return uptime(seconds) + " ago";
}

function addFact(text, warn) {
  const item = document.createElement("li");
  item.textContent = text;
  if (warn) item.className = "warn";
  factsEl.appendChild(item);
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
    codeEl.classList.toggle("not-ready", up && data.ready_to_join === false);
    copyEl.disabled = !code || (up && data.ready_to_join === false);
    copyPasswordEl.disabled = !joinPassword;
    copyPasswordEl.textContent = joinPassword ? "Copy password" : "No password";
    factsEl.replaceChildren();
    if (up && data.ready_to_join === false) addFact("Not ready to join yet.", true);
    if (data.update_pending) addFact("A Steam update will restart the server.", true);
    if (data.save_age_seconds == null) {
      addFact("No successful save in the recent log.", !!(up && data.save_stale));
    } else {
      const size = data.save_bytes != null ? ", file " + data.save_bytes + " bytes" : "";
      addFact("Saved " + ago(data.save_age_seconds) + size + ".", false);
    }
    if (data.save_stale && data.save_age_seconds != null) addFact("The last save is more than 10 minutes old.", true);
    if (data.save_size_stale) addFact("Save file size has not changed for more than 10 minutes.", true);
    if (data.usage) addFact("Memory " + data.usage.memory + ", CPU " + data.usage.cpu + ".", false);
    const prior = data.connection_before_this_start ? "before this start, " : "";
    const players = data.players || [];
    if (players.length) {
      const names = players.map(player => player.platform ? player.name + " (" + player.platform + ")" : player.name);
      let who = names[0];
      if (names.length === 2) who = names[0] + " and " + names[1];
      else if (names.length > 2) who = names.slice(0, -1).join(", ") + ", and " + names[names.length - 1];
      addFact(who + (names.length === 1 ? " is in." : " are in."), false);
    } else if (!data.connection_before_this_start && data.last_close_age_seconds == null) {
      addFact("No connection has reached this server.", false);
    } else {
      addFact("Nobody is in.", false);
    }
    if (data.unnamed_leave) addFact("Someone left, and the log did not say who.", false);
    if (data.last_close_age_seconds != null) addFact("Last close " + prior + ago(data.last_close_age_seconds) + ".", false);
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


def docker_get(path, timeout=3):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
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


def log_stamp(value):
    return datetime.strptime(value, "%Y.%m.%d-%H.%M.%S").replace(tzinfo=timezone.utc)


def age_seconds(stamp, now):
    return max(0, int((now - log_stamp(stamp)).total_seconds()))


def read_file(path):
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size <= 4_000_000:
            data = handle.read()
        else:
            head = handle.read(1_000_000)
            handle.seek(size - 2_000_000)
            data = head + b"\n" + handle.read()
    return data.decode("utf-8", "replace")


def read_log():
    if not LOG.exists():
        return ""
    return read_file(LOG)


def mark_left(players, user_id):
    for player in reversed(players):
        if not player["left"] and player["user_id"] == user_id:
            player["left"] = True
            return True
    return False


def players_from_lines(lines):
    players = []
    platforms = {}
    ids = {}
    unnamed_leave = False
    last_close = None
    named_close_at = set()
    for line in lines:
        if "Login request:" in line:
            name = LOGIN_NAME_RE.search(line)
            platform = LOGIN_PF_RE.search(line)
            user_id = USER_ID_RE.search(line)
            if name and platform:
                platforms[name.group(1)] = platform.group(1)
            if name and user_id:
                ids[name.group(1)] = user_id.group(1)
            continue
        joined = JOINED_RE.search(line)
        if joined:
            name = joined.group(1)
            players.append({
                "name": name,
                "platform": platforms.get(name) or "",
                "user_id": ids.get(name) or "",
                "left": False,
            })
            continue
        named = CONN_CLOSE_RE.search(line)
        if named and "UniqueId:" in line:
            last_close = named.group(1)
            named_close_at.add(last_close)
            user_id = UNIQUE_ID_RE.search(line)
            if not (user_id and mark_left(players, user_id.group(1))):
                unnamed_leave = True
            continue
        closed = CLOSE_RE.search(line)
        if not closed:
            continue
        last_close = closed.group(1)
        if last_close in named_close_at:
            continue
        still_in = [player for player in players if not player["left"]]
        if len(still_in) == 1:
            still_in[0]["left"] = True
        elif len(still_in) > 1:
            unnamed_leave = True
    present = [{"name": player["name"], "platform": player["platform"]} for player in players if not player["left"]]
    return present, unnamed_leave, last_close


def players_in_log(path):
    if not path.exists():
        return [], False, None
    with path.open("r", errors="replace") as handle:
        return players_from_lines(handle)


def newest_backup():
    folder = LOG.parent
    if not folder.exists():
        return None
    backups = sorted(folder.glob("RSDragonwilds-backup-*.log"))
    return backups[-1] if backups else None


def last_match(pattern, text):
    found = list(pattern.finditer(text))
    return found[-1] if found else None


def log_facts(text, running, uptime_seconds, now=None):
    now = now or datetime.now(timezone.utc)
    save = last_match(SAVE_RE, text)
    ready = last_match(READY_RE, text)
    accept = last_match(ACCEPT_RE, text)
    close = last_match(CLOSE_RE, text)
    code = last_match(JOIN_RE, text)
    save_age = age_seconds(save.group(1), now) if save else None
    ready_to_join = None if ready is None else ready.group(2) == "1"
    save_stale = bool(
        running
        and (
            (save_age is not None and save_age > STALE_AFTER)
            or (save_age is None and uptime_seconds is not None and uptime_seconds > STALE_AFTER)
        )
    )
    return {
        "invite_code": code.group(2) if code else None,
        "ready_to_join": ready_to_join,
        "save_age_seconds": save_age,
        "save_stale": save_stale,
        "last_accept": None
        if accept is None
        else {"age_seconds": age_seconds(accept.group(1), now), "address": accept.group(2)},
        "last_close_age_seconds": None if close is None else age_seconds(close.group(1), now),
    }


def connection_facts(current_text, now):
    accept = last_match(ACCEPT_RE, current_text)
    close = last_match(CLOSE_RE, current_text)
    before = False
    if accept is None and close is None:
        backup = newest_backup()
        if backup is not None:
            previous = read_file(backup)
            accept = last_match(ACCEPT_RE, previous)
            close = last_match(CLOSE_RE, previous)
            before = accept is not None or close is not None
    return {
        "connection_before_this_start": before,
        "last_accept": None
        if accept is None
        else {"age_seconds": age_seconds(accept.group(1), now), "address": accept.group(2)},
        "last_close_age_seconds": None if close is None else age_seconds(close.group(1), now),
    }


def demux_logs(body):
    if len(body) < 8 or body[1:4] != b"\x00\x00\x00":
        return body.decode("utf-8", "replace")
    parts = []
    index = 0
    while index + 8 <= len(body):
        if body[index + 1:index + 4] != b"\x00\x00\x00":
            parts.append(body[index:])
            break
        size = int.from_bytes(body[index + 4:index + 8], "big")
        start = index + 8
        end = start + size
        if end > len(body):
            parts.append(body[start:])
            break
        parts.append(body[start:end])
        index = end
    return b"".join(parts).decode("utf-8", "replace")


_update_cache = {"at": 0.0, "value": False}


def steam_update_pending():
    now = time.time()
    if now - _update_cache["at"] < 60:
        return _update_cache["value"]
    pending = False
    try:
        since = int(now) - 45 * 60
        status, body = docker_get(
            f"/containers/{CONTAINER}/logs?stdout=1&stderr=1&since={since}"
        )
        if status == 200:
            for line in demux_logs(body).splitlines():
                if "New Steam version is available" in line and "stopping server" in line:
                    pending = True
                    break
    except Exception:
        pending = False
    _update_cache["at"] = now
    _update_cache["value"] = pending
    return pending


def current_save():
    if not SAVES.is_dir():
        return None
    files = [path for path in SAVES.iterdir() if path.is_file() and path.suffix == ".sav"]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


_save_seen = {"size": None, "changed": None}


def save_file_facts(running, now):
    path = current_save()
    if path is None:
        return None, False
    stat = path.stat()
    size = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    if _save_seen["size"] != size:
        _save_seen["changed"] = mtime if _save_seen["changed"] is None else now
        _save_seen["size"] = size
    changed = _save_seen["changed"] or mtime
    stale = bool(running and (now - changed).total_seconds() > STALE_AFTER)
    return size, stale


def format_mem(amount):
    gib = 1024 ** 3
    if amount >= gib:
        text = f"{amount / gib:.2f}".rstrip("0").rstrip(".")
        return f"{text} GiB"
    return f"{round(amount / (1024 ** 2))} MiB"


def memory_used(memory_stats):
    usage = int(memory_stats.get("usage") or 0)
    inner = memory_stats.get("stats") or {}
    cache = inner.get("inactive_file")
    if cache is None:
        cache = inner.get("total_inactive_file") or 0
    return max(0, usage - int(cache))


def cpu_percent(stats):
    cpu = stats.get("cpu_stats") or {}
    previous = stats.get("precpu_stats") or {}
    used = int((cpu.get("cpu_usage") or {}).get("total_usage") or 0)
    used -= int((previous.get("cpu_usage") or {}).get("total_usage") or 0)
    system = int(cpu.get("system_cpu_usage") or 0) - int(previous.get("system_cpu_usage") or 0)
    if used <= 0 or system <= 0:
        return None
    cores = cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    return round(used / system * int(cores) * 100)


_usage_cache = {"at": 0.0, "value": None}


def container_usage():
    now = time.time()
    if now - _usage_cache["at"] < 30:
        return _usage_cache["value"]
    try:
        status, body = docker_get(f"/containers/{CONTAINER}/stats?stream=0", timeout=8)
        if status == 200:
            stats = json.loads(body)
            memory = stats.get("memory_stats") or {}
            used = memory_used(memory)
            limit = int(memory.get("limit") or 0)
            cpu = cpu_percent(stats)
            if used and limit and cpu is not None:
                _usage_cache["value"] = {"memory": f"{format_mem(used)} of {format_mem(limit)}", "cpu": f"{cpu}%"}
    except Exception:
        pass
    _usage_cache["at"] = now
    return _usage_cache["value"]


def snapshot():
    try:
        state = container_state()
    except Exception:
        state = {"running": False, "status": "unknown", "uptime_seconds": None}
    now = datetime.now(timezone.utc)
    text = read_log()
    facts = log_facts(text, state["running"], state["uptime_seconds"], now)
    facts.update(connection_facts(text, now))
    present, unnamed_leave, last_close = players_in_log(LOG)
    facts["players"] = present
    facts["unnamed_leave"] = unnamed_leave
    if last_close:
        facts["last_close_age_seconds"] = age_seconds(last_close, now)
    save_bytes, save_size_stale = save_file_facts(state["running"], now)
    try:
        usage = container_usage() if state["running"] else None
    except Exception:
        usage = None
    try:
        update_pending = steam_update_pending()
    except Exception:
        update_pending = False
    return {
        "name": ini_value("ServerName") or "Dragonwilds",
        "running": state["running"],
        "status": state["status"],
        "uptime_seconds": state["uptime_seconds"],
        "invite_code": facts["invite_code"],
        "ready_to_join": facts["ready_to_join"],
        "save_age_seconds": facts["save_age_seconds"],
        "save_stale": facts["save_stale"],
        "save_bytes": save_bytes,
        "save_size_stale": save_size_stale,
        "usage": usage,
        "last_accept": facts["last_accept"],
        "players": facts["players"],
        "unnamed_leave": facts["unnamed_leave"],
        "last_close_age_seconds": facts["last_close_age_seconds"],
        "connection_before_this_start": facts["connection_before_this_start"],
        "update_pending": update_pending,
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
