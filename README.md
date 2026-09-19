# rsdw-status

See whether a [RuneScape: Dragonwilds dedicated server](https://github.com/runescape/rsdw-dedicated) is up, and copy the current invite code, without opening the game.

> [!NOTE]
> Unofficial. This is not a Jagex project, and it is not part of the official image.

## Start

The game server has to be running in Docker already.

1. Set `RSDW_DATA_DIR` to the host folder that the game container mounts at `/home/steam/rsdw-dedicated`.
2. Start this page.

```bash
export RSDW_DATA_DIR=/path/to/rsdw-dedicated
docker compose up -d
```

Open [http://127.0.0.1:8791](http://127.0.0.1:8791).

## What you see

- A green or red dot, and how long the container has been up.
- The invite code, large, with a copy button. It is the latest `JoinCode` line in `RSDragonwilds.log`. A new code is written every time the game server starts. The copy button stays off until the log says the session is ready to join.
- How long ago the world last saved. The dedicated server saves about every five minutes. If it is up and the last success is older than 10 minutes, the page says the save looks stale.
- The last address that reached the server, and the last time a connection closed. The log has no player names, so this is not a player list.
- The join password from `WorldPassword` in `DedicatedServer.ini`, with a copy button. If the world has no password, the button stays off.
- The page title, from `ServerName` in that same file.

Set `RSDW_DIRECT_HOST` if you also want a direct-connect address on the page. Leave it empty and that line is omitted.

## Keep it on your network

> [!WARNING]
> Anyone who can open this page can see the invite code and the join password. It listens on localhost only. If you change `compose.yaml` so other computers on your LAN can open it, do not forward that port on your router.

The container mounts the Docker socket, so it can control Docker, not only read one container. Run it on a machine you trust.

`DedicatedServer.ini` also contains the admin password. This page does not show it.

## Settings

| Variable | Default | What it does |
| --- | --- | --- |
| `RSDW_DATA_DIR` | | Host path of the game data. Compose only. Required. |
| `RSDW_CONTAINER` | `rsdw-dedicated` | Container to inspect |
| `RSDW_STATUS_PORT` | `8791` | Port the page binds inside the container. Keep it the same as the published port. |
| `RSDW_DIRECT_HOST` | empty | Direct-connect address. Hidden when empty. |
| `RSDW_GAME_PORT` | `7777` | Game port shown next to that address |

Compose mounts the game log at `/logs/RSDragonwilds.log` and the ini at `/config/DedicatedServer.ini`.

## Just the invite code

```bash
docker logs rsdw-dedicated 2>&1 | awk '/JoinCode/{line=$0} END{print line}'
```
