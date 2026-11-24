## SCC Broadcast Engine

One connection for the whole of SCC Broadcast Engine: the GFX Engine's graphics, scores and series, teams, workspaces and tournaments, the run of show, every game HUD that's switched on (League, VALORANT, Call of Duty, Rocket League, Smash, Overwatch), Multistream, and the app's parts.

**Setup**

1. Add an **SCC Broadcast Engine** connection.
2. Address: the PC SCC Broadcast Engine runs on (`127.0.0.1` if it's this PC). Port: `8782`.
3. If Companion runs on another PC, turn on **Let other PCs use this engine** (Event > Outputs & Network on the engine's PC) and type its **pairing code** in the connection if it asks for one.
4. A HUD PC without the GFX Engine: run Companion on that PC and use port `8770`. Its graphics then come from the Control PC set in its Settings.

Add one connection per PC you want to control (the Control PC, a HUD PC...). Needs Companion 3.5 or later (4.x is fine).

**Presets** (made from what the app has now, and made again when that changes)

- **GFX: Preview / Program**: one button per graphic (green on Preview, red on air).
- **GFX: Take**: Take with the default transition or any one (stingers too), Clear, Update Program, what's on Preview and Program.
- **Score, series & teams**: each team's score +1 / -1, reset, **swap sides** (the game HUDs follow), best of 1 / 3 / 5 / 7, the series score.
- **Teams: left / right side**: put any team from the team list on a side.
- **Workspaces & tournaments**: open one.
- **GFX: Quick functions**: clock mode, timer, background loop, Back in bug loop, player graphics side, caster boxes.
- **Run of show**: next, back, start again, cue the segment's graphics onto Preview, auto (follow the Schedule), what's on now with the time left, what's next and when, and one button per segment (red while it's on).
- **League of Legends, VALORANT, Call of Duty, Rocket League, Smash Ultimate, Overwatch**: each HUD's settings and commands (HUD on game, demo, webcams, timeouts, technical pause, stocks, map results, replay stinger, post-game stats...). Lit while they're on.
- **Multistream**: each platform on / off, red while it's live; restart the relay.
- **App: parts**: switch a game HUD, HUD Builder or Multistream on / off, or restart it; whether Companion is connected.

**Actions**

GFX: Preview, Program, Take, Clear, Update Program, Quick function. Series: set a score, best of. Teams: put a team on a side. Event: event / stage name. Workspace, Tournament. **Run of show / game HUD / Multistream / app** (one action for every control the app lists, toggle / on / off). Run of show: go to a segment. Game HUD: set / nudge a value.

**Feedbacks**

GFX graphic on Preview / Program, GFX something is set, Run of show / game HUD / Multistream / app is on, a part is running / off / has an error, a run of show segment is on now, not connected.

**Variables**

The GFX Engine's (`left_name`, `left_short`, `left_score`, `right_…`, `series`, `best_of`, `game_number`, `event`, `stage`, `preview`, `program`, `timer`, `clock`, `workspace`, `tournament`…), the run of show's (`ros_current`, `ros_next`, `ros_left`, `ros_elapsed`, `ros_next_at`, `ros_position`, `ros_block`, `ros_match`), each game HUD's (`val_map`, `val_score_left`, `val_timeouts_left`, `rl_clock`, `smash_stocks_left`, `ow_map_no`, `lol_game_time`…), Multistream's (`stream_live`, `stream_ingest`, one per platform) and each part's status (`part_val`…).
