# rsdw-status

A small page for an [rsdw-dedicated](https://github.com/runescape/rsdw-dedicated) server. It shows whether the container is running, the current invite code, and the join password.

This is not a Jagex project. It is not part of the official image.

## What it shows

- Up or down, and how long the container has been up.
- The invite code from the latest `JoinCode` line in `RSDragonwilds.log`. That code changes every time the game server starts. The log line is not a stable API.
- The join password from `WorldPassword` in `DedicatedServer.ini`.
- The server name from `ServerName` in that same file.

It does not show the admin password. The ini file still contains it, and this container can read that file.

## Run

The game server has to be running under Docker already. Point `RSDW_DATA_DIR` at the host directory mounted as `/home/steam/rsdw-dedicated` in that container.

```bash
export RSDW_DATA_DIR=/path/to/rsdw-dedicated
docker compose up -d
```

Open http://127.0.0.1:8791

By default the page listens only on localhost. To open it from another computer on your network, change the publish line in `compose.yaml` to that machine's LAN address. Do not forward the port on your router. Anyone who can open the page can see the invite code and the join password.

`/var/run/docker.sock` lets this container control Docker, not only read one container. Keep the page on a machine you trust.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `RSDW_CONTAINER` | `rsdw-dedicated` | Container name to inspect |
| `RSDW_STATUS_PORT` | `8791` | Port inside the status container. Match the published port. |
| `RSDW_DIRECT_HOST` | empty | Shown as a direct-connect address. Omitted when empty. |
| `RSDW_GAME_PORT` | `7777` | Game port shown next to that address |
| `RSDW_DATA_DIR` | | Host path of the game server data, used by Compose only |

The log is read from `/logs/RSDragonwilds.log` and the ini from `/config/DedicatedServer.ini`. Those are the mount points in `compose.yaml`.

## Without this page

The invite code is also in the game container's output:

```bash
docker logs rsdw-dedicated 2>&1 | awk '/JoinCode/{line=$0} END{print line}'
```
