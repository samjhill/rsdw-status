# Live zone dig (2026-09-20)

Question: can the status page know which zone players are standing in, so tips can scroll with the party?

## Logging

Hillwilds runs with `DEBUG=3` (official max: steamcmd spew + `RSDW_LOG=on`). Leave that on. The game container was restarted once to apply it.

## Verdict

**No live zone feed.** Even with max logging, the dedicated server does not emit enter/leave or “current region” lines while idle, and prior play under default logging only showed first-time fog-of-war unlocks.

| Signal | Live zone? |
| --- | --- |
| `LogMapRegions: Revealing map region [Name]` | No — unlock once per region per controller |
| `JOURNAL_Know_Place_*` | No — bulk unlock on join |
| `TeleportTo` XYZ | No continuous stream; no region name |
| Chest / prop names with area suffixes | Place of the prop, not the player |
| `EnterRegion` / `LeaveRegion` / `CurrentRegion` | Absent (0 hits) |

Regions seen via reveals on this world: Temple Woods, Bramblemead Valley, Whispering Swamp, Fractured Plains, Stormtouched Highlands.

Under `DEBUG=3` boot with an empty party, verbosity rose for `LogDominionGameplayDebugger` (VeryVerbose) and similar categories, but no new zone-position channel appeared. MapRegions still only fires when someone reveals fog.

## Tip strategy (follow-up)

Do **both**: soft tips keyed to the **most recent map-region reveal** when one exists; otherwise rotate **generic Ashenfall tips** while anyone is online. Do not invent current zone, night/day, or a map from coordinates.
