#!/usr/bin/env python3
"""Record a Dragonwilds dedicated-server session. Does not change the server.

Writes next to this file. Skips profanity-filter spam. Requires:
  RSDW_SSH_HOST   SSH host that can read the game files and run docker
  RSDW_LOG        game log path on that host
  RSDW_SAV_DIR    SaveGames directory on that host
Optional:
  RSDW_CONTAINER  default rsdw-dedicated
  RSDW_STATUS_URL status page, if you want those snapshots too
  RSDW_GAME_PORT  default 7777
"""

import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OFFSET = ROOT / ".log-offset"
DOCKER_SINCE = ROOT / ".docker-since"
EVENTS = ROOT / "events.log"
GAMELOG = ROOT / "gamelog.log"
DOCKERLOG = ROOT / "docker.log"
STATUS = ROOT / "status.jsonl"
RESOURCES = ROOT / "resources.log"

SSH_HOST = os.environ.get("RSDW_SSH_HOST", "").strip()
LOG = os.environ.get("RSDW_LOG", "").strip()
SAV_DIR = os.environ.get("RSDW_SAV_DIR", "").strip()
CONTAINER = os.environ.get("RSDW_CONTAINER", "rsdw-dedicated").strip()
STATUS_URL = os.environ.get("RSDW_STATUS_URL", "").strip()
GAME_PORT = int(os.environ.get("RSDW_GAME_PORT", "7777"))
BEACON_PORT = GAME_PORT + 1111

KEYS = (
    "NotifyAcceptingConnection accepted from",
    "ControlChannelClose",
    "Save completed SUCCESSFULLY",
    "ReadyToJoin",
    "JoinCode",
    "Join succeeded",
    "Login request",
    "Join request",
    "Error",
    "Fatal",
    "Exception",
    "Warning",
)


def stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def skipped(line):
    return "profanity" in line.lower()


def highlight(line):
    return any(key in line for key in KEYS)


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
        if os.path.isfile(path):
            saves.append(name + "=" + str(os.path.getsize(path)))
stats = subprocess.check_output(
    ["docker", "stats", "--no-stream", "--format",
     "mem={{{{.MemUsage}}}} cpu={{{{.CPUPerc}}}} net={{{{.NetIO}}}} block={{{{.BlockIO}}}} pids={{{{.PIDs}}}}",
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


def poll():
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
        highlighted = [line for line in game_lines if highlight(line)]
        if highlighted:
            with EVENTS.open("a") as handle:
                for line in highlighted:
                    handle.write(f"{when} {line}\n")
                    print(line, flush=True)
    docker_lines = [line for line in docker_text.splitlines() if line.strip() and not skipped(line)]
    if docker_lines:
        with DOCKERLOG.open("a") as handle:
            for line in docker_lines:
                handle.write(f"{when} {line}\n")
    with RESOURCES.open("a") as handle:
        handle.write(f"{when} {stats_line} {saves}\n")
        if ports:
            handle.write(f"{when} ports {ports}\n")
    try:
        snap = status_snapshot()
    except Exception as exc:
        snap = {"error": str(exc)}
    if snap is not None:
        snap["captured_at"] = when
        with STATUS.open("a") as handle:
            handle.write(json.dumps(snap, separators=(",", ":")) + "\n")
    OFFSET.write_text(str(new_size) + "\n")
    DOCKER_SINCE.write_text(when + "\n")
    print(f"polled {when} game={len(game_lines)} docker={len(docker_lines)}", flush=True)


def main():
    missing = [name for name, value in (("RSDW_SSH_HOST", SSH_HOST), ("RSDW_LOG", LOG), ("RSDW_SAV_DIR", SAV_DIR)) if not value]
    if missing:
        raise SystemExit("Set " + ", ".join(missing))
    if not OFFSET.exists():
        OFFSET.write_text(str(current_log_size()) + "\n")
    if not DOCKER_SINCE.exists():
        DOCKER_SINCE.write_text(stamp() + "\n")
    while True:
        try:
            poll()
        except Exception as exc:
            with EVENTS.open("a") as handle:
                handle.write(f"{stamp()} recorder error: {exc}\n")
            print(f"recorder error: {exc}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
