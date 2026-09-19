#!/usr/bin/env python3
"""Record a Dragonwilds dedicated-server session. Does not change the server.

Read summary.md. events.log has one line per join, leave, save, invite-code
change, and the first time each error appears. gamelog.log is the raw archive
without profanity-filter lines.

Requires:
  RSDW_SSH_HOST   SSH host that can read the game files and run docker
  RSDW_LOG        game log path on that host
  RSDW_SAV_DIR    SaveGames directory on that host
Optional:
  RSDW_CONTAINER   default rsdw-dedicated
  RSDW_STATUS_URL  status page, if you want those snapshots too
  RSDW_GAME_PORT   default 7777
  RSDW_RECORD_DIR  output folder, default is this script's directory
"""

import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("RSDW_RECORD_DIR", "")).expanduser() if os.environ.get("RSDW_RECORD_DIR") else Path(__file__).resolve().parent
OFFSET = ROOT / ".log-offset"
DOCKER_SINCE = ROOT / ".docker-since"
EVENTS = ROOT / "events.log"
GAMELOG = ROOT / "gamelog.log"
DOCKERLOG = ROOT / "docker.log"
STATUS = ROOT / "status.jsonl"
RESOURCES = ROOT / "resources.log"
SUMMARY = ROOT / "summary.md"
STATE = ROOT / "state.json"

SSH_HOST = os.environ.get("RSDW_SSH_HOST", "").strip()
LOG = os.environ.get("RSDW_LOG", "").strip()
SAV_DIR = os.environ.get("RSDW_SAV_DIR", "").strip()
CONTAINER = os.environ.get("RSDW_CONTAINER", "rsdw-dedicated").strip()
STATUS_URL = os.environ.get("RSDW_STATUS_URL", "").strip()
GAME_PORT = int(os.environ.get("RSDW_GAME_PORT", "7777"))
BEACON_PORT = GAME_PORT + 1111
STALE_AFTER = 600

GAME_TIME = re.compile(r"\[(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2})")
JOINED = re.compile(r"Join succeeded:\s*(\S+)")
LOGIN_NAME = re.compile(r"Name=([^\s?]+)")
LOGIN_PF = re.compile(r"pf=([^?&\s]+)")
INVITE = re.compile(r'JoinCode"\] written with key\[[^\]]+\] value\[([A-Z0-9-]+)\]')
READY = re.compile(r'ReadyToJoin"\] written with key\[[^\]]+\] value\[([01])\]')
ERROR_BODY = re.compile(r"(?:Error|Fatal|Exception):\s*(.*)")
SAV_SIZE = re.compile(r"(\S+\.sav)=(\d+)")
NOISE = ("LogNetPackageMap", "IsLocalPlayer", "Failed to find string table entry", "Multicast_StopCurrentAIAction")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def show_time(raw):
    if not raw:
        return ""
    return raw.replace("T", " ").replace("Z", "")[:19]


def game_time(line):
    match = GAME_TIME.search(line)
    if not match:
        return ""
    year, month, day, hour, minute, second = match.groups()
    return f"{year}-{month}-{day} {hour}:{minute}:{second}"


def skipped(line):
    return "profanity" in line.lower()


def engine_noise(line):
    return any(part in line for part in NOISE)


def fresh_state():
    return {
        "players": [],
        "platforms": {},
        "events": [],
        "errors": [],
        "seen": [],
        "invite_code": "",
        "ready": None,
        "last_save_at": "",
        "sav_bytes": None,
        "sav_changed_at": "",
        "server_up": False,
        "listen_game": None,
        "listen_beacon": None,
    }


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    state = fresh_state()
    if GAMELOG.exists():
        for line in GAMELOG.read_text(errors="replace").splitlines():
            ingest(state, line)
    if EVENTS.exists():
        for line in EVENTS.read_text(errors="replace").splitlines():
            if any(key in line for key in ("Login request", "Join succeeded", "ControlChannelClose", "Save completed SUCCESSFULLY", "JoinCode", "ReadyToJoin")):
                ingest(state, line)
    seed_save_size(state)
    return state


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2) + "\n")


def remember(state, key):
    if key in state["seen"]:
        return False
    state["seen"].append(key)
    return True


def add_event(state, when, text):
    state["events"].append({"at": show_time(when), "text": text})


def ingest(state, line):
    if skipped(line) or engine_noise(line):
        return
    when = game_time(line) or show_time(line[:20])
    if "Login request:" in line:
        name = LOGIN_NAME.search(line)
        platform = LOGIN_PF.search(line)
        if name and platform:
            state["platforms"][name.group(1)] = platform.group(1)
        return
    joined = JOINED.search(line)
    if joined:
        name = joined.group(1)
        if not remember(state, f"join|{when}|{name}"):
            return
        platform = state["platforms"].get(name, "unknown")
        state["players"].append({"name": name, "platform": platform, "joined": when, "left": ""})
        add_event(state, when, f"{name} joined, {platform}")
        return
    if "ControlChannelClose" in line:
        if not remember(state, f"close|{when}|{line[-40:]}"):
            return
        still_in = [player for player in state["players"] if not player["left"]]
        if len(still_in) == 1:
            still_in[0]["left"] = when
            add_event(state, when, f"{still_in[0]['name']} left")
        else:
            add_event(state, when, "connection closed, player not named")
        return
    if "Save completed SUCCESSFULLY" in line:
        if not remember(state, f"save|{when}"):
            return
        state["last_save_at"] = when
        add_event(state, when, "Save completed")
        return
    invite = INVITE.search(line)
    if invite:
        code = invite.group(1)
        if code != state["invite_code"] and remember(state, f"invite|{code}"):
            state["invite_code"] = code
            add_event(state, when, f"Invite code {code}")
        return
    ready = READY.search(line)
    if ready:
        state["ready"] = ready.group(1) == "1"
        return
    if any(part in line for part in ("Error:", "Fatal:", "Exception:")):
        body = ERROR_BODY.search(line)
        text = body.group(1) if body else line
        text = re.sub(r"\d+", "N", text)
        text = re.sub(r"\s+", " ", text).strip()[:200]
        for error in state["errors"]:
            if error["text"] == text:
                error["count"] += 1
                return
        state["errors"].append({"at": when, "text": text, "count": 1})


def seed_save_size(state):
    if not RESOURCES.exists():
        return
    last_size = None
    for line in RESOURCES.read_text(errors="replace").splitlines():
        found = SAV_SIZE.search(line)
        if not found:
            continue
        when = show_time(line[:20])
        size = int(found.group(2))
        if last_size is None or size != last_size:
            state["sav_changed_at"] = when.replace(" ", "T") + "Z"
            last_size = size
    if last_size is not None:
        state["sav_bytes"] = last_size


def note_saves(state, saves, when, server_up):
    found = SAV_SIZE.search(saves or "")
    if not found:
        state["server_up"] = server_up
        return
    size = int(found.group(2))
    if state.get("sav_bytes") != size:
        state["sav_bytes"] = size
        state["sav_changed_at"] = when
    state["server_up"] = server_up


def listening(ports, port):
    return re.search(rf":{port}(?![0-9])", ports or "") is not None


def note_ports(state, ports):
    if not (ports or "").strip():
        state["listen_game"] = None
        state["listen_beacon"] = None
        return
    state["listen_game"] = listening(ports, GAME_PORT)
    state["listen_beacon"] = listening(ports, BEACON_PORT)


def note_status(state, snap):
    if not isinstance(snap, dict) or snap.get("error"):
        return
    code = snap.get("invite_code") or ""
    if code and code != state["invite_code"] and remember(state, f"invite|{code}"):
        state["invite_code"] = code
        add_event(state, snap.get("captured_at") or stamp(), f"Invite code {code}")
    if "ready_to_join" in snap and snap["ready_to_join"] is not None:
        state["ready"] = bool(snap["ready_to_join"])


def age_seconds(when):
    if not when:
        return None
    text = when.replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T")
    if "+" not in text:
        text += "+00:00"
    then = datetime.fromisoformat(text)
    return (datetime.now(timezone.utc) - then).total_seconds()


def write_summary(state):
    lines = ["# Session", "", f"Updated {stamp()}", "", "## Players"]
    present = sorted((player for player in state["players"] if not player["left"]), key=lambda player: player["joined"])
    if present:
        for player in present:
            lines.append(f"- {player['joined']} {player['name']}, {player['platform']}")
    else:
        lines.append("- Nobody is in.")
    unnamed = [event for event in state["events"] if event["text"] == "connection closed, player not named"]
    if unnamed and present:
        lines.append(f"- {unnamed[-1]['at']} a connection closed and the log did not name the player.")
    lines.extend(["", "## Save"])
    if state["last_save_at"]:
        size = f"{state['sav_bytes']} bytes" if state.get("sav_bytes") is not None else "size not read yet"
        lines.append(f"Last save {state['last_save_at']}, file {size}.")
    else:
        lines.append("No successful save in this recording.")
    age = age_seconds(state.get("sav_changed_at"))
    if state.get("server_up") and age is not None and age > STALE_AFTER:
        lines.append(f"Save file size has not changed for {int(age // 60)} minutes while the server is up.")
    lines.extend(["", "## Invite"])
    if state["invite_code"]:
        ready = "Ready to join." if state["ready"] else "Not ready to join." if state["ready"] is False else "Ready flag not in the log yet."
        lines.append(f"Invite code {state['invite_code']}. {ready}")
    else:
        lines.append("Invite code not in the log yet.")
    lines.extend(["", "## Ports"])
    def port_line(port, up):
        if up is None:
            return f"UDP {port} not checked yet."
        return f"UDP {port} listening." if up else f"UDP {port} is not listening."
    lines.append(port_line(GAME_PORT, state.get("listen_game")))
    lines.append(port_line(BEACON_PORT, state.get("listen_beacon")))
    lines.append("")
    SUMMARY.write_text("\n".join(lines))


def write_events(state):
    rows = [(event["at"], f"{event['at']} {event['text']}") for event in state["events"]]
    for error in state["errors"]:
        count = f" x{error['count']}" if error["count"] > 1 else ""
        rows.append((error["at"], f"{error['at']} Error{count}: {error['text']}"))
    text = "\n".join(line for _, line in sorted(rows))
    EVENTS.write_text((text + "\n") if text else "")


def write_views(state):
    write_summary(state)
    write_events(state)
    save_state(state)


def remote(offset, docker_since):
    script = f"""
import os, subprocess
log = {LOG!r}
sav_dir = {SAV_DIR!r}
container = {CONTAINER!r}
offset = {int(offset)}
since = {docker_since!r}
game_port = {GAME_PORT}
beacon_port = {BEACON_PORT}
size = os.path.getsize(log) if os.path.exists(log) else 0
chunk = b""
if size > offset:
    with open(log, "rb") as handle:
        handle.seek(offset)
        chunk = handle.read()
saves = []
if os.path.isdir(sav_dir):
    for name in sorted(os.listdir(sav_dir)):
        path = os.path.join(sav_dir, name)
        if os.path.isfile(path) and name.endswith(".sav"):
            saves.append(name + "=" + str(os.path.getsize(path)))
stats = subprocess.check_output(
    ["docker", "stats", "--no-stream", "--format",
     "mem={{{{.MemUsage}}}} cpu={{{{.CPUPerc}}}} pids={{{{.PIDs}}}}",
     container],
    text=True,
).strip()
ports = subprocess.run(["ss", "-u", "-n", "-a"], text=True, capture_output=True)
needles = (f":{{game_port}}", f":{{beacon_port}}")
port_lines = [line for line in (ports.stdout or "").splitlines() if any(n in line for n in needles)]
docker_out = subprocess.run(
    ["docker", "logs", "--since", since, container],
    text=True,
    capture_output=True,
)
extra = (docker_out.stdout or "") + (docker_out.stderr or "")
print(size)
print(stats)
print("SAVES " + " ".join(saves))
print("PORTS " + " | ".join(port_lines))
print("---DOCKER---")
print(extra, end="")
print("---LOG---")
print(chunk.decode("utf-8", "replace"), end="")
"""
    return subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", SSH_HOST, "python3", "-"],
        input=script,
        text=True,
    )


def status_snapshot():
    if not STATUS_URL:
        return None
    with urllib.request.urlopen(STATUS_URL, timeout=8) as response:
        return json.load(response)


def current_log_size():
    script = f"import os\nprint(os.path.getsize({LOG!r}) if os.path.exists({LOG!r}) else 0)\n"
    raw = subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", SSH_HOST, "python3", "-"],
        input=script,
        text=True,
    )
    return int(raw.strip())


def poll(state):
    offset = int(OFFSET.read_text().strip())
    docker_since = DOCKER_SINCE.read_text().strip() if DOCKER_SINCE.exists() else stamp()
    raw = remote(offset, docker_since)
    head, _, rest = raw.partition("\n---DOCKER---\n")
    docker_text, _, body = rest.partition("\n---LOG---\n")
    lines = head.splitlines()
    new_size = int(lines[0])
    stats_line = lines[1] if len(lines) > 1 else ""
    saves = next((line[6:] for line in lines if line.startswith("SAVES ")), "")
    ports = next((line[6:] for line in lines if line.startswith("PORTS ")), "")
    when = stamp()
    game_lines = [line for line in body.splitlines() if line.strip() and not skipped(line)]
    if game_lines:
        with GAMELOG.open("a") as handle:
            for line in game_lines:
                handle.write(f"{when} {line}\n")
                ingest(state, line)
    docker_lines = [line for line in docker_text.splitlines() if line.strip() and not skipped(line)]
    if docker_lines:
        with DOCKERLOG.open("a") as handle:
            for line in docker_lines:
                handle.write(f"{when} {line}\n")
    server_up = stats_line.startswith("mem=")
    note_saves(state, saves, when, server_up)
    note_ports(state, ports)
    with RESOURCES.open("a") as handle:
        handle.write(f"{when} {stats_line} {saves}\n")
    try:
        snap = status_snapshot()
    except Exception as exc:
        snap = {"error": str(exc)}
    if snap is not None:
        snap["captured_at"] = when
        with STATUS.open("a") as handle:
            handle.write(json.dumps(snap, separators=(",", ":")) + "\n")
        note_status(state, snap)
    if new_size < offset:
        raise RuntimeError(f"log shrank from {offset} to {new_size}; offset left unchanged")
    OFFSET.write_text(str(new_size) + "\n")
    DOCKER_SINCE.write_text(when + "\n")
    write_views(state)
    print(f"polled {when} game={len(game_lines)} docker={len(docker_lines)}", flush=True)


def main():
    missing = [name for name, value in (("RSDW_SSH_HOST", SSH_HOST), ("RSDW_LOG", LOG), ("RSDW_SAV_DIR", SAV_DIR)) if not value]
    if missing:
        raise SystemExit("Set " + ", ".join(missing))
    ROOT.mkdir(parents=True, exist_ok=True)
    state = load_state()
    write_views(state)
    if not OFFSET.exists():
        OFFSET.write_text(str(current_log_size()) + "\n")
    if not DOCKER_SINCE.exists():
        DOCKER_SINCE.write_text(stamp() + "\n")
    while True:
        try:
            poll(state)
        except Exception as exc:
            add_event(state, stamp(), f"recorder error: {exc}")
            write_views(state)
            print(f"recorder error: {exc}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
