// The app window has no Windows title bar (sccbe/winframe.py). This draws the
// window buttons (the glass capsule right of the top bar), drags the window by
// the top bar's empty space, double-click maximises, and the window's edges
// resize it. Only in the app window: in a web browser none of this shows.
(function () {
  let W = null, maxed = false, act = null, busy = false, want = null;
  const body = document.body;
  const NOT_DRAG = "a, button, input, select, textarea, .chip, .t, .menu, [data-menu], [data-go]";

  function setMax(on) {
    maxed = !!on;
    body.classList.toggle("maxed", maxed);
    const b = document.querySelector('#wincaps [data-w="max"]');
    if (b) b.title = maxed ? "Restore" : "Maximise";
  }
  async function toggleMax() {
    try { const st = await W.win_toggle_max(); setMax(st && st.maximized); } catch (e) { /* closing */ }
  }

  // One window call in flight at a time; mouse moves in between only keep the latest.
  function send(fn) {
    want = fn;
    if (busy) return;
    busy = true;
    const go = want; want = null;
    Promise.resolve(go()).catch(() => {}).finally(() => { busy = false; if (want) send(want); });
  }

  function end() {
    act = null;
    body.classList.remove("winmoving");
    window.removeEventListener("mousemove", onMove, true);
    window.removeEventListener("mouseup", end, true);
  }
  function begin(a) {
    act = a;
    body.classList.add("winmoving");
    window.addEventListener("mousemove", onMove, true);
    window.addEventListener("mouseup", end, true);
  }

  async function startDrag(ev) {
    const dpr = window.devicePixelRatio || 1;
    let r = null;
    if (maxed) {
      const ratio = ev.clientX / Math.max(1, window.innerWidth);
      r = await W.win_drag_out(ev.screenX * dpr, ev.screenY * dpr, ratio);
      setMax(false);
    } else {
      r = await W.win_rect();
    }
    if (!r) return begin({ kind: "drag", sx: ev.screenX, sy: ev.screenY, r: [window.screenX, window.screenY], dpr: 1 });   // not Windows: pywebview's own move
    begin({ kind: "drag", sx: ev.screenX, sy: ev.screenY, r, dpr });
  }

  async function startResize(ev, edge) {
    const r = await W.win_rect();
    if (!r) return;
    begin({ kind: "size", edge, sx: ev.screenX, sy: ev.screenY, r, dpr: window.devicePixelRatio || 1 });
  }

  function onMove(ev) {
    if (!act) return;
    if (!(ev.buttons & 1)) return end();
    const dx = (ev.screenX - act.sx) * act.dpr, dy = (ev.screenY - act.sy) * act.dpr;
    const [x, y, w, h] = act.r;
    if (act.kind === "drag") {
      const nx = Math.round(x + dx), ny = Math.round(y + dy);
      return send(() => W.win_move(nx, ny));
    }
    const minW = 1100 * act.dpr, minH = 680 * act.dpr, e = act.edge;
    let nx = x, ny = y, nw = w, nh = h;
    if (e.includes("e")) nw = Math.max(minW, w + dx);
    if (e.includes("s")) nh = Math.max(minH, h + dy);
    if (e.includes("w")) { nw = Math.max(minW, w - dx); nx = x + w - nw; }
    if (e.includes("n")) { nh = Math.max(minH, h - dy); ny = y + h - nh; }
    const rect = [nx, ny, nw, nh].map(Math.round);
    send(() => W.win_set_rect(rect[0], rect[1], rect[2], rect[3], act ? act.dpr : 1));
  }

  function dragArea(ev) {
    if (ev.button !== 0) return false;
    const t = ev.target;
    if (!t.closest("#bar, #wincaps")) return false;
    return !t.closest(NOT_DRAG);
  }

  function setup(api) {
    W = api;
    body.classList.add("frameless");
    document.getElementById("wincaps").hidden = false;
    document.getElementById("wedges").hidden = false;
    if (typeof fitBar === "function") fitBar();

    document.getElementById("wincaps").addEventListener("click", ev => {
      const b = ev.target.closest("[data-w]");
      if (!b) return;
      const w = b.dataset.w;
      if (w === "min") W.win_minimize();
      else if (w === "max") toggleMax();
      else if (w === "close") W.win_close();
    });
    document.addEventListener("mousedown", ev => {
      if (ev.detail > 1 || !dragArea(ev)) return;
      ev.preventDefault();
      startDrag(ev);
    });
    document.addEventListener("dblclick", ev => {
      if (!dragArea(ev)) return;
      end();
      toggleMax();
    });
    document.getElementById("wedges").addEventListener("mousedown", ev => {
      const e = ev.target.dataset && ev.target.dataset.e;
      if (!e || ev.button !== 0) return;
      ev.preventDefault();
      startResize(ev, e);
    });
  }

  async function init() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.win_state !== "function" || W) return;
    try {
      const st = await api.win_state();
      if (!st || !st.native) return;
      setup(api);
      setMax(st.maximized);
    } catch (e) { /* an older window without the buttons */ }
  }
  if (window.top === window) {
    window.addEventListener("pywebviewready", init);
    init();
  }
})();
