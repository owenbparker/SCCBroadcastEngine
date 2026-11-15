# SCC Broadcast Engine

One app for the whole SCC broadcast: the **GFX Engine**, the six **game HUDs**
(League of Legends, VALORANT, Call of Duty, Rocket League, Smash Ultimate,
Overwatch), **HUD Builder** and **Multistream**, in one window with one
installer and one updater.

Everything works the way it did in the separate apps: each part runs on its
usual port, so OBS browser sources, Bitfocus Companion buttons, player cam
links and the HUD-to-engine pairing don't change.

## Install

Download **SCC-Broadcast-Engine-Setup.exe** from the
[latest release](https://github.com/owenbparker/SCCBroadcastEngine/releases/latest)
and run it. It installs to `C:\SCC Broadcast Engine` (or a folder you choose)
and adds a desktop shortcut. The app checks for updates when it starts, and
one update covers every part.

Close the old separate apps (GFX Engine, the HUDs, HUD Builder, Multistream)
before starting it: they use the same ports. Player Cam stays its own small
app for players' PCs.

## First start: what does this PC do?

| Role | Runs |
| --- | --- |
| **Control PC** | The GFX Engine (Control, Composer, Event, Cameras, the OBS outputs), HUD Builder, and the games you pick |
| **HUD PC** | The games you pick. Control, Composer and Event open from the Control PC (enter its address) |
| **Stream PC** | Multistream |

Each part can be switched on or off afterwards in **Settings** (the gear at
the top right), and the role changed.

## The top bar

- **Home**: tonight's match, what's on air, the games and what's running.
- **Control**, **Cameras**: the GFX Engine's Control page and Camera Control Room.
- **Stream**: Multistream.
- **Games**: each game HUD's own pages (League and VALORANT open on the
  GFX Controller / Observer Client choice, as before).
- **Build**: Composer, HUD Builder, Assets, Transitions.
- **Event**: Global, Teams, Tournament, Schedule, Outputs & Network, Data.
- **Settings**: this PC's role, which parts run, the Control PC, the Home
  background (solid colour or the SCC BG loop), updates and folders.

## Other PCs and the pairing code

The engine has a 6-digit **pairing code** (Event > Outputs & Network). With
"Ask other PCs for the pairing code" on, anything on another PC that changes
something (a game HUD there, Bitfocus Companion, the control panel opened in a
browser there) needs it once: a HUD asks for it on its GFX Engine page,
Companion has a "Pairing code" field, a browser asks the first time.
Outputs (OBS and vMix browser sources) never need it. A web page open in a
browser on any PC can't change anything without the code either.

New installs ask for the code from the start. Installs from before it existed
keep working as they did until the box is ticked.

See [docs/STATE.md](docs/STATE.md) for which part owns which data (the one place each thing is set).

## Your files

Everything that's yours is in the `data` folder next to `SCCBroadcastEngine.exe`,
one folder per part (`data\gfxengine` has the workspaces, `data\lolhud` the
League HUD's settings and logos, and so on). Updates never touch it.

## For developers

```
pip install pywebview
python SCCBroadcastEngine.py                 # the app (data in ./data)
python SCCBroadcastEngine.py --no-window     # no window: http://127.0.0.1:8770/
python tools/run_tests.py                    # every test: the app's and each part's
```

Each part's code is in `apps/<part>/`, and **this is where it's changed**:
since 2026-11-15 SCC Broadcast Engine is the only app, and the old app
repositories (GFX Engine, the game HUDs, HUD Builder, Multistream) are frozen.
Their code was first copied in by `tools/sync_apps.py` (now retired; see that
file for the small changes it made), and `apps/SOURCES.json` records the last
commit copied from each. Player Cam stays its own app (players install it). The app
itself (top bar, Home, Settings, starting the parts, the updater) is in
`sccbe/` and `web/`.

How it's put together: every part runs in this one process (its web server in
a thread, on its usual port). The window is a pywebview window showing the
top bar from `sccbe/app.py` (port 8770), with each part's own pages in a
frame below it. The HUD-over-the-game windows and Multistream's chat window
are pywebview windows of the same app.

## Releases

Normal releases (the ones installed apps update to) are built from the `main` branch. Work branches publish test builds (GitHub pre-releases) that installed apps never pick up.
