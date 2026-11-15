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

Each part's code is in `apps/<part>/`, copied from its own repository by
`tools/sync_apps.py` (see that file for the three small changes it makes, and
`apps/SOURCES.json` for the branch and commit each copy came from). The app
itself (top bar, Home, Settings, starting the parts, the updater) is in
`sccbe/` and `web/`.

How it's put together: every part runs in this one process (its web server in
a thread, on its usual port). The window is a pywebview window showing the
top bar from `sccbe/app.py` (port 8770), with each part's own pages in a
frame below it. The HUD-over-the-game windows and Multistream's chat window
are pywebview windows of the same app.

## Releases

Normal releases (the ones installed apps update to) are built from the `main` branch. Work branches publish test builds (GitHub pre-releases) that installed apps never pick up.
