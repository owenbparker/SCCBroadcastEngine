// Composer: making and editing graphics. The graphic list and its layers on
// the left, the canvas in the middle (drag to move, handles to resize), the
// selected layer's properties and animation on the right.
"use strict";

(function composer() {
  const canvas = $("#canvas"), stage = $("#canvas-stage"), selLayer = $("#canvas-sel");
  let compId = null;          // the graphic being edited
  let comp = null;            // our copy of it (changes are saved as they're made)
  let root = null;            // its element on the canvas
  let selected = null;        // selected layer id
  const multi = new Set();    // more layers picked with Ctrl / Shift (their "Show when" set together)
  let scale = 0.5, offX = 0, offY = 0;
  let pending = false, lastSent = "";
  const undo = [], redo = [];
  try { compId = localStorage.getItem("gfx-edit"); } catch (e) { /* */ }

  const TYPE_ICON = { text: "T", rect: "▭", image: "🖼", video: "▶", lottie: "✦", bracket: "⊏", web: "◫" };

  // --- saving ------------------------------------------------------------
  const saveSoon = debounce(save, 120);
  function save() {
    if (!comp) return;
    const body = JSON.stringify(comp);
    if (body === lastSent) { pending = false; return; }
    lastSent = body;
    api("/api/comp/save", { comp }).finally(() => { pending = false; });
  }
  function changed(opts) {
    tidyGroups();
    pending = true;
    saveSoon();
    redraw();
    if (!opts || !opts.keepList) renderLayers();
    if (opts && opts.props) renderProps();
    else syncPropsGeometry();
  }
  function snapshot() {
    undo.push(JSON.stringify(comp));
    if (undo.length > 100) undo.shift();
    redo.length = 0;
  }
  function restore(json) {
    comp = JSON.parse(json);
    if (!comp.layers.some(l => l.id === selected)) selected = null;
    for (const id of [...multi]) if (!comp.layers.some(l => l.id === id)) multi.delete(id);
    if (multi.size < 2) multi.clear();
    changed({ props: true });
  }

  // --- the graphic list ---------------------------------------------------
  function renderComps() {
    const list = $("#comp-list");
    const comps = App.comps();
    const sig = JSON.stringify(comps.map(c => [c.id, c.name, c.layers]) ) + compId;
    if (list.dataset.sig === sig) return;
    list.dataset.sig = sig;
    list.replaceChildren(...comps.map(c => h("div", { class: "comp-item" + (c.id === compId ? " sel" : ""), onclick: () => open(c.id) },
      thumb(c, {}, 48), h("span", { class: "nm" }, c.name),
      h("button", { class: "comp-trash", title: `Delete "${c.name}"`, "aria-label": `Delete ${c.name}`,
        onclick: e => { e.stopPropagation(); deleteComp(c.id); } }))));
    if (!comps.length) list.replaceChildren(h("div", { class: "empty" }, "No graphics yet."));
  }
  function open(id) {
    compId = id;
    selected = null;
    multi.clear();
    undo.length = redo.length = 0;
    try { localStorage.setItem("gfx-edit", id); } catch (e) { /* */ }
    adopt(true);
  }
  // Takes the engine's copy of the graphic (unless we've changes on the way).
  function adopt(force) {
    const server = App.comp(compId) || App.comps()[0];
    if (!server) { comp = null; compId = null; draw(); renderLayers(); renderProps(); renderComps(); return; }
    if (server.id !== compId) { compId = server.id; force = true; }
    $("#comp-dup-groups").hidden = !/Tournament!Group [A-D]\b/.test(JSON.stringify(server.layers || []));
    const json = JSON.stringify(server);
    if (!force && (pending || json === JSON.stringify(comp))) return;
    if (!force && json === lastSent) return;
    comp = JSON.parse(json);
    lastSent = json;
    if (selected && !comp.layers.some(l => l.id === selected)) selected = null;
    draw();
    renderLayers();
    renderProps();
    renderComps();
  }
  $("#comp-new").addEventListener("click", async () => {
    const name = prompt("Name of the new graphic", "New graphic");
    if (!name) return;
    const r = await api("/api/comp/new", { name, after: compId });
    open(r.comp.id);
  });
  $("#comp-import").addEventListener("click", () => $("#comp-import-file").click());
  $("#comp-import-file").addEventListener("change", async e => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    let r = await upload(f, true);
    // (video and After Effects are converted / rendered first)
    if (r && r.job && !(r.comps && r.comps[0])) r = await waitJob(r.job);
    if (!(r && r.comps && r.comps[0])) return;
    if (r.comps.length && !r.missing_fonts && !r.imported) toast(`Made the graphic "${r.comps[0].name}"`);
    // (once the engine's update with the new graphic is here)
    const id = r.comps[0].id;
    for (let i = 0; i < 40 && !App.comp(id); i++) await new Promise(res => setTimeout(res, 100));
    open(id);
  });
  $("#comp-export").addEventListener("click", () => {
    if (!compId) return;
    toast(`Exporting "${App.comp(compId).name}"… send the .sccgfx file to the other PC and Import it there`);
    location.href = `/api/share?comps=${compId}`;
  });
  $("#comp-dup").addEventListener("click", async () => { if (compId) open((await api("/api/comp/duplicate", { id: compId })).comp.id); });
  $("#comp-dup-groups").addEventListener("click", async () => {
    if (!compId) return;
    const made = (await api("/api/comp/duplicate", { id: compId, groups: true })).comp;
    toast(`Made "${made.name}": it shows groups E-H (G and H hide with 6 groups)`);
    open(made.id);
  });
  // Asks first: a deleted graphic is gone (Undo doesn't bring it back).
  async function deleteComp(id) {
    const c = App.comp(id);
    if (!c || !confirm(`Delete the graphic "${c.name}"? It comes off air too, and it can't be undone.`)) return;
    await api("/api/comp/delete", { id });
    if (id === compId) compId = null;
    adopt(true);
  }
  $("#comp-del").addEventListener("click", () => { if (compId) deleteComp(compId); });

  // --- layers ---------------------------------------------------------------
  // Groups: layers with the same "group" id (and "groupName") sit together in
  // the stack and are picked, moved, lined up, hidden and locked as one (the
  // same as HUD Builder's groups). Alt + click on the canvas, or a click on
  // its row in Layers, picks one layer inside. A group's row folds up.
  let dragLayer = null;
  const GROUP_CLOSED_KEY = "gfx-groups-closed";
  let closedGroups = new Set();
  try { closedGroups = new Set(JSON.parse(localStorage.getItem(GROUP_CLOSED_KEY) || "[]")); } catch (e) { /* */ }
  function foldGroup(g, closed) {
    if (closed) closedGroups.add(g); else closedGroups.delete(g);
    try { localStorage.setItem(GROUP_CLOSED_KEY, JSON.stringify([...closedGroups].slice(-300))); } catch (e) { /* */ }
    renderLayers();
  }
  // (the picked layers, in stacking order)
  const picked = () => !comp ? [] : multi.size > 1 ? comp.layers.filter(x => multi.has(x.id)) : comp.layers.filter(x => x.id === selected);
  const membersOf = g => comp ? comp.layers.filter(x => x.group === g) : [];
  const groupNameOf = g => (membersOf(g).find(x => x.groupName) || {}).groupName || "Group";
  // (the layers a click on this one picks: its whole group, or just it)
  const withGroup = l => l && l.group ? membersOf(l.group) : l ? [l] : [];
  function renderLayers() {
    const list = $("#layer-list");
    if (!comp) { list.replaceChildren(); return; }
    // Top layer first, as in Photoshop.
    const rows = [], done = new Set();
    for (const l of [...comp.layers].reverse()) {
      if (done.has(l.group)) continue;
      if (l.group && membersOf(l.group).length > 1) {
        done.add(l.group);
        const members = membersOf(l.group).reverse();
        const closed = closedGroups.has(l.group);
        rows.push(groupRow(l.group, members, closed));
        if (!closed) members.forEach(m => rows.push(layerRow(m, true)));
      } else rows.push(layerRow(l, false));
    }
    list.replaceChildren(...rows);
  }
  // Dropped on a row: the dragged layer (or group) goes just above it. On a
  // layer in a group it joins that group; a grouped layer dropped on one
  // that isn't in a group leaves its group.
  function dropOn(target) {
    const ids = dragLayer;
    dragLayer = null;
    if (!ids || !comp) return;
    const targetIds = target.group ? membersOf(target.group).map(x => x.id) : [target.id];
    if (target.row === "group" ? targetIds.some(id => ids.includes(id)) : ids.includes(target.id)) return;
    snapshot();
    const moving = comp.layers.filter(x => ids.includes(x.id));
    comp.layers = comp.layers.filter(x => !ids.includes(x.id));
    const over = target.row === "group" ? targetIds : [target.id];
    const onLayer = target.row !== "group" && comp.layers.find(x => x.id === target.id);
    // (a whole group dropped in another group goes above that group)
    const whole = moving.length > 1 && moving[0].group && moving.every(m => m.group === moving[0].group) && !membersOf(moving[0].group).length;
    let at = Math.max(...over.map(id => comp.layers.findIndex(x => x.id === id))) + 1;
    if (onLayer && whole && onLayer.group) at = Math.max(...membersOf(onLayer.group).map(x => comp.layers.indexOf(x))) + 1;
    else if (onLayer && onLayer.group) moving.forEach(m => { m.group = onLayer.group; m.groupName = groupNameOf(onLayer.group); });
    else if (onLayer && !whole) moving.forEach(m => { delete m.group; delete m.groupName; });
    comp.layers.splice(at, 0, ...moving);
    changed();
  }
  const dragProps = (ids, target) => ({
    draggable: true,
    ondragstart: e => { dragLayer = ids(); e.dataTransfer.effectAllowed = "move"; e.stopPropagation(); },
    ondragover: e => { e.preventDefault(); e.currentTarget.classList.add("drag-over"); },
    ondragleave: e => e.currentTarget.classList.remove("drag-over"),
    ondrop: e => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.remove("drag-over"); dropOn(target); },
  });
  function groupRow(g, members, closed) {
    const allPicked = members.every(m => m.id === selected || multi.has(m.id)) && (members.length < 2 || multi.size > 1);
    const hidden = members.every(m => m.visible === false), locked = members.every(m => m.locked);
    const name = groupNameOf(g);
    return h("div", Object.assign({
      class: "ly grp" + (allPicked ? " sel" : ""),
      onmousedown: e => { if (e.shiftKey) e.preventDefault(); },
      onclick: e => (e.ctrlKey || e.metaKey || e.shiftKey) ? pickToo(members[0].id, members) : pickLayers(members, members[0].id),
      ondblclick: e => { e.stopPropagation(); renameGroup(g); },
    }, dragProps(() => membersOf(g).map(x => x.id), { group: g, row: "group" })),
      h("span", { class: "eye" + (hidden ? " off" : ""), title: hidden ? "Show the group" : "Hide the group",
        onclick: e => { e.stopPropagation(); snapshot(); members.forEach(m => { m.visible = hidden; }); changed(); } }, "👁"),
      h("span", { class: "fold", title: closed ? "Open the group" : "Fold the group up",
        onclick: e => { e.stopPropagation(); foldGroup(g, !closed); } }, closed ? "▸" : "▾"),
      h("span", { class: "ic" }, "▣"),
      h("span", { class: "nm", title: `${name}: double-click to rename` }, name),
      h("span", { class: "cnt" }, String(members.length)),
      h("span", { class: "lock" + (locked ? " on" : ""), title: locked ? "Unlock the group" : "Lock the group (can't be picked, moved or deleted on the canvas)",
        onclick: e => { e.stopPropagation(); setLocked(members, !locked); } }, locked ? "🔒" : "🔓"));
  }
  function layerRow(l, inGroup) {
    return h("div", Object.assign({
      class: "ly" + (inGroup ? " in" : "") + (l.id === selected || multi.has(l.id) ? " sel" : ""),
      onmousedown: e => { if (e.shiftKey) e.preventDefault(); },  // no text highlight on Shift+click
      onclick: e => e.shiftKey ? pickRange(l.id, e.ctrlKey || e.metaKey) : (e.ctrlKey || e.metaKey) ? pickToo(l.id) : selectLayer(l.id),
    }, dragProps(() => [l.id], { id: l.id, group: l.group, row: "layer" })),
      h("span", { class: "eye" + (l.visible === false ? " off" : ""), title: "Show / hide",
        onclick: e => { e.stopPropagation(); snapshot(); l.visible = l.visible === false; changed(); } }, "👁"),
      h("span", { class: "ic" }, TYPE_ICON[l.type] || "?"),
      h("span", { class: "nm", title: l.name }, l.name),
      l.field ? h("span", { class: "fld", title: `Changed from Control as "${l.field}"` }, "field") : null,
      linked(l) ? h("span", { class: "fld live", title: "Follows live data" }, "live") : null,
      h("span", { class: "lock" + (l.locked ? " on" : ""), title: l.locked ? "Unlock" : "Lock (can't be picked, moved or deleted on the canvas)",
        onclick: e => { e.stopPropagation(); setLocked([l], !l.locked); } }, l.locked ? "🔒" : "🔓"));
  }
  function renameGroup(g) {
    const v = prompt("Name of the group", groupNameOf(g));
    if (v == null || !v.trim()) return;
    snapshot();
    membersOf(g).forEach(m => { m.groupName = v.trim().slice(0, 80); });
    changed({ props: true });
  }
  // Ctrl+G: the picked layers become one group (where the top one is in the
  // stack). Layers already in a group move into the new one.
  function groupLayers() {
    if (!comp) return;
    const list = picked();
    if (list.length < 2) return toast("Pick two or more layers to group (Ctrl or Shift + click)", true);
    snapshot();
    const ids = new Set(list.map(x => x.id));
    const g = "g" + Math.random().toString(16).slice(2, 10);
    const taken = new Set(comp.layers.map(x => x.groupName).filter(Boolean));
    let n = 1;
    while (taken.has("Group " + n)) n++;
    const top = Math.max(...list.map(x => comp.layers.indexOf(x)));
    const rest = comp.layers.filter(x => !ids.has(x.id));
    const at = rest.filter(x => comp.layers.indexOf(x) < top).length;
    list.forEach(x => { x.group = g; x.groupName = "Group " + n; });
    rest.splice(at, 0, ...list);
    comp.layers = rest;
    multi.clear();
    list.forEach(x => multi.add(x.id));
    changed({ props: true });
    toast("Grouped: they're picked, moved, hidden and locked together. Alt + click picks one inside.");
  }
  // Ctrl+Shift+G: the picked layers leave their groups (all of a group
  // picked: the group goes).
  function ungroupLayers() {
    if (!comp) return;
    const list = picked().filter(x => x.group);
    if (!list.length) return toast("Pick a group to ungroup", true);
    snapshot();
    list.forEach(x => { delete x.group; delete x.groupName; });
    changed({ props: true });
  }
  // Groups stay whole: one layer left is no group, and a group's layers sit
  // together in the stack (where its top one is).
  function tidyGroups() {
    if (!comp) return;
    const count = {};
    comp.layers.forEach(x => { if (x.group) count[x.group] = (count[x.group] || 0) + 1; });
    comp.layers.forEach(x => { if (x.group && count[x.group] < 2) { delete x.group; delete x.groupName; } });
    const top = {};
    comp.layers.forEach((x, i) => { if (x.group) top[x.group] = i; });
    const out = [];
    comp.layers.forEach((x, i) => { if (!x.group) out.push(x); else if (top[x.group] === i) out.push(...comp.layers.filter(m => m.group === x.group)); });
    comp.layers = out;
  }
  // Lock: a locked layer can't be clicked, dragged, resized, nudged or
  // deleted on the canvas. Pick it in the list to change it in the panel.
  function setLocked(layers, on) {
    snapshot();
    layers.forEach(l => { if (on) l.locked = true; else delete l.locked; });
    changed({ props: true });
  }
  // Does the layer follow live data (a link, a fill or a "Show when")?
  const linked = l => !!(l.meter || l.when || [l.text, l.src, l.fill].some(v => /\{\{\s*(Rocket League HUD|Global)!/i.test(v || "")));
  // Shift + click: every layer from the last one clicked down (or up) to this
  // one, as in Photoshop. Ctrl + Shift adds the range to what's picked.
  let rangeFrom = null;
  function pickRange(id, add) {
    const ids = comp.layers.map(x => x.id);
    let a = rangeFrom === selected || multi.has(rangeFrom) ? ids.indexOf(rangeFrom) : -1;
    if (a < 0) a = ids.indexOf(selected);
    const b = ids.indexOf(id);
    if (a < 0 || b < 0) return selectLayer(id);
    if (!add) multi.clear(); else if (!multi.size && selected) multi.add(selected);
    for (let i = Math.min(a, b); i <= Math.max(a, b); i++) multi.add(ids[i]);
    selected = id;
    if (multi.size < 2) multi.clear();
    renderLayers();
    renderProps();
    drawSelection();
  }
  // Ctrl + click: one more layer (or one less); a group's row: the group.
  function pickToo(id, also) {
    rangeFrom = id;
    if (!multi.size && selected) multi.add(selected);
    const ids = (also || [layerById(id)]).filter(Boolean).map(x => x.id);
    const all = ids.every(x => multi.has(x));
    ids.forEach(x => all ? multi.delete(x) : multi.add(x));
    selected = multi.has(id) ? id : [...multi].pop() || null;
    if (multi.size < 2) multi.clear();
    renderLayers();
    renderProps();
    drawSelection();
  }
  // A group (or any set of layers), picked together; id is the main one.
  function pickLayers(layers, id) {
    rangeFrom = id;
    multi.clear();
    if (layers.length > 1) layers.forEach(x => multi.add(x.id));
    selected = id;
    renderLayers();
    renderProps();
    drawSelection();
  }
  function selectLayer(id) {
    rangeFrom = id;
    multi.clear();
    selected = id;
    renderLayers();
    renderProps();
    drawSelection();
  }
  document.querySelectorAll("[data-add]").forEach(b => b.addEventListener("click", async () => {
    if (!comp) return toast("Make or pick a graphic first", true);
    const { layer } = await api("/api/layer/blank", { type: b.dataset.add });
    snapshot();
    layer.name = { text: "Text", rect: "Shape", image: "Picture", video: "Video", lottie: "Animation" }[layer.type];
    comp.layers.push(layer);
    selected = layer.id;
    changed({ props: true });
  }));

  // Special elements: layers that show what Global has (and change with it).
  const pictureOf = (src, w, h) => ({ src, w, h, x: Math.round((GFX.W - w) / 2), y: Math.round((GFX.H - h) / 2), fit: "contain" });
  const textOf = (text, extra) => Object.assign({ text, font: "Bebas Neue", weight: 400, size: 72, caps: true, w: 600, h: 90 }, extra);
  const SPECIAL = [
    ["Logos", [
      ["Left team logo", "image", pictureOf("{{Global!Left logo}}", 240, 240)],
      ["Right team logo", "image", pictureOf("{{Global!Right logo}}", 240, 240)],
      ["Tournament logo", "image", pictureOf("{{Global!Tournament logo}}", 260, 260)],
      ["Sponsors (in turn)", "image", Object.assign(pictureOf("{{Sponsors}}", 320, 120), { timer: false })]]],
    ["Teams", [
      ["Left team name", "text", textOf("{{Global!Left name}}")],
      ["Right team name", "text", textOf("{{Global!Right name}}", { align: "right" })],
      ["Left short name", "text", textOf("{{Global!Left short}}", { w: 220 })],
      ["Right short name", "text", textOf("{{Global!Right short}}", { w: 220, align: "right" })],
      ["Left score", "text", textOf("{{Global!Left score}}", { w: 140, size: 96, h: 120, align: "center" })],
      ["Right score", "text", textOf("{{Global!Right score}}", { w: 140, size: 96, h: 120, align: "center" })],
      ["Left team colour", "rect", { fill: "{{Global!Left color}}", w: 400, h: 12 }],
      ["Right team colour", "rect", { fill: "{{Global!Right color}}", w: 400, h: 12 }]]],
    ["Event", [
      ["Event", "text", textOf("{{Global!Event}}", { size: 40, h: 54 })],
      ["Stage", "text", textOf("{{Global!Stage}}", { size: 40, h: 54 })],
      ["Game number", "text", textOf("GAME {{Global!Game}}", { size: 40, h: 54 })],
      ["Ticker", "text", { text: "{{Global!Ticker}}", font: "Inter", weight: 600, size: 28, caps: true, scroll: 90, fit: "none", x: 0, y: 1030, w: 1920, h: 40 }],
      ["Background loop", "video", { src: "{{Global!BG loop}}", x: 0, y: 0, w: 1920, h: 1080, fit: "cover", blend: "screen", audio: false,
        tint: "{{Global!BG loop colour}}", brightness: "{{Global!BG loop brightness}}", speed: "{{Global!BG loop speed}}" }]]],
    ["Rocket League HUD", [
      ["Spectated player's cam", "web", { src: "{{Rocket League HUD!target_cam}}", x: 40, y: 760, w: 360, h: 240,
        when: [{ value: "{{Rocket League HUD!target_has_cam}}", op: "has" }],
        anim: { in: { type: "slide-up", dur: 400, delay: 0 }, out: { type: "slide-up", dur: 350, delay: 0 } } }],
      ["Spectated player's name", "text", textOf("{{Rocket League HUD!target}}")],
      ["Spectated player's boost", "text", textOf("{{Rocket League HUD!target_boost}}", { w: 160, size: 96, h: 120, align: "center" })],
      ["Clock", "text", textOf("{{Rocket League HUD!clock}}", { w: 220, align: "center" })]]],
    ["Tournament", [
      ["Knockout bracket (8 or 16)", "bracket", { x: 144, y: 196, w: 1566, h: 748, font: "Bebas Neue", color: "#ffffff",
        gold: "#b28a1d", dark: "#000b05", line: "#b28a1d", champ: "#ffc52a" }],
      ["Champion", "text", textOf("{{Tournament!Top champion}}")],
      ["Bracket size (8 / 16)", "text", textOf("{{Tournament!Top teams}} COMPETITOR BRACKET", { size: 48, h: 64 })]]],
  ];
  const special = $("#add-special");
  special.replaceChildren(h("option", { value: "" }, "★"),
    ...SPECIAL.map(([group, items], gi) => h("optgroup", { label: group }, ...items.map((it, i) => h("option", { value: gi + ":" + i }, it[0])))));
  special.addEventListener("change", async () => {
    const v = special.value;
    special.value = "";
    if (!v) return;
    if (!comp) return toast("Make or pick a graphic first", true);
    const [gi, i] = v.split(":").map(Number);
    const [name, type, extra] = SPECIAL[gi][1][i];
    const { layer } = await api("/api/layer/blank", { type });
    snapshot();
    Object.assign(layer, JSON.parse(JSON.stringify(extra)), { name });
    if (layer.type === "image" && !layer.src.includes("Sponsors")) layer.placeholder = "";
    comp.layers.push(layer);
    selected = layer.id;
    changed({ props: true });
  });

  // --- the canvas --------------------------------------------------------------
  // Zoom: Ctrl + scroll wheel zooms toward the mouse, the scroll wheel pans
  // while zoomed in (Shift: sideways), middle mouse or Space + drag pans too,
  // Ctrl+0 or the zoom button fits the whole graphic again. zoom is relative
  // to "fit"; offX/offY are where the graphic's top left sits on screen.
  let zoom = 1, spaceDown = false;
  const ZOOM_MIN = 0.25, ZOOM_MAX = 16;
  const fitScale = r => Math.max(0.01, Math.min((r.width - 48) / GFX.W, (r.height - 48) / GFX.H));
  function applyView() {
    const r = canvas.getBoundingClientRect();
    // Keep at least 80 px of the graphic on screen.
    const w = GFX.W * scale, hh = GFX.H * scale, keep = 80;
    offX = Math.min(r.width - keep, Math.max(keep - w, offX));
    offY = Math.min(r.height - keep, Math.max(keep - hh, offY));
    stage.style.transform = `translate(${offX}px, ${offY}px) scale(${scale})`;
    const zb = $("#canvas-zoom");
    if (zb) zb.textContent = zoom === 1 ? "Fit" : Math.round(scale * 100) + "%";   // % of real size
    canvas.classList.toggle("zoomed", zoom !== 1);
    drawSelection();
  }
  function fitStage() {
    const r = canvas.getBoundingClientRect();
    zoom = 1;
    scale = fitScale(r);
    offX = (r.width - GFX.W * scale) / 2;
    offY = (r.height - GFX.H * scale) / 2;
    applyView();
  }
  function zoomTo(z, cx, cy) {
    const r = canvas.getBoundingClientRect();
    if (cx == null) { cx = r.width / 2; cy = r.height / 2; }
    zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
    if (Math.abs(zoom - 1) < 0.02) return fitStage();
    // The point of the graphic under (cx, cy) stays under it.
    const gx = (cx - offX) / scale, gy = (cy - offY) / scale;
    scale = fitScale(r) * zoom;
    offX = cx - gx * scale; offY = cy - gy * scale;
    applyView();
  }
  let lastSize = null;
  new ResizeObserver(() => {
    const r = canvas.getBoundingClientRect();
    if (zoom === 1 || !lastSize) fitStage();
    else {
      // Keep the middle of the view where it was and the same zoom.
      offX += (r.width - lastSize[0]) / 2; offY += (r.height - lastSize[1]) / 2;
      scale = fitScale(r) * zoom;
      applyView();
    }
    lastSize = [r.width, r.height];
  }).observe(canvas);
  canvas.addEventListener("wheel", e => {
    if (!comp) return;
    const r = canvas.getBoundingClientRect();
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      // Pixel or line deltas; trackpad pinch also arrives as Ctrl + wheel.
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      zoomTo(zoom * Math.exp(-Math.max(-300, Math.min(300, dy)) * 0.0015), e.clientX - r.left, e.clientY - r.top);
    } else if (zoom > 1) {
      e.preventDefault();
      const k = e.deltaMode === 1 ? 33 : 1;
      if (e.shiftKey && !e.deltaX) offX -= e.deltaY * k;
      else { offX -= e.deltaX * k; offY -= e.deltaY * k; }
      applyView();
    }
  }, { passive: false });
  // Middle mouse, or Space held, drags the view.
  canvas.addEventListener("mousedown", e => {
    if (!(e.button === 1 || (e.button === 0 && spaceDown))) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const sx = e.clientX - offX, sy = e.clientY - offY;
    canvas.classList.add("panning");
    const move = ev => { offX = ev.clientX - sx; offY = ev.clientY - sy; applyView(); };
    const up = () => { removeEventListener("mousemove", move); removeEventListener("mouseup", up); canvas.classList.remove("panning"); };
    addEventListener("mousemove", move);
    addEventListener("mouseup", up);
  }, true);
  canvas.addEventListener("auxclick", e => { if (e.button === 1) e.preventDefault(); });
  addEventListener("keydown", e => {
    if (App.tab !== "composer" || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const mod = e.ctrlKey || e.metaKey;
    if (e.key === " " && !mod) { e.preventDefault(); if (!spaceDown) { spaceDown = true; canvas.classList.add("can-pan"); } return; }
    if (!mod) return;
    if (e.key === "0") { e.preventDefault(); fitStage(); }
    else if (e.key === "1") { e.preventDefault(); zoomTo(1 / fitScale(canvas.getBoundingClientRect())); }   // 100%: real pixels
    else if (e.key === "=" || e.key === "+") { e.preventDefault(); zoomTo(zoom * 1.25); }
    else if (e.key === "-") { e.preventDefault(); zoomTo(zoom / 1.25); }
  });
  addEventListener("keyup", e => { if (e.key === " ") { spaceDown = false; canvas.classList.remove("can-pan"); } });
  addEventListener("blur", () => { spaceDown = false; canvas.classList.remove("can-pan"); });
  $("#canvas-zoom").addEventListener("click", fitStage);
  $("#canvas-bg").addEventListener("change", e => { canvas.className = "canvas " + e.target.value; try { localStorage.setItem("gfx-canvas-bg", e.target.value); } catch (err) { /* */ } });
  try { const bg = localStorage.getItem("gfx-canvas-bg"); if (bg) { $("#canvas-bg").value = bg; } } catch (e) { /* */ }
  canvas.className = "canvas " + $("#canvas-bg").value;

  function draw() {
    if (root) { GFX.destroy(root); root.remove(); root = null; }
    $("#canvas-name").textContent = comp ? comp.name : "";
    if (!comp) return;
    root = GFX.buildComp(comp, {}, { showHidden: true, muted: true });
    stage.appendChild(root);
    drawSelection();
  }
  function redraw() {
    if (!comp) return;
    if (!root) return draw();
    GFX.updateComp(root, comp, {});
    $("#canvas-name").textContent = comp.name;
    drawSelection();
  }
  const layerById = id => comp && comp.layers.find(l => l.id === id);
  const toScreen = (x, y) => [offX + x * scale, offY + y * scale];

  // The box around some layers.
  const boundsOf = layers => {
    const x = Math.min(...layers.map(o => o.x)), y = Math.min(...layers.map(o => o.y));
    return { x, y, w: Math.max(...layers.map(o => o.x + o.w)) - x, h: Math.max(...layers.map(o => o.y + o.h)) - y };
  };
  const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
  function drawSelection(guides) {
    selLayer.replaceChildren();
    for (const id of multi) {
      const o = layerById(id);
      if (!o || id === selected) continue;
      const [ox, oy] = toScreen(o.x, o.y);
      selLayer.appendChild(h("div", { class: "sel-box also", style: { left: ox + "px", top: oy + "px", width: o.w * scale + "px", height: o.h * scale + "px",
        transform: o.rotation ? `rotate(${o.rotation}deg)` : "" } }));
    }
    const l = layerById(selected);
    if (!l) { $("#canvas-pos").textContent = ""; return; }
    // A group picked whole: a box around it.
    const groups = new Set(picked().map(o => o.group).filter(g => g && membersOf(g).every(m => m.id === selected || multi.has(m.id))));
    for (const g of groups) {
      const b = boundsOf(membersOf(g));
      const [gx, gy] = toScreen(b.x, b.y);
      selLayer.appendChild(h("div", { class: "sel-box group", style: { left: gx + "px", top: gy + "px", width: b.w * scale + "px", height: b.h * scale + "px" } },
        h("span", { class: "sel-tag" }, groupNameOf(g))));
    }
    const [x, y] = toScreen(l.x, l.y);
    const w = l.w * scale, hgt = l.h * scale;
    const many = multi.size > 1;
    const box = h("div", { class: "sel-box" + (l.locked ? " locked" : "") + (many ? " also" : ""), style: { left: x + "px", top: y + "px", width: w + "px", height: hgt + "px",
      transform: l.rotation ? `rotate(${l.rotation}deg)` : "" } });
    // (handles: one layer picked; in a group, Alt + click picks one to resize)
    if (!l.locked && !many) for (const hd of HANDLES) {
      const hx = hd.includes("w") ? 0 : hd.includes("e") ? 100 : 50;
      const hy = hd.includes("n") ? 0 : hd.includes("s") ? 100 : 50;
      box.appendChild(h("div", { class: "handle", "data-h": hd, style: { left: hx + "%", top: hy + "%", cursor: hd + "-resize" } }));
    }
    selLayer.appendChild(box);
    for (const g of guides || []) {
      if (g.x != null) { const [gx] = toScreen(g.x, 0); selLayer.appendChild(h("div", { class: "guide", style: { left: gx + "px", top: 0, bottom: 0, width: "1px" } })); }
      if (g.y != null) { const [, gy] = toScreen(0, g.y); selLayer.appendChild(h("div", { class: "guide", style: { top: gy + "px", left: 0, right: 0, height: "1px" } })); }
    }
    const p = many ? boundsOf(picked()) : l;
    $("#canvas-pos").textContent = `${Math.round(p.x)}, ${Math.round(p.y)} · ${Math.round(p.w)}×${Math.round(p.h)}` +
      (many ? ` · ${multi.size} layers` : l.locked ? " · locked" : "");
  }

  // Which layer is at a point (top first, visible ones only).
  function hit(px, py) {
    for (const l of [...comp.layers].reverse()) {
      if (l.visible === false || l.locked) continue;
      if (px >= l.x && px <= l.x + l.w && py >= l.y && py <= l.y + l.h) return l;
    }
    return null;
  }
  // Snapping to the canvas' edges and middle and other layers' edges and middles.
  // (l: the box that moves, a layer or a group's bounds; skip: the layers in it)
  function snap(l, moving, skip) {
    const tol = 6 / scale;
    const xs = [0, GFX.W / 2, GFX.W], ys = [0, GFX.H / 2, GFX.H];
    for (const o of comp.layers) {
      if (o.id === l.id || (skip && skip.has(o.id)) || o.visible === false) continue;
      xs.push(o.x, o.x + o.w / 2, o.x + o.w);
      ys.push(o.y, o.y + o.h / 2, o.y + o.h);
    }
    const guides = [];
    const best = (vals, cands) => {
      let b = null;
      for (const [edge, off] of vals) for (const c of cands) if (Math.abs(edge - c) < tol && (!b || Math.abs(edge - c) < Math.abs(b.d))) b = { d: c - edge, c, off };
      return b;
    };
    if (moving) {
      const bx = best([[l.x, 0], [l.x + l.w / 2, 0], [l.x + l.w, 0]], xs);
      if (bx) { l.x += bx.d; guides.push({ x: bx.c }); }
      const by = best([[l.y, 0], [l.y + l.h / 2, 0], [l.y + l.h, 0]], ys);
      if (by) { l.y += by.d; guides.push({ y: by.c }); }
    }
    return guides;
  }

  const inside = (o, px, py) => px >= o.x && px <= o.x + o.w && py >= o.y && py <= o.y + o.h;
  canvas.addEventListener("mousedown", e => {
    if (!comp || e.button !== 0) return;
    const r = canvas.getBoundingClientRect();
    const px = (e.clientX - r.left - offX) / scale, py = (e.clientY - r.top - offY) / scale;
    const handle = e.target.dataset && e.target.dataset.h;
    let l = layerById(selected);
    if (!handle) {
      const under = hit(px, py);
      // Ctrl / Shift + click on another layer picks it too (or drops it), with its group.
      if ((e.shiftKey || e.ctrlKey || e.metaKey) && !e.altKey && under && (under.id !== selected || multi.size > 1) && (selected || multi.size)) {
        e.preventDefault();
        return pickToo(under.id, withGroup(under));
      }
      // Clicking inside what's picked keeps it (it may be under another).
      // Alt + click: just the layer under the mouse, even in a group.
      const keep = !e.altKey && picked().find(o => !o.locked && o.visible !== false && inside(o, px, py));
      if (keep) l = keep;
      else {
        l = under;
        if (l && !e.altKey && l.group) {
          pickLayers(withGroup(l), l.id);
          return drag(e, l, null, px, py, r);
        }
        if (!l || !multi.has(l.id) || e.altKey) multi.clear();
        selected = l ? l.id : null;
        rangeFrom = selected;
        renderLayers();
        renderProps();
        drawSelection();
      }
      if (!l) return;
    }
    if (l.locked) return;
    drag(e, l, handle, px, py, r);
  });
  // Dragging the picked layers (locked ones stay put), or a handle of the one picked.
  function drag(e, l, handle, px, py, r) {
    e.preventDefault();
    const group = handle ? [l] : picked().filter(o => !o.locked);
    if (!group.length) return;
    const starts = group.map(o => ({ o, x: o.x, y: o.y }));
    const skip = new Set(group.map(o => o.id));
    const start = Object.assign(handle ? { x: l.x, y: l.y, w: l.w, h: l.h } : boundsOf(group), { px, py });
    const ratio = l.w / Math.max(1, l.h);
    let moved = false;
    const move = ev => {
      const qx = (ev.clientX - r.left - offX) / scale, qy = (ev.clientY - r.top - offY) / scale;
      let dx = qx - start.px, dy = qy - start.py;
      if (!moved && Math.abs(dx) < 2 && Math.abs(dy) < 2) return;
      if (!moved) { snapshot(); moved = true; }
      let guides = [];
      if (!handle) {
        if (ev.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
        // (the whole box snaps, then every layer in it moves the same)
        const box = { id: null, x: Math.round(start.x + dx), y: Math.round(start.y + dy), w: start.w, h: start.h };
        if (!ev.ctrlKey) guides = snap(box, true, skip);
        const mx = Math.round(box.x) - start.x, my = Math.round(box.y) - start.y;
        for (const st of starts) { st.o.x = st.x + mx; st.o.y = st.y + my; }
      } else {
        let { x, y, w, h: hh } = start;
        if (handle.includes("e")) w = Math.max(4, start.w + dx);
        if (handle.includes("s")) hh = Math.max(4, start.h + dy);
        if (handle.includes("w")) { w = Math.max(4, start.w - dx); x = start.x + start.w - w; }
        if (handle.includes("n")) { hh = Math.max(4, start.h - dy); y = start.y + start.h - hh; }
        if (ev.shiftKey && handle.length === 2) {
          // Keep the shape.
          if (w / hh > ratio) { hh = w / ratio; if (handle.includes("n")) y = start.y + start.h - hh; }
          else { w = hh * ratio; if (handle.includes("w")) x = start.x + start.w - w; }
        }
        Object.assign(l, { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(hh) });
      }
      pending = true;
      saveSoon();
      redraw();
      drawSelection(guides);
      syncPropsGeometry();
    };
    const up = () => {
      removeEventListener("mousemove", move);
      removeEventListener("mouseup", up);
      if (moved) changed();
      drawSelection();
    };
    addEventListener("mousemove", move);
    addEventListener("mouseup", up);
  }
  canvas.addEventListener("dblclick", () => {
    const l = layerById(selected);
    if (l && l.type === "text") { const t = document.querySelector("#props textarea[data-k=text]"); if (t) { t.focus(); t.select(); } }
  });

  addEventListener("keydown", e => {
    if (App.tab !== "composer" || !comp || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const l = layerById(selected);
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "z") {
      e.preventDefault();
      const from = e.shiftKey ? redo : undo, to = e.shiftKey ? undo : redo;
      if (from.length) { to.push(JSON.stringify(comp)); restore(from.pop()); }
      return;
    }
    if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); if (redo.length) { undo.push(JSON.stringify(comp)); restore(redo.pop()); } return; }
    if (mod && e.key.toLowerCase() === "v" && !e.altKey) { e.preventDefault(); pasteLayers(); return; }
    if (mod && e.key.toLowerCase() === "g" && !e.altKey) { e.preventDefault(); if (e.shiftKey) ungroupLayers(); else groupLayers(); return; }
    if (!l) return;
    if (mod && (e.key.toLowerCase() === "c" || e.key.toLowerCase() === "x") && !e.altKey) {
      e.preventDefault();
      copyLayers(e.key.toLowerCase() === "x");
      return;
    }
    const step = e.shiftKey ? 10 : 1;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) {
      e.preventDefault();
      const free = picked().filter(o => !o.locked);
      if (!free.length) return toast("That layer is locked: unlock it (🔒 in Layers) to move it", true);
      snapshot();
      free.forEach(o => { o.x += moves[e.key][0]; o.y += moves[e.key][1]; });
      changed({ keepList: true });
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      removeLayers(picked());
    } else if (mod && e.key.toLowerCase() === "d") {
      e.preventDefault();
      if (multi.size > 1) placeLayers(picked(), 20, " copy");
      else duplicateLayer(l);
    } else if (e.key === "Escape") {
      selectLayer(null);
    }
  });
  // --- copy and paste -------------------------------------------------------
  // Ctrl+C / Ctrl+X copy the picked layers (all of a Ctrl / Shift pick, in
  // their stacking order) whole: style, field, live data links, "Show when",
  // animations and the files they use. Ctrl+V puts them in whichever graphic
  // is open, where they were (20 px on in the graphic they came from, more
  // each time), above the selected layer, with new ids. The copy is kept
  // while the engine runs (and in other Composer windows); from a graphic in
  // another workspace the engine brings the files over too.
  const CLIP_KEY = "gfx-layer-clip";
  let clip = null, pastes = {};
  const newLayerId = () => "l" + Math.random().toString(16).slice(2, 10);
  const workspaceId = () => (App.state && App.state.workspace && App.state.workspace.id) || "";
  function copyLayers(cut) {
    const layers = picked();
    if (!layers.length) return;
    clip = { kind: "scc-gfx-layers", workspace: workspaceId(), comp: compId, cut: !!cut, at: Date.now(),
      layers: JSON.parse(JSON.stringify(layers)) };
    pastes = {};
    try { localStorage.setItem(CLIP_KEY, JSON.stringify(clip)); } catch (e) { /* too big or private: this window keeps it */ }
    const what = layers.length === 1 ? `"${layers[0].name}"` : `${layers.length} layers`;
    if (cut && layers.every(l => l.locked)) toast(`Copied ${what}: it's locked, so it stays here (unlock it to cut)`);
    else if (cut) { removeLayers(layers); toast(`Cut ${what}: Ctrl+V pastes it into any graphic`); }
    else toast(`Copied ${what}: Ctrl+V pastes into any graphic`);
  }
  function readClip() {
    // (the newest copy, this window's or another Composer window's)
    let stored = null;
    try { stored = JSON.parse(localStorage.getItem(CLIP_KEY) || "null"); } catch (e) { /* */ }
    if (stored && stored.kind === "scc-gfx-layers" && (!clip || stored.at > clip.at)) { clip = stored; pastes = {}; }
    return clip;
  }
  async function pasteLayers() {
    if (!comp) return toast("Make or pick a graphic first", true);
    const c = readClip();
    if (!c || !c.layers || !c.layers.length) return toast("Nothing copied yet: pick a layer and press Ctrl+C", true);
    let layers = JSON.parse(JSON.stringify(c.layers));
    if (c.workspace && c.workspace !== workspaceId()) {
      // From another workspace: its pictures, videos and animations come too.
      const r = await api("/api/layer/paste", { workspace: c.workspace, layers });
      layers = r.layers;
      if (r.assets && r.assets.length) toast(`Brought ${r.assets.length} file(s) over from the other workspace`);
    }
    // Same graphic: a step on each time (a cut goes back where it was first).
    const here = c.comp === compId && c.workspace === workspaceId();
    const n = (pastes[compId] || 0) + (here && !c.cut ? 1 : 0);
    pastes[compId] = (pastes[compId] || 0) + 1;
    placeLayers(layers, 20 * n, "", true);
  }
  // Adds copies of the layers to the open graphic, above the selected layer
  // (or on top), and picks them.
  function placeLayers(layers, offset, suffix, fresh) {
    if (!layers.length) return;
    snapshot();
    const made = layers.map(src => {
      const l = fresh ? src : JSON.parse(JSON.stringify(src));
      l.id = newLayerId();
      if (suffix) l.name = (l.name || "Layer") + suffix;
      l.x = Math.round((+l.x || 0) + offset); l.y = Math.round((+l.y || 0) + offset);
      return l;
    });
    // (a field of the same name would be one field with another layer here)
    for (const l of made) if (l.field) l.field = uniqueField(l.field);
    // (copies of a group are a group of their own)
    const regroup = {};
    for (const l of made) if (l.group) l.group = regroup[l.group] = regroup[l.group] || "g" + Math.random().toString(16).slice(2, 10);
    const anchor = picked().reduce((i, x) => Math.max(i, comp.layers.indexOf(x)), -1);
    comp.layers.splice(anchor >= 0 ? anchor + 1 : comp.layers.length, 0, ...made);
    multi.clear();
    if (made.length > 1) made.forEach(l => multi.add(l.id));
    selected = made[made.length - 1].id;
    changed({ props: true });
  }
  function removeLayers(layers) {
    if (!layers.length) return;
    const kept = layers.filter(l => l.locked).length;
    layers = layers.filter(l => !l.locked);
    if (!layers.length) return toast("That layer is locked: unlock it (🔒 in Layers) to delete it", true);
    if (kept) toast(`${kept} locked layer(s) kept`);
    snapshot();
    const gone = new Set(layers.map(x => x.id));
    comp.layers = comp.layers.filter(x => !gone.has(x.id));
    multi.clear();
    selected = null;
    changed({ props: true });
  }

  function duplicateLayer(l) {
    snapshot();
    const copyL = JSON.parse(JSON.stringify(l));
    copyL.id = "l" + Math.random().toString(16).slice(2, 10);
    copyL.name = l.name + " copy";
    copyL.x += 20; copyL.y += 20;
    if (copyL.field) copyL.field = uniqueField(copyL.field);
    comp.layers.splice(comp.layers.indexOf(l) + 1, 0, copyL);
    selected = copyL.id;
    changed({ props: true });
  }
  function uniqueField(name) {
    const taken = new Set(comp.layers.map(l => (l.field || "").toLowerCase()));
    let n = 2, out = name;
    while (taken.has(out.toLowerCase())) out = `${name.replace(/ \d+$/, "")} ${n++}`;
    return out;
  }

  // Playing the animation on the canvas.
  $("#anim-in").addEventListener("click", () => { if (root) { GFX.finish(root); GFX.play(root, "in").then(() => {}); } });
  $("#anim-out").addEventListener("click", () => {
    if (!root) return;
    GFX.finish(root);
    GFX.play(root, "out").then(() => setTimeout(() => root && root.querySelectorAll(".gfx-A").forEach(a => a.getAnimations().forEach(x => x.cancel())), 600));
  });

  // --- properties ----------------------------------------------------------------
  const props = $("#props");
  // Recent fonts: the last ones picked, newest first, kept in this browser
  // (same key as HUD Builder's font lists, so they share one list).
  const RECENT_FONTS = "sccbe-recent-fonts";
  function recentFonts() {
    try { const a = JSON.parse(localStorage.getItem(RECENT_FONTS) || "[]"); return Array.isArray(a) ? a.filter(f => typeof f === "string" && f) : []; }
    catch (e) { return []; }
  }
  function useFont(name) {
    if (!name) return;
    try { localStorage.setItem(RECENT_FONTS, JSON.stringify([name, ...recentFonts().filter(f => f !== name)].slice(0, 12))); } catch (e) { }
  }
  function setFont(l, name) { snapshot(); l.font = name; useFont(name); changed({ props: true }); }
  function fontOptions(current) {
    const fonts = App.state.fonts || [];
    const assetFonts = fonts.filter(f => !f.adobe).map(f => f.postscript);
    const adobe = fonts.filter(f => f.adobe);
    const all = [...GFX.builtinFonts, ...assetFonts, ...adobe.map(f => f.postscript)];
    const nameOf = f => { const a = adobe.find(x => x.postscript === f); return a ? `${a.family} ${a.style}`.trim() : f; };
    let picked = false;   // only the first option for the current font is selected
    const sel = f => !picked && f === current ? (picked = true) : false;
    const out = [];
    if (current && !all.includes(current)) out.push(h("option", { value: current, selected: sel(current) },
      GFX.hasFont(current) ? `${current} (Adobe Fonts)` : `${current} (not added: stand-in)`));
    // Only fonts this workspace has (a recent one from elsewhere would be a stand-in here).
    const recent = recentFonts().filter(f => all.includes(f)).slice(0, 8);
    if (recent.length) out.push(h("optgroup", { label: "Recent" }, recent.map(f => h("option", { value: f, selected: sel(f) }, nameOf(f)))));
    out.push(h("optgroup", { label: "Built in" }, GFX.builtinFonts.map(f => h("option", { value: f, selected: sel(f) }, f))));
    if (assetFonts.length) out.push(h("optgroup", { label: "Added fonts" }, [...new Set(assetFonts)].sort().map(f => h("option", { value: f, selected: sel(f) }, f))));
    if (adobe.length) out.push(h("optgroup", { label: "Adobe Fonts" }, adobe.slice().sort((a, b) => a.postscript.localeCompare(b.postscript)).map(f =>
      h("option", { value: f.postscript, selected: sel(f.postscript),
        title: f.adobe === "pc" ? (f.kit ? "On this PC (Creative Cloud) and in the web project" : "On this PC through Creative Cloud: other PCs need it too, or add it to the web project")
          : "From the Adobe Fonts web project (any PC with internet)" },
        `${f.family} ${f.style}`.trim() + (f.adobe === "pc" && !f.kit ? " · this PC" : "")))));
    return out;
  }
  function assetSelect(kind, value, onChange) {
    const kinds = kind === "video" ? ["video"] : [kind];
    const list = App.assets.filter(a => kinds.includes(a.kind));
    // Pictures and the loop can follow the global configuration.
    const linked = kind === "image" ? [["{{Global!Left logo}}", "Left team's logo"], ["{{Global!Right logo}}", "Right team's logo"],
      ["{{Global!Tournament logo}}", "Tournament logo"], ["{{Sponsors}}", "Sponsors (in turn)"]]
      : kind === "video" ? [["{{Global!BG loop}}", "Background loop"]] : [];
    const known = list.some(a => a.path === value) || linked.some(([v]) => v === value);
    const sel = h("select", { onchange: e => onChange(e.target.value) },
      h("option", { value: "" }, "(none)"),
      linked.length ? h("optgroup", { label: "Global configuration" }, linked.map(([v, t]) => h("option", { value: v, selected: v === value }, t))) : null,
      h("optgroup", { label: "Files" }, list.map(a => h("option", { value: a.path, selected: a.path === value }, a.path.replace(/^assets\//, "")))),
      value && !known ? h("option", { value, selected: true }, value + " (missing)") : null);
    const file = h("input", { type: "file", hidden: true, accept: kind === "image" ? "image/*" : kind === "video" ? "video/*,.mov,.webm,.mxf,.zip,.aep,.aepx" : ".json,.lottie,.zip",
      onchange: async e => {
        const f = e.target.files[0];
        e.target.value = "";
        if (!f) return;
        let r = await upload(f);
        // (converted or rendered in the background: picked once it's ready)
        if (r && r.job && !(r.assets && r.assets[0])) r = await waitJob(r.job);
        const rel = r && r.assets && (r.assets.find(p => kind === "lottie" ? /\.json$/i.test(p) : kind === "video" ? /\.(webm|mp4|m4v)$/i.test(p) : true) || r.assets[0]);
        if (rel) onChange(rel);
      } });
    return h("div", { class: "pick" }, sel, h("button", { class: "small", title: "Add a file", onclick: () => file.click() }, "+"), file);
  }

  // An input bound to a layer property.
  function bind(l, key, kind, extra) {
    extra = extra || {};
    const set = v => { snapshot(); l[key] = v; changed({ keepList: key !== "name" && key !== "field" }); };
    let input;
    if (kind === "number") {
      input = h("input", { type: "number", step: extra.step || 1, min: extra.min, max: extra.max, value: l[key] ?? "", "data-k": key,
        onchange: e => set(e.target.value === "" ? 0 : +e.target.value) });
    } else if (kind === "color") {
      input = h("div", { class: "row-gap" },
        h("input", { type: "color", value: /^#[0-9a-f]{6}$/i.test(l[key]) ? l[key] : "#ffffff", oninput: e => { l[key] = e.target.value; e.target.nextSibling.value = e.target.value; changed({ keepList: true }); }, onchange: () => {} }),
        h("input", { value: l[key] || "", "data-k": key, onchange: e => set(e.target.value) }));
    } else if (kind === "check") {
      input = h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: !!l[key], onchange: e => set(e.target.checked) }), extra.label);
    } else if (kind === "select") {
      input = h("select", { "data-k": key, onchange: e => set(extra.num ? +e.target.value : e.target.value) },
        extra.options.map(o => Array.isArray(o) ? h("option", { value: o[0], selected: String(l[key]) === String(o[0]) }, o[1]) : h("option", { value: o, selected: l[key] === o }, o)));
    } else if (kind === "textarea") {
      input = h("textarea", { "data-k": key, rows: 3, oninput: e => { l[key] = e.target.value; pending = true; saveSoon(); redraw(); }, onchange: () => { snapshot(); changed({ keepList: true }); } });
      input.value = l[key] || "";
    } else {
      input = h("input", { value: l[key] ?? "", "data-k": key, placeholder: extra.placeholder || "", onchange: e => set(e.target.value) });
    }
    return extra.label && kind !== "check" ? h("label", {}, extra.label, input) : kind === "check" ? input : input;
  }
  const lab = (text, ...kids) => h("label", {}, text, ...kids);

  function syncPropsGeometry() {
    const l = layerById(selected);
    if (!l) return;
    for (const k of ["x", "y", "w", "h"]) {
      const input = props.querySelector(`input[data-k="${k}"]`);
      if (input && document.activeElement !== input) input.value = Math.round(l[k]);
    }
  }

  function renderProps() {
    if (!comp) { props.replaceChildren(h("div", { class: "empty" }, "Make a graphic with + New, or Import a Photoshop file.")); return; }
    if (multi.size > 1) return renderMulti();
    const l = layerById(selected);
    if (!l) return renderCompProps();
    const sections = [];
    sections.push(h("div", { class: "sect" },
      h("h3", {}, ({ text: "Text", rect: "Shape", image: "Picture", video: "Video", lottie: "Lottie animation", bracket: "Bracket", web: "Web page" }[l.type] || "Layer") + " layer"),
      lab("Name", bind(l, "name", "text")),
      h("label", { title: "Give it a name to change it from Control (and from data)" }, "Field (changed from Control)",
        h("div", { class: "row-gap" },
          h("input", { value: l.field || "", placeholder: "(fixed: not a field)", "data-k": "field",
            onchange: e => { snapshot(); l.field = e.target.value.trim() ? uniqueFieldExcept(e.target.value.trim(), l) : ""; changed({ props: true }); } }),
          !l.field ? h("button", { class: "small", onclick: () => { snapshot(); l.field = uniqueField(l.name); changed({ props: true }); } }, "Make field") : null)),
      h("div", { class: "grid4" }, lab("X", bind(l, "x", "number")), lab("Y", bind(l, "y", "number")),
        lab("W", bind(l, "w", "number", { min: 1 })), lab("H", bind(l, "h", "number", { min: 1 }))),
      h("div", { class: "grid4" },
        lab("Opacity", bind(l, "opacity", "number", { step: 0.05, min: 0, max: 1 })),
        lab("Rotate °", bind(l, "rotation", "number")),
        h("label", { title: "Keeps turning while it's on: turns a second (0.1 = once every 10 s), minus for anticlockwise. 0 = still" }, "Spin",
          bind(l, "spin", "number", { step: 0.05 })),
        lab("Blend", bind(l, "blend", "select", { options: ["normal", "multiply", "screen", "overlay", "darken", "lighten", "color-dodge", "color-burn", "hard-light", "soft-light", "difference", "plus-lighter"] }))),
      h("div", { class: "row-gap" },
        h("button", { class: "small", onclick: () => duplicateLayer(l) }, "Duplicate"),
        h("button", { class: "small", title: "Full screen", onclick: () => { snapshot(); Object.assign(l, { x: 0, y: 0, w: GFX.W, h: GFX.H }); changed({ props: true }); } }, "Fill"),
        h("button", { class: "small", title: "Centre on the canvas", onclick: () => { snapshot(); l.x = Math.round((GFX.W - l.w) / 2); l.y = Math.round((GFX.H - l.h) / 2); changed({ props: true }); } }, "Centre"),
        h("div", { class: "spacer" }),
        h("button", { class: "small danger", onclick: () => removeLayers([l]) }, "Delete")),
      h("label", { class: "toggle", title: "A locked layer can't be picked, moved, resized or deleted on the canvas" },
        h("input", { type: "checkbox", checked: !!l.locked, onchange: e => setLocked([l], e.target.checked) }), "Locked"),
      l.group ? h("div", { class: "row-gap in-group" },
        h("span", { class: "muted small" }, `In the group "${groupNameOf(l.group)}"`),
        h("div", { class: "spacer" }),
        h("button", { class: "small", onclick: () => pickLayers(membersOf(l.group), l.id) }, "Pick the group"),
        h("button", { class: "small", title: "Ctrl+Shift+G", onclick: ungroupLayers }, "Take out")) : null));
    sections.push(alignSection([l]));

    if (l.type === "text") {
      const missing = !GFX.hasFont(l.font);
      sections.push(h("div", { class: "sect" }, h("h3", {}, "Text"),
        lab("Text", bind(l, "text", "textarea")),
        h("div", { class: "muted small" }, "Use data: {{Source!B2}} · clock: {{time}} · {{countdown:19:30}}"),
        lab("Font", h("select", { onchange: e => setFont(l, e.target.value) }, fontOptions(l.font))),
        missing ? h("div", { class: "warnline" }, `"${l.font}" isn't added: a similar font stands in. Add the font file in Assets.`) : null,
        h("div", { class: "grid3" }, lab("Size", bind(l, "size", "number", { min: 1 })), bind(l, "color", "color", { label: "Colour" }),
          lab("Weight", bind(l, "weight", "select", { num: true, options: [[300, "Light"], [400, "Regular"], [500, "Medium"], [600, "Semibold"], [700, "Bold"], [800, "Extra bold"], [900, "Black"]] }))),
        lab("Colour set in Control", bind(l, "color", "select", { options: [
          ...(["{{Global!Text primary}}", "{{Global!Text secondary}}"].includes(l.color) ? [] : [[l.color || "", "(its own colour)"]]),
          ["{{Global!Text primary}}", "Primary text colour"], ["{{Global!Text secondary}}", "Secondary text colour"]] })),
        h("div", { class: "grid3" },
          lab("Align", bind(l, "align", "select", { options: [["left", "Left"], ["center", "Centre"], ["right", "Right"]] })),
          lab("Vertical", bind(l, "valign", "select", { options: [["top", "Top"], ["middle", "Middle"], ["bottom", "Bottom"]] })),
          lab("Too long", bind(l, "fit", "select", { options: [["shrink", "Shrink"], ["squeeze", "Squeeze"], ["none", "Overflow"]] }))),
        h("div", { class: "grid3" },
          lab("Tracking", bind(l, "tracking", "number", { step: 10 })),
          lab("Line height", bind(l, "lineHeight", "number", { step: 0.05, min: 0.5 })),
          lab("Scroll px/s", bind(l, "scroll", "number", { min: 0, step: 10 }))),
        h("div", { class: "row-gap" }, bind(l, "caps", "check", { label: "ALL CAPS" }), bind(l, "italic", "check", { label: "Italic" }),
          bind(l, "shadow", "check", { label: "Shadow" })),
        l.scroll > 0 ? h("div", { class: "grid2" }, bind(l, "divider", "color", { label: "Divider between lines" }),
          lab("Divider width", bind(l, "dividerWidth", "number", { min: 0, step: 1 }))) : null,
        lab("Picture before the text", bind(l, "icon", "text", { placeholder: "e.g. {{Roster!Player 1 flag}}" })),
        l.show ? h("div", { class: "muted small" }, `Shown only while ${l.show} has something in it.`) : null));
    } else if (l.type === "bracket") {
      sections.push(h("div", { class: "sect" }, h("h3", {}, "Bracket"),
        h("p", { class: "muted small" }, "The knockout bracket from Global > Tournament: 8 or 16 teams, single or double elimination (Control has the choice), drawn to fit this box."),
        lab("Font", h("select", { onchange: e => setFont(l, e.target.value) }, fontOptions(l.font))),
        h("div", { class: "grid2" }, bind(l, "color", "color", { label: "Text" }), bind(l, "gold", "color", { label: "First round" })),
        h("div", { class: "grid2" }, bind(l, "dark", "color", { label: "Later rounds" }), bind(l, "line", "color", { label: "Lines" })),
        bind(l, "champ", "color", { label: "Champion's frame" })));
    } else if (l.type === "web") {
      sections.push(h("div", { class: "sect" }, h("h3", {}, "Page"),
        lab("Address", bind(l, "src", "text", { placeholder: "{{Rocket League HUD!target_cam}}" })),
        h("p", { class: "muted small" }, "A live web page in this box: a game HUD's page, or the spectated player's cam."),
        l.design != null ? h("button", { class: "small", onclick: () => { snapshot(); l.type = /^#|^rgb|^\{\{Global!.*colou?r/i.test(l.design) ? "rect" : "image";
          if (l.type === "rect") { l.fill = l.design; delete l.src; } else l.src = l.design; delete l.design; delete l.when; changed({ props: true }); } }, "Back to the design's picture") : null));
    } else if (l.type === "rect") {
      sections.push(h("div", { class: "sect" }, h("h3", {}, "Shape"),
        h("div", { class: "grid2" }, bind(l, "fill", "color", { label: "Fill" }), lab("Corner radius", bind(l, "radius", "number", { min: 0 }))),
        h("div", { class: "grid2" }, bind(l, "stroke", "color", { label: "Border" }), lab("Border width", bind(l, "strokeWidth", "number", { min: 0 })))));
    } else {
      sections.push(h("div", { class: "sect" }, h("h3", {}, "Source"),
        lab("File", assetSelect(l.type, l.src, v => { snapshot(); l.src = v; changed({ props: true }); })),
        l.type === "image" && l.src ? h("button", { class: "small", style: { marginTop: "6px" }, onclick: () => naturalSize(l) }, "Actual size") : null,
        l.type === "image" ? lab("Sits at", bind(l, "position", "select", { options: [["", "Middle"], ["bottom", "Bottom"], ["top", "Top"], ["left", "Left"], ["right", "Right"]] })) : null,
        lab("Fit", bind(l, "fit", "select", { options: [["contain", "Fit inside"], ["cover", "Fill and crop"], ["fill", "Stretch"]] })),
        /\{\{\s*sponsors\s*\}\}/i.test(l.src || "") ? bind(l, "timer", "check", { label: "Show a bar with the time it has left" }) : null,
        l.type === "image" ? h("label", { class: "toggle", title: "The picture in the background loop's colour (Global configuration): it changes with it" },
          h("input", { type: "checkbox", checked: l.tint === "{{Global!BG loop colour}}", onchange: e => {
            snapshot(); if (e.target.checked) l.tint = "{{Global!BG loop colour}}"; else delete l.tint; changed({ props: true }); } }),
          "Take the background loop's colour") : null,
        l.type === "image" && l.tint && l.tint !== "{{Global!BG loop colour}}" ? bind(l, "tint", "text", { label: "Colour", placeholder: "(none)" }) : null,
        l.type === "image" && /\{\{/.test(l.src || "") ? lab("When Global has none", assetSelect("image", l.placeholder || "", v => { snapshot(); l.placeholder = v; changed({ props: true }); })) : null,
        l.type === "video" ? h("div", { class: "row-gap" },
          bind(l, "tint", "text", { label: "Tint colour (e.g. {{Global!BG loop colour}})", placeholder: "(none)" })) : null,
        l.type !== "image" ? h("div", { class: "row-gap" }, bind(l, "loop", "check", { label: "Loop" }),
          l.type === "video" ? bind(l, "audio", "check", { label: "Sound (Program output)" }) : null) : null));
    }
    sections.push(liveSection([l]));
    sections.push(animSection(l));
    props.replaceChildren(...sections);
  }

  // --- live data: what a layer shows, fills by, and when it shows ------------------
  // (the property a layer's content is in)
  const contentKey = l => l.type === "text" ? "text" : l.type === "rect" ? "fill" : ["image", "web", "video"].includes(l.type) ? "src" : null;
  function setShows(l, v) {
    const key = contentKey(l);
    if (!key) return;
    snapshot();
    // (the design's own text or picture is kept, to go back to)
    if (v && !LiveData.isToken(l[key]) && l.design == null) l.design = l[key] ?? "";
    if (v) l[key] = v;
    else if (l.design != null) { l[key] = l.design; delete l.design; }
    changed({ props: true });
  }
  function liveSection(layers) {
    const one = layers.length === 1 ? layers[0] : null;
    const each = fn => { snapshot(); layers.forEach(fn); changed({ props: true }); };
    const kids = [h("h3", {}, "Live data")];
    if (!one) kids.push(h("p", { class: "muted small" }, `${layers.length} layers: their "Show when" and "Fill by" are set together.`));
    const key = one && contentKey(one);
    if (key) {
      const v = LiveData.isToken(one[key]) ? one[key].trim() : "";
      kids.push(lab(one.type === "text" ? "Text shows" : one.type === "rect" ? "Colour from" : one.type === "web" ? "Page from" : "Picture from",
        LiveData.select(v, val => setShows(one, val), "(as designed)")));
    }
    // Fill by: a bar (or the dial's ring) cut to how full the value is.
    const m = one ? one.meter : null;
    kids.push(lab("Fill by (a boost bar or dial)", LiveData.select(m ? m.value : "", val =>
      each(l => { if (!val) delete l.meter; else l.meter = Object.assign({ max: "100", dir: "right" }, l.meter, { value: val }); }), "(always full)")));
    if (m) {
      const setM = (k, val) => { snapshot(); one.meter[k] = val; changed({ props: true }); };
      kids.push(h("div", { class: "grid3" },
        lab("Full at", h("input", { value: m.max ?? "100", onchange: e => setM("max", e.target.value) })),
        lab("Fills", h("select", { onchange: e => setM("dir", e.target.value) },
          [["right", "Left to right"], ["left", "Right to left"], ["up", "Bottom up"], ["down", "Top down"], ["ring", "Round (a dial)"]]
            .map(([o, t]) => h("option", { value: o, selected: (m.dir || "right") === o }, t)))),
        m.dir === "ring" ? lab("Starts at °", h("input", { type: "number", step: 5, value: m.start || 0, onchange: e => setM("start", +e.target.value) })) : null),
        m.dir === "ring" ? lab("Goes round °", h("input", { type: "number", step: 5, value: m.sweep || 360, onchange: e => setM("sweep", +e.target.value) })) : null,
        m.dir === "ring" ? h("p", { class: "muted small" }, "0° is the top, going clockwise. A dial that starts bottom-left and ends bottom-right: start 225°, round 270°.") : null);
    }
    // Show when: all of these true (else hidden, with its Out animation).
    const rules = one ? (Array.isArray(one.when) ? one.when : one.when ? [one.when] : []) : [];
    const setRules = list => each(l => { if (list.length) l.when = JSON.parse(JSON.stringify(list)); else delete l.when; });
    kids.push(h("label", {}, "Show when"));
    rules.forEach((r, i) => {
      const upd = (k, val) => { const list = rules.map(x => Object.assign({}, x)); list[i][k] = val; setRules(list); };
      kids.push(h("div", { class: "rule" },
        LiveData.select(r.value, val => { const list = rules.map(x => Object.assign({}, x)); if (val) list[i].value = val; else list.splice(i, 1); setRules(list); }, "(remove)"),
        h("div", { class: "row-gap" },
          h("select", { onchange: e => upd("op", e.target.value) }, GFX.RULE_OPS.map(([o, t]) => h("option", { value: o, selected: (r.op || "has") === o }, t))),
          ["has", "empty"].includes(r.op || "has") ? null : h("input", { value: r.to ?? "", placeholder: "value", onchange: e => upd("to", e.target.value) }))));
    });
    kids.push(h("div", { class: "row-gap" },
      LiveData.select("", val => { if (val) setRules([...rules, { value: val, op: "has" }]); }, rules.length ? "+ and also…" : "(always shown) + add a rule…")));
    if (rules.length || !one) {
      kids.push(lab("Otherwise", h("select", { onchange: e => each(l => { if (e.target.value) l.otherwise = e.target.value; else delete l.otherwise; }) },
        [["", "Hide (plays its Out animation, then In when it's back)"], ["dim", "Fade it (an empty series box)"]]
          .map(([o, t]) => h("option", { value: o, selected: ((one && one.otherwise) || "") === o }, t)))));
      if (!one) kids.push(h("button", { class: "small", onclick: () => each(l => { delete l.when; delete l.otherwise; }) }, "Clear their rules"));
    }
    if (rules.length) kids.push(h("p", { class: "muted small" }, "Composer shows it either way; on air it follows the rule, playing its In and Out animations. A box that rises in and sinks away: In and Out both slide-up."));
    if (one && ["image", "rect", "video"].includes(one.type)) kids.push(h("button", { class: "small", style: { marginTop: "6px" },
      title: "The Rocket League HUD's player cam (Player Cam or a VDO.Ninja link) for whoever is spectated, in this box",
      onclick: () => { snapshot(); makeCam(one); changed({ props: true }); } }, "Make this the spectated player's cam"));
    return h("div", { class: "sect" }, ...kids);
  }
  // A box that shows the spectated player's cam, and slides away when they have none.
  function makeCam(l) {
    l.design = l.design ?? (l.src || l.fill || "");
    l.type = "web";
    l.src = `{{${LiveData.RL}!target_cam}}`;
    delete l.fill;
    l.when = [{ value: `{{${LiveData.RL}!target_has_cam}}`, op: "has" }];
    l.anim = Object.assign({}, l.anim, { in: { type: "slide-up", dur: 400, delay: 0 }, out: { type: "slide-up", dur: 350, delay: 0 } });
  }
  function renderMulti() {
    const layers = comp.layers.filter(l => multi.has(l.id));
    const setAnim = (dir, type) => { if (!type) return; snapshot(); layers.forEach(l => { l.anim = l.anim || {}; l.anim[dir] = Object.assign({ dur: 300, delay: 0 }, l.anim[dir], { type }); }); changed({ props: true }); };
    // (one group, picked whole)
    const g = layers[0].group && layers.every(l => l.group === layers[0].group) && membersOf(layers[0].group).length === layers.length ? layers[0].group : null;
    const grouped = layers.some(l => l.group);
    props.replaceChildren(
      g ? h("div", { class: "sect" }, h("h3", {}, "Group"),
        lab("Name", h("input", { value: groupNameOf(g), onchange: e => {
          if (!e.target.value.trim()) return;
          snapshot(); membersOf(g).forEach(m => { m.groupName = e.target.value.trim().slice(0, 80); }); changed({ props: true }); } })),
        h("p", { class: "muted small" }, `${layers.length} layers: ${layers.map(l => l.name).join(", ")}`),
        h("p", { class: "muted small" }, "Picked, moved, lined up, hidden and locked together. Alt + click on the canvas (or a click on its row in Layers) picks one layer inside."),
        h("div", { class: "row-gap" },
          h("button", { class: "small", title: "Ctrl+Shift+G", onclick: ungroupLayers }, "Ungroup"),
          h("button", { class: "small", onclick: () => setLocked(layers, !layers.every(l => l.locked)) }, layers.every(l => l.locked) ? "🔓 Unlock group" : "🔒 Lock group"),
          h("div", { class: "spacer" }),
          h("button", { class: "small danger", onclick: () => removeLayers(layers) }, "Delete")))
      : h("div", { class: "sect" }, h("h3", {}, `${layers.length} layers`),
        h("p", { class: "muted small" }, layers.map(l => l.name).join(", ")),
        h("p", { class: "muted small" }, "Ctrl + click in the list picks one more (or fewer). Shift + click picks every layer between the last one clicked and this one."),
        h("div", { class: "row-gap" },
          h("button", { class: "small", title: "Ctrl+G", onclick: groupLayers }, "▣ Group"),
          grouped ? h("button", { class: "small", title: "Ctrl+Shift+G: takes them out of their groups", onclick: ungroupLayers }, "Ungroup") : null,
          h("button", { class: "small", onclick: () => setLocked(layers, true) }, "🔒 Lock all"),
          h("button", { class: "small", onclick: () => setLocked(layers, false) }, "🔓 Unlock all"))),
      alignSection(layers),
      liveSection(layers),
      h("div", { class: "sect" }, h("h3", {}, "Animation"),
        h("div", { class: "grid2" },
          lab("All in", h("select", { onchange: e => setAnim("in", e.target.value) }, h("option", { value: "" }, "(as they are)"), GFX.animTypes.map(t => h("option", { value: t }, t)))),
          lab("All out", h("select", { onchange: e => setAnim("out", e.target.value) }, h("option", { value: "" }, "(as they are)"), GFX.animTypes.map(t => h("option", { value: t }, t)))))));
  }
  // --- align and distribute -----------------------------------------------
  // Lines up the picked layers with each other (their left edges, middles,
  // right edges, tops, middles, bottoms), or one layer with the canvas.
  // Distribute evens out the gaps between three or more (the outer two stay),
  // and Tidy up sets them in a neat grid with the same gap. Locked layers
  // don't move, but the others line up with them.
  const ALIGN_ICON = {
    left: '<path d="M3 2v16"/><rect x="6" y="5" width="11" height="3.5" rx="1"/><rect x="6" y="11.5" width="7" height="3.5" rx="1"/>',
    hcenter: '<path d="M10 2v16"/><rect x="4" y="5" width="12" height="3.5" rx="1"/><rect x="6" y="11.5" width="8" height="3.5" rx="1"/>',
    right: '<path d="M17 2v16"/><rect x="3" y="5" width="11" height="3.5" rx="1"/><rect x="7" y="11.5" width="7" height="3.5" rx="1"/>',
    top: '<path d="M2 3h16"/><rect x="5" y="6" width="3.5" height="11" rx="1"/><rect x="11.5" y="6" width="3.5" height="7" rx="1"/>',
    vcenter: '<path d="M2 10h16"/><rect x="5" y="4" width="3.5" height="12" rx="1"/><rect x="11.5" y="6" width="3.5" height="8" rx="1"/>',
    bottom: '<path d="M2 17h16"/><rect x="5" y="3" width="3.5" height="11" rx="1"/><rect x="11.5" y="7" width="3.5" height="7" rx="1"/>',
    hspace: '<path d="M2 3v14M18 3v14"/><rect x="8" y="5" width="4" height="10" rx="1"/>',
    vspace: '<path d="M3 2h14M3 18h14"/><rect x="5" y="8" width="10" height="4" rx="1"/>',
    tidy: '<rect x="3" y="3" width="5.5" height="5.5" rx="1"/><rect x="11.5" y="3" width="5.5" height="5.5" rx="1"/><rect x="3" y="11.5" width="5.5" height="5.5" rx="1"/><rect x="11.5" y="11.5" width="5.5" height="5.5" rx="1"/>',
  };
  const ALIGN_TIP = {
    left: "Align left (Alt+A)", hcenter: "Align horizontal centres (Alt+H)", right: "Align right (Alt+D)",
    top: "Align top (Alt+W)", vcenter: "Align vertical centres (Alt+V)", bottom: "Align bottom (Alt+S)",
    hspace: "Distribute horizontal spacing (Alt+Shift+H)", vspace: "Distribute vertical spacing (Alt+Shift+V)",
    tidy: "Tidy up: a neat grid with even gaps (Ctrl+Alt+Shift+T)",
  };
  const alignIcon = kind => {
    const s = h("span", { class: "al-ic" });
    s.innerHTML = `<svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">${ALIGN_ICON[kind]}</svg>`;
    return s;
  };
  // A group picked whole lines up as one box (its layers keep their places
  // in it); its locked layers stay put.
  function units(list) {
    const out = [], seen = new Set();
    for (const l of list) {
      const g = l.group && membersOf(l.group).every(m => list.includes(m)) ? l.group : null;
      if (g && seen.has(g)) continue;
      if (!g) { out.push(l); continue; }
      seen.add(g);
      const members = membersOf(g);
      const b = boundsOf(members);
      out.push({ x: b.x, y: b.y, w: b.w, h: b.h, members, locked: members.every(m => m.locked) });
    }
    return out;
  }
  function arrange(kind) {
    if (!comp) return;
    const pickedNow = picked();
    if (!pickedNow.length) return toast("Pick the layers to line up first (Ctrl or Shift + click)", true);
    const layers = units(pickedNow);
    const free = layers.filter(l => !l.locked);
    if (!free.length) return toast(layers.length > 1 ? "Those layers are locked: unlock them (🔒 in Layers) to line them up" : "That layer is locked: unlock it (🔒 in Layers) to move it", true);
    const spread = kind === "hspace" || kind === "vspace" || kind === "tidy";
    if (spread && layers.length < (kind === "tidy" ? 2 : 3)) return toast(kind === "tidy" ? "Pick two or more layers to tidy up" : "Pick three or more layers to even out the gaps", true);
    // With one layer, line it up with the canvas; with more, with all of them.
    const box = layers.length === 1 ? { x: 0, y: 0, r: GFX.W, b: GFX.H } : {
      x: Math.min(...layers.map(l => l.x)), y: Math.min(...layers.map(l => l.y)),
      r: Math.max(...layers.map(l => l.x + l.w)), b: Math.max(...layers.map(l => l.y + l.h)) };
    const before = JSON.stringify(comp);
    const put = (l, x, y) => {
      if (l.locked) return;
      if (!l.members) { if (x != null) l.x = Math.round(x); if (y != null) l.y = Math.round(y); return; }
      const dx = x != null ? Math.round(x - l.x) : 0, dy = y != null ? Math.round(y - l.y) : 0;
      l.members.forEach(m => { if (!m.locked) { m.x += dx; m.y += dy; } });
      l.x += dx; l.y += dy;
    };
    if (kind === "left") layers.forEach(l => put(l, box.x));
    else if (kind === "hcenter") layers.forEach(l => put(l, (box.x + box.r) / 2 - l.w / 2));
    else if (kind === "right") layers.forEach(l => put(l, box.r - l.w));
    else if (kind === "top") layers.forEach(l => put(l, null, box.y));
    else if (kind === "vcenter") layers.forEach(l => put(l, null, (box.y + box.b) / 2 - l.h / 2));
    else if (kind === "bottom") layers.forEach(l => put(l, null, box.b - l.h));
    else if (kind === "hspace" || kind === "vspace") {
      // Even gaps between the layers; the first and last stay where they are.
      const [p, s] = kind === "hspace" ? ["x", "w"] : ["y", "h"];
      const order = [...layers].sort((a, b) => (a[p] + a[s] / 2) - (b[p] + b[s] / 2));
      const first = order[0], last = order[order.length - 1];
      const room = (last[p] + last[s]) - first[p] - order.reduce((t, l) => t + l[s], 0);
      const gap = room / (order.length - 1);
      let at = first[p] + first[s] + gap;
      for (const l of order.slice(1, -1)) { if (p === "x") put(l, at); else put(l, null, at); at += l[s] + gap; }
    } else if (kind === "tidy") tidyUp(layers, box, put);
    if (JSON.stringify(comp) === before) return toast("They're already lined up");
    undo.push(before);
    if (undo.length > 100) undo.shift();
    redo.length = 0;
    const kept = pickedNow.filter(l => l.locked).length;
    if (kept) toast(`${kept} locked layer(s) stayed put`);
    changed({ keepList: true });
    drawSelection();
  }
  // Tidy up: sorts the layers into rows (by where they are now) and columns,
  // and sets them out from the top left with the same gap everywhere (the
  // gap they have now, on average).
  function tidyUp(layers, box, put) {
    const rows = [];
    for (const l of [...layers].sort((a, b) => (a.y + a.h / 2) - (b.y + b.h / 2))) {
      const row = rows[rows.length - 1];
      const mid = l.y + l.h / 2;
      if (row && Math.abs(mid - row.mid) < Math.max(row.h, l.h) / 2) { row.items.push(l); row.h = Math.max(row.h, l.h); }
      else rows.push({ mid, h: l.h, items: [l] });
    }
    rows.forEach(r => r.items.sort((a, b) => a.x - b.x));
    const cols = Math.max(...rows.map(r => r.items.length));
    const colW = [...Array(cols)].map((_, c) => Math.max(0, ...rows.map(r => r.items[c] ? r.items[c].w : 0)));
    const rowH = rows.map(r => Math.max(...r.items.map(l => l.h)));
    // The gap they have now: the space between neighbours in a row (or
    // between rows when it's one column), never less than 0.
    const gaps = [];
    rows.forEach(r => r.items.slice(1).forEach((l, i) => gaps.push(l.x - (r.items[i].x + r.items[i].w))));
    if (!gaps.length) rows.slice(1).forEach((r, i) => gaps.push(Math.min(...r.items.map(l => l.y)) - Math.max(...rows[i].items.map(l => l.y + l.h))));
    const avg = gaps.reduce((t, g) => t + g, 0) / Math.max(1, gaps.length);
    const gap = avg < 0 ? 20 : Math.round(avg);   // piled on top of each other: 20 px apart
    let y = box.y;
    rows.forEach((r, ri) => {
      let x = box.x;
      r.items.forEach((l, c) => { put(l, x, y); x += colW[c] + gap; });
      y += rowH[ri] + gap;
    });
  }
  function alignSection(layers) {
    const one = units(layers).length === 1;
    const btn = kind => h("button", { class: "al-btn", title: ALIGN_TIP[kind] + (one && !/space|tidy/.test(kind) ? ": to the canvas" : ""),
      "aria-label": ALIGN_TIP[kind], onclick: () => arrange(kind) }, alignIcon(kind));
    return h("div", { class: "sect align-sect" }, h("h3", {}, "Alignment"),
      h("div", { class: "al-row" },
        h("div", { class: "al-group" }, btn("left"), btn("hcenter"), btn("right")),
        h("div", { class: "al-group" }, btn("top"), btn("vcenter"), btn("bottom"))),
      one ? h("p", { class: "muted small" }, layers.length > 1 ? "The group lines up with the canvas, as one. Ctrl or Shift + click picks more to line them up with each other."
        : "One layer lines up with the canvas. Ctrl or Shift + click picks more to line them up with each other.")
        : h("div", { class: "al-row" },
          h("div", { class: "al-group" }, btn("hspace"), btn("vspace"), btn("tidy"))));
  }
  addEventListener("keydown", e => {
    if (App.tab !== "composer" || !comp || !e.altKey || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const mod = e.ctrlKey || e.metaKey;
    const key = { KeyA: "left", KeyH: "hcenter", KeyD: "right", KeyW: "top", KeyV: "vcenter", KeyS: "bottom" }[e.code];
    let kind = null;
    if (mod && e.shiftKey && e.code === "KeyT") kind = "tidy";
    else if (!mod && e.shiftKey && e.code === "KeyH") kind = "hspace";
    else if (!mod && e.shiftKey && e.code === "KeyV") kind = "vspace";
    else if (!mod && !e.shiftKey && key) kind = key;
    if (!kind || !picked().length) return;
    e.preventDefault();
    arrange(kind);
  });
  function uniqueFieldExcept(name, layer) {
    const taken = new Set(comp.layers.filter(x => x !== layer).map(x => (x.field || "").toLowerCase()));
    let n = 2, out = name;
    while (taken.has(out.toLowerCase())) out = `${name} ${n++}`;
    return out;
  }
  function naturalSize(l) {
    const img = new Image();
    img.onload = () => { snapshot(); l.w = img.naturalWidth; l.h = img.naturalHeight; changed({ props: true }); };
    img.src = "/" + l.src;
  }

  function animSection(l) {
    l.anim = l.anim || {};
    const row = dir => {
      const a = (l.anim[dir] = l.anim[dir] || { type: "fade", dur: 300, delay: 0 });
      const set = (k, v) => { snapshot(); a[k] = v; changed({ keepList: true }); };
      return h("div", { class: "grid3" },
        lab(dir === "in" ? "In" : "Out", h("select", { onchange: e => set("type", e.target.value) },
          GFX.animTypes.map(t => h("option", { value: t, selected: a.type === t }, t)))),
        lab("ms", h("input", { type: "number", min: 0, step: 50, value: a.dur, onchange: e => set("dur", +e.target.value) })),
        lab("Delay ms", h("input", { type: "number", min: 0, step: 50, value: a.delay || 0, onchange: e => set("delay", +e.target.value) })));
    };
    return h("div", { class: "sect" }, h("h3", {}, "Animation"), row("in"), row("out"),
      h("div", { class: "row-gap", style: { marginTop: "8px" } },
        h("button", { class: "small", onclick: () => { if (root) GFX.play(root, "in"); } }, "▶ Play in")));
  }

  function renderCompProps() {
    const fields = App.fields(comp);
    props.replaceChildren(
      h("div", { class: "sect" }, h("h3", {}, "Graphic"),
        lab("Name", h("input", { value: comp.name, onchange: e => { snapshot(); comp.name = e.target.value || "Graphic"; changed({ props: true }); renderComps(); } })),
        lab("Kind", h("select", { onchange: e => { snapshot(); comp.kind = e.target.value; changed(); } },
          [["board", "Full-page board"], ["lower third", "Lower third"], ["overlay", "Overlay (scorebug, ticker…)"]].map(([v, t]) => h("option", { value: v, selected: (comp.kind || "overlay") === v }, t)))),
        h("p", { class: "muted small" }, "On air there's one board and one lower third at a time: taking another replaces it. Overlays stay."),
        lab("Stacking on the output", h("select", { onchange: e => { snapshot(); comp.layer = +e.target.value; changed(); } },
          [[-1, "Behind others"], [0, "Normal"], [1, "In front"], [2, "Always on top"]].map(([v, t]) => h("option", { value: v, selected: (comp.layer || 0) === v }, t)))),
        h("p", { class: "muted small" }, `${comp.layers.length} layers, ${fields.length} fields. Click a layer to change it.`)),
      h("div", { class: "sect" }, h("h3", {}, "Animation"),
        h("p", { class: "muted small" }, "Every layer has its own In and Out animation. Set them all at once:"),
        h("div", { class: "row-gap" },
          h("button", { class: "small", onclick: () => autoAnimate() }, "Auto (one after another)"),
          h("button", { class: "small", onclick: () => allAnim("fade") }, "All fade"),
          h("button", { class: "small", onclick: () => allAnim("none") }, "None"))),
      hudSection(),
      linksSection(),
      h("div", { class: "sect" }, h("h3", {}, "Shortcuts"),
        h("p", { class: "muted small" }, "Drag to move (Shift: straight, Ctrl: no snapping), handles to resize (Shift: keep shape). Arrows nudge (Shift: 10). Ctrl+C / Ctrl+X copy or cut (Ctrl + click picks more, Shift + click picks a range) and Ctrl+V pastes, into this graphic or any other. Ctrl+D duplicates, Delete removes, Ctrl+Z / Ctrl+Shift+Z undo / redo. Alt+click picks the layer underneath. Ctrl or Shift + click on the canvas picks more layers; Alignment lines them up (Alt+A / H / D left, centre, right, Alt+W / V / S top, middle, bottom, Alt+Shift+H / V evens out the gaps, Ctrl+Alt+Shift+T tidies up), one layer lines up with the canvas. 🔒 in Layers locks a layer: it can't be picked, moved or deleted on the canvas (pick it in the list to change it). Ctrl+scroll zooms (Ctrl+0 fits, Ctrl+1 is 100%), scroll or middle-drag or Space+drag moves around while zoomed.")));
  }
  // --- Add to a HUD: this graphic as a game HUD's own overlay -------------------
  let hudGame = "rl";
  try { hudGame = localStorage.getItem("gfx-hud-game") || "rl"; } catch (e) { /* */ }
  function hudSection() {
    const box = h("div", { class: "sect hud-add" }, h("h3", {}, "Add this to a game HUD"),
      h("p", { class: "muted small" }, "Makes this graphic the HUD's overlay: the HUD plays it with its own live data (no delay), cams and all."),
      h("div", { class: "muted small" }, "Looking for the HUDs…"));
    const forComp = compId;
    fetch("/api/hud-looks").then(r => r.json()).then(r => {
      if (compId !== forComp || !box.isConnected) return;
      const huds = r.huds || [];
      const games = Object.fromEntries((App.state.games || []).map(n => [n, n]));
      const pick = huds.find(x => x.game === hudGame) || huds[0];
      const list = h("select", { onchange: e => { hudGame = e.target.value; try { localStorage.setItem("gfx-hud-game", hudGame); } catch (err) { /* */ } renderProps(); } },
        huds.map(x => h("option", { value: x.game, selected: x === pick }, x.name)),
        h("optgroup", { label: "Not yet" }, Object.keys(games).filter(n => !huds.some(x => x.name === n)).map(n => h("option", { disabled: true }, n))));
      const kids = [lab("Game", list)];
      if (pick) {
        const look = pick.look, mine = look && look.comp === compId;
        const n = comp.layers.filter(linked).length;
        kids.push(h("p", { class: "small " + (pick.connected ? "" : "warnline") }, pick.connected
          ? `${pick.hud} is connected (${pick.from}).` + (look ? (pick.took === look.rev ? " It's playing what was sent last." : " It picks up the last one in a few seconds.") : "")
          : `${pick.hud} isn't connected to this engine now. It takes the graphic when it connects (Connect to GFX Engine in the HUD).`));
        if (look) kids.push(h("p", { class: "muted small" }, `${mine ? "This graphic" : `"${look.name}"`} was sent ${new Date(look.at * 1000).toLocaleString()}.`));
        if (!n) kids.push(h("p", { class: "warnline small" }, "None of its layers follow the live data yet: link them below, or pick a layer and use Live data."));
        kids.push(h("button", { class: "primary", onclick: async () => {
          const r2 = await api("/api/hud-look", { comp: compId, game: pick.game });
          if (r2 && r2.look) { toast(`Sent to the ${pick.hud}`); renderProps(); }
        } }, look && mine ? `Send the changes to the ${pick.hud}` : `Make it the ${pick.hud}'s overlay`));
      }
      box.replaceChildren(box.firstChild, box.children[1], ...kids);
    }).catch(() => { if (box.isConnected) box.lastChild.textContent = "Couldn't ask the engine about the HUDs."; });
    return box;
  }
  // Every field of the graphic, with the live data it follows: linking a whole HUD in one place.
  function linksSection() {
    const rows = comp.layers.filter(l => l.field || contentKey(l) && LiveData.isToken(l[contentKey(l)]));
    if (!rows.length) return null;
    return h("div", { class: "sect links" }, h("h3", {}, "Live data links"),
      h("p", { class: "muted small" }, "Each field and what it shows on air. Click a name to find it on the canvas."),
      ...[...rows].reverse().map(l => {
        const key = contentKey(l), v = key && LiveData.isToken(l[key]) ? l[key].trim() : "";
        const was = l.type === "text" ? (l.design ?? l.text) : "";
        return h("div", { class: "link-row" },
          h("a", { href: "#", title: was ? `Designed as "${was}"` : l.name, onclick: e => { e.preventDefault(); selected = l.id; renderLayers(); drawSelection(); } },
            l.name + (was && !v ? ` · "${String(was).slice(0, 14)}"` : "")),
          key ? LiveData.select(v, val => setShows(l, val), "(as designed)") : h("span", { class: "muted small" }, "—"));
      }));
  }

  function allAnim(type) {
    snapshot();
    for (const l of comp.layers) l.anim = { in: { type, dur: 300, delay: 0 }, out: { type: type === "none" ? "none" : "fade", dur: 250, delay: 0 } };
    changed();
  }
  function autoAnimate() {
    snapshot();
    const order = comp.layers.map((l, i) => i).sort((a, b) => Math.floor(comp.layers[a].x / 120) - Math.floor(comp.layers[b].x / 120) || comp.layers[a].y - comp.layers[b].y);
    order.forEach((i, n) => {
      const l = comp.layers[i];
      let type = "fade", delay = 80;
      if (l.w >= GFX.W * 0.9 && l.h >= GFX.H * 0.9) { type = "fade"; delay = 0; }
      else if (l.type === "text") { type = "slide-up"; delay = 150; }
      else if (l.w > l.h * 3) { type = "wipe-right"; delay = 0; }
      else if (l.w < 400 && l.h < 400) type = "scale";
      l.anim = { in: { type, dur: 450, delay: Math.min(700, delay + n * 12) }, out: { type: "fade", dur: 250, delay: 0 } };
    });
    changed();
  }

  App.on((s, what) => {
    renderComps();
    if (what === "assets") { if (selected) renderProps(); return; }
    adopt(false);
  });
  pages.composer = { shown() { fitStage(); adopt(!comp); } };
  window.editGraphic = id => { open(id); showTab("composer"); };
})();
