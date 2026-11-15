# Who owns what

Every piece of data in SCC Broadcast Engine has **one owner**: the one place
it's set. Everything else reads it, or asks the owner to change it. When two
places could both set something, it flips back and forth on air (the
"Bearrett + 2019 Kawhi" teams of 2026-11-04 came from exactly that), so a
change that adds a second writer needs a line here first.

| Data | Owner (where it's set) | Who reads it | How others change it |
|---|---|---|---|
| The two teams: name, short name, logo, colour | **GFX Engine, Global** (`globalcfg.py`) | Every graphic (`{{Global!...}}`), every connected HUD (follows it: `enginelink._check_follow`) | Only in Global (or Teams > fill a side). HUDs never send team info (`_scores_only`). |
| Which team is on the left | **GFX Engine, Global** | HUDs (follow; a Global swap swaps the HUD too) | A HUD's Swap sides button asks the engine (`swap_global`), then follows. |
| Series score, best of | **GFX Engine, Global** | Graphics, HUDs | A HUD sends a score only when it changes while connected (a map won there); what's set in Global stands otherwise (`Engine.ingest`). |
| Live game stats (K/D/A, gold, agents...) | **The game's HUD** (its reader) | The engine, as the data table named after the HUD (`{{VALORANT HUD!...}}`), read only | Nobody else. A HUD's fields are replaced whole on each send. |
| VALORANT: which team (Red / Blue) a side of the screen is | **VAL reader** (`tracker.SideKeeper`, from the agents) | The HUD | Nobody: worked out again each map. |
| VALORANT: who a player is | **Riot Client roster** (Riot ID, team, agent: `riotclient.roster`) | The tracker, cam links, Player graphics | The screen's names fill in only when the Riot Client isn't there. |
| Team rosters, players' in-game IDs, headshots, countries | **GFX Engine, Teams** (`library/teams.csv`, shared by every workspace) | Player graphics, HUDs' "Save IGN to player" | A HUD's Save IGN to player asks the engine (`/api/roster/link`). |
| Player cam links (VDO.Ninja) | **The game's HUD** (`cams.links`) | Its overlay | Only there. |
| Tournament, brackets, standings, schedule, sponsors, ticker | **GFX Engine, the open workspace** | Graphics | Only there. |
| Run of show templates | **SCC Broadcast Engine** (`sccbe/ros.py`) | Its Run of show page | Other PCs send templates (`rosnet`, the person picks keep or replace). |
| Which parts run, the PC's role, the Control PC and its pairing code | **SCC Broadcast Engine settings** (`data/shell`) | The window | Only in Settings. |
| The pairing code | **GFX Engine settings** (`network_key`) | Shown on its own PC only | New code on that PC; never in `/api/state`. |
| Appearance (look, highlight colour) | **Each part's own `appearance.json`** | That part's pages | That part's Appearance setting. |

## Rules that keep it that way

- A part that doesn't own a piece of data **never writes it into its own
  settings as if it did**. It keeps what it read only as a cache, and takes
  the owner's value in again when they differ (a HUD's team names: every 15 s
  while they differ from Global's).
- An owner **ignores an old value coming back**. The engine only takes a
  HUD's score when the HUD's score *moved*, so connecting a HUD or restarting
  the engine never puts last night's score back.
- Live readings (the screen readers, the Riot Client) never write into
  anything a person set by hand. They go into the HUD's live fields, which
  are replaced on every reading.
- When two PCs run different versions of the link between HUDs and the
  engine, both say so (`PROTOCOL` in `scc_shared/enginelink.py`) instead of
  one quietly getting data it can't read.
