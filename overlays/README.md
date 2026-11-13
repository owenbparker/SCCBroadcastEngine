# Overlays

Files added to a part's copy in `apps/<part>/` after `tools/sync_apps.py`
brings it in from its own repository (same layout). The pages load them with
one `<link>` / `<script>` line that sync_apps.py adds (see PATCHES there).

They only change anything when the page is shown inside SCC Broadcast
Engine's window (in a frame under the top bar): the page then gets the class
`sccbe` on `<html>`. Opened on its own (OBS, another PC's browser) a page
looks and works exactly as before.

- `gfxengine/web/sccbe-embed.*`: no sidebar (the top bar has its pages and the
  workspaces), and a bar to drag between Preview / Program and the Graphics
  and Fields panels on Control.
- `multistream/web/sccbe-embed.*`: Multistream in the app's look.
