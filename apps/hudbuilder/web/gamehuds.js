// HUD Builder > Game HUDs: every built-in game HUD (League, VALORANT, CoD,
// Rocket League, Smash, Overwatch, each of their designs and profiles) opened
// as it is, to change in place: move, resize, recolour, other fonts and
// pictures, hide or delete parts, add shapes, text and pictures. Save puts it on air.
// Laid out like GFX Engine's Composer: HUDs and Layers | the canvas | properties.
//
// The HUD runs in the frame as itself (its own data and code), with
// /hudedit.js doing the picking and dragging inside it; this page is the
// panels around it. They talk with postMessage ({hudedit: ...}).
"use strict";

window.GameHuds = (function () {
  let catalog = null;        // /api/game-huds
  let open = null;           // {game, title, port, design: {key, name, path}}
  let info = null;           // the frame's latest state (selection, dirty, fonts)
  let nodes = [], added = [];
  let showHidden = false, filter = "", collapsed = new Set(), testView = "";
  let frameReady = false;

  const frame = () => $("#he-frame");
  const post = m => { const f = frame(); if (f && f.contentWindow) f.contentWindow.postMessage(m, "*"); };
  const send = (type, data) => post(Object.assign({ hudedit: type }, data || {}));
  const hudUrl = path => `http://127.0.0.1:${open.port}${path}`;

  // --- the list -------------------------------------------------------------------
  async function list() {
    const box = $("#gh-list");
    if (!catalog) box.replaceChildren(h("p", { class: "muted" }, "Looking for the game HUDs…"));
    try {
      const embed = window.App && App.state && App.state().embed;
      catalog = await api("/api/game-huds" + (embed ? `?game=${encodeURIComponent(embed.game)}` : ""));
    } catch (e) { box.replaceChildren(h("p", { class: "error" }, e.message)); return; }
    box.replaceChildren(...catalog.games.map(g => h("div", { class: "gh-game" },
      h("div", { class: "gh-head" }, h("h3", {}, g.title),
        h("span", { class: "gh-status " + (g.running ? "on" : "off") }, g.running ? "Running" : "Not running"),
        g.running ? null : h("span", { class: "muted small" }, `Turn ${g.title} on (Settings > Parts, or open it from Games) to edit its HUDs.`)),
      h("div", { class: "gh-cards" }, ...g.designs.map(d => card(g, d))),
      deletedCopies(g))));
  }
  function card(g, d) {
    const c = d.copy;
    const url = `http://localhost:${g.port}${d.path}`;
    return h("div", { class: "gh-card" + (g.running ? "" : " off") + (c ? " copy" : ""), onclick: () => g.running && edit(g, d) },
      h("b", {}, d.name), h("span", { class: "muted small" }, d.what),
      c ? h("span", { class: "gh-url", title: "Its own browser source (click to copy)", onclick: async e => { e.stopPropagation(); toast(await copyText(url) ? "Browser source copied" : url); } }, url) : null,
      h("div", { class: "gh-card-btns", onclick: e => e.stopPropagation() },
        h("button", { class: "small primary", disabled: !g.running, onclick: () => edit(g, d) }, "Edit"),
        c ? h("button", { class: "small ghost", disabled: !g.running, title: "Put this copy's changes on the original HUD (what's on air at its usual address). The original's changes before are kept in its Versions.",
          onclick: () => applyCopy(g, d) }, "Use on original") : null,
        h("span", { class: "grow" }),
        g.running && c ? iconBtn("rename", `Rename "${d.name}"`, () => renameCopy(g, d)) : null,
        g.running ? iconBtn("dup", `Duplicate "${d.name}"`, () => duplicate(g, d)) : null,
        // (built-in HUDs can't be deleted, only their changes undone: copies can)
        g.running && c ? iconBtn("trash", `Delete "${d.name}"`, () => deleteCopy(g, d)) : null));
  }
  function deletedCopies(g) {
    const list = g.deleted || [];
    if (!list.length || !g.running) return null;
    return h("details", { class: "deleted-box" }, h("summary", {}, `Recently deleted copies (${list.length})`),
      h("div", { class: "deleted-list" }, ...list.map(x => h("div", { class: "deleted-row" },
        h("b", {}, x.name), h("span", { class: "muted small" }, `deleted ${new Date(x.deleted * 1000).toLocaleString()}`), h("span", { class: "grow" }),
        h("button", { class: "small", onclick: () => copies(g, { action: "undelete", tid: x.tid }, `${x.name} is back`) }, "Bring back")))));
  }
  async function copies(g, body, done) {
    try { const r = await api("/api/game-huds/copies", Object.assign({ part: g.part }, body)); if (done) toast(done); await list(); return r; } catch (e) { toast(e.message, true); return null; }
  }
  // Duplicate a game HUD: a copy with its own name and its own changes (starting from these), its own browser source.
  async function duplicate(g, d) {
    const name = await askName({ title: `Duplicate "${d.name}"`, label: "Name of the copy", value: `${d.name} copy`, ok: "Duplicate" });
    if (!name) return;
    const base = d.copy ? d.copy.base : d.key, path = d.copy ? d.copy.path : d.path;
    const r = await copies(g, { action: "make", base, path, name, from: d.copy ? d.copy.id : null }, `Made ${name}. Edit it, then add its own browser source to OBS or vMix.`);
    if (r && open && open.game === g.game) {
      const fresh = catalog.games.find(x => x.game === g.game);
      if (fresh) { open.designs = fresh.designs; open.g = fresh; renderDesigns(); }
    }
  }
  async function renameCopy(g, d) {
    const name = await askName({ title: `Rename "${d.name}"`, label: "Name", value: d.name, ok: "Rename" });
    if (name && name !== d.name) await copies(g, { action: "rename", id: d.copy.id, name }, "Renamed");
  }
  async function deleteCopy(g, d) {
    const typed = await confirmDelete({ name: d.name, what: "copy", note: "Only this copy goes: the original HUD isn't touched. Its changes and versions are kept in Recently deleted copies, so you can bring it back." });
    if (typed == null) return;
    if (open && open.design && open.design.key === d.key) open = null;
    await copies(g, { action: "delete", id: d.copy.id, confirm: typed }, `Deleted ${d.name}. Recently deleted copies brings it back.`);
  }
  async function applyCopy(g, d) {
    const of = d.what.replace(/^Copy of /, "");
    if (!confirm(`Put the changes of "${d.name}" on "${of}" (on air now)?\n\nThe changes "${of}" has now are kept in its Versions.`)) return;
    await copies(g, { action: "apply", id: d.copy.id }, `"${of}" now has the changes of ${d.name}`);
  }

  // --- the editor -------------------------------------------------------------------
  // The game's other HUDs, to hop between (like Composer's Graphics list).
  function renderDesigns() {
    const box = $("#he-designs");
    if (!box || !open) return;
    box.replaceChildren(...open.designs.map(d => h("div", { class: "he-design" + (d === open.design ? " on" : ""), title: d.what || "",
      onclick: () => edit(open.g, d) }, h("b", {}, `${open.title} · ${d.name}`), d.what ? h("span", {}, d.what) : null)));
  }

  function edit(g, d) {
    if (open && open.design === d) return;
    if (open && info && info.dirty && !confirm("Open another HUD without saving your changes to this one?")) return;
    open = { game: g.game, title: g.title, port: g.port, design: d, designs: g.designs, g };
    info = null; nodes = []; added = []; frameReady = false; collapsed = new Set(); filter = ""; testView = ""; autoState = false;
    $("#he-title").textContent = d.name; $("#he-title").title = `${g.title} · ${d.name}`;
    $("#he-search").value = "";
    renderDesigns();
    load();
    location.hash = "#/hud-edit";
  }
  function load() {
    frameReady = false; autoState = false;
    const extra = testView.replace(/^[?&]+/, "");
    const path = open.design.path + (open.design.path.includes("?") ? "&" : "?") + "hudedit=1" + (extra ? "&" + extra : "");
    frame().src = hudUrl(path);
    $("#he-status").textContent = "Opening…";
    renderParts(); renderProps(); renderBar();
    setTimeout(() => { if (!frameReady && open) $("#he-status").textContent = "The HUD didn't answer. Is it running?"; }, 8000);
  }

  addEventListener("message", e => {
    const f = frame();
    if (!f || e.source !== f.contentWindow || !e.data || !e.data.hudedit) return;
    const m = e.data;
    if (m.hudedit === "ready") { frameReady = true; fit(); }
    if (m.tree) { nodes = m.tree.nodes || []; added = m.tree.added || []; }
    if (m.hudedit === "tree") { nodes = m.nodes || []; added = m.added || []; renderParts(); return; }
    if (m.hudedit === "design") return;
    if (m.hudedit === "error") {
      toast(m.text, true, 9000);
      if (m.conflict && confirm(`${m.text}\n\nLoad the saved version? (Your changes here will be dropped.)`)) send("reload");
      return;
    }
    if ("selected" in m) info = m;
    if (m.hudedit === "saved") toast(`Saved: ${open.title} · ${open.design.name} is on air with your changes`);
    if (m.hudedit === "loaded") send("tree");
    renderBar();
    if (m.hudedit === "live") { renderBarPos(); return renderPos(); }
    renderParts();
    renderProps();
  });

  // The HUD (1920 x 1080) shrunk to fit.
  function fit() {
    const c = $("#he-canvas"), st = $("#he-stage");
    if (!c || !open) return;
    const s = Math.min((c.clientWidth - 32) / 1920, (c.clientHeight - 32) / 1080);
    if (!(s > 0)) return;
    st.style.transform = `scale(${s})`;
    st.style.left = Math.round((c.clientWidth - 1920 * s) / 2) + "px";
    st.style.top = Math.round((c.clientHeight - 1080 * s) / 2) + "px";
    send("view", { scale: s });
  }
  new ResizeObserver(fit).observe(document.documentElement);

  // What the HUD shows while editing: live, or one of its own states (everything at once, the buy phase, a round win...).
  let autoState = false;
  function renderStates() {
    const box = $("#he-states");
    if (!box) return;
    const list = (info && info.states) || [];
    const cur = (info && info.state) || "";
    if (frameReady && !autoState && list.some(x => x.id === "everything")) { autoState = true; send("state", { id: "everything" }); }
    const chip = (id, label, title) => h("button", { class: "small he-chip" + (cur === id ? " on" : ""), title: title || "", onclick: () => send("state", { id }) }, label);
    if (!list.length) return box.replaceChildren();
    box.replaceChildren(h("span", { class: "muted small" }, "Show:"), chip("", "Live", "As it is on air right now"), ...list.map(x => chip(x.id, x.label, x.help)));
  }
  function replay() {
    const cur = (info && info.state) || "";
    const list = (info && info.states) || [];
    if (!list.length) return send("replay");   // (no states of its own: its animations started again)
    // (somewhere else and back, so its animations play again)
    const other = list.find(x => x.id !== cur && x.id !== "everything" && x.id !== "buy") || list.find(x => x.id !== cur) || { id: "" };
    send("state", { id: other.id });
    setTimeout(() => send("state", { id: cur }), 900);
  }

  function renderBar() {
    renderStates();
    const dirty = !!(info && info.dirty);
    $("#he-save").disabled = !dirty;
    $("#he-discard").disabled = !dirty;
    $("#he-undo").disabled = !(info && info.canUndo);
    $("#he-delete").disabled = !(info && info.selected && !info.selected.deleted);
    renderBarPos();
    $("#he-redo").disabled = !(info && info.canRedo);
    if (frameReady) $("#he-status").textContent = dirty ? "Not saved yet" : "Saved · on air";
    $("#he-status").classList.toggle("warn", dirty);
  }

  // What's picked and where, on the bar (like Composer's "70, 917 · 220×34").
  function renderBarPos() {
    const s = info && info.selected, t = $("#he-pos");
    if (!t) return;
    if (!s) return (t.textContent = "");
    const r = s.added ? { x: s.item.x, y: s.item.y, w: s.item.w, h: s.item.h } : s.rect;
    t.textContent = r ? `${Math.round(r.x)}, ${Math.round(r.y)} · ${Math.round(r.w)}×${Math.round(r.h)}` : "";
  }

  // --- the parts list -------------------------------------------------------------
  const ICON = { text: "T", picture: "🖼", group: "▤", shape: "◆", box: "□" };
  const SHAPE_ICON = { rect: "▭", ellipse: "◯", triangle: "△", line: "╱", slant: "▱", star: "☆", arrow: "➜", chevron: "❯" };
  function renderParts() {
    const box = $("#he-parts");
    if (!box) return;
    const sel = info && info.selected;
    const rows = [];
    const eye = (off, onclick) => h("span", { class: "eye" + (off ? " off" : ""), title: off ? "Hidden on air: click to show it" : "Hide it on air (it stays in its place)", onclick: e => { e.stopPropagation(); onclick(); } }, "👁");
    // Lock: a locked layer can't be picked, moved, resized or deleted on the HUD (pick it here to change it).
    const lock = (on, onclick) => h("span", { class: "lock" + (on ? " on" : ""), title: on ? "Unlock" : "Lock (can't be picked, moved or deleted on the HUD)", onclick: e => { e.stopPropagation(); onclick(); } }, on ? "🔒" : "🔓");
    const q = filter.trim().toLowerCase();
    // Added layers on top (top layer first, as in Composer).
    [...added].reverse().forEach(a => {
      if (q && !a.name.toLowerCase().includes(q)) return;
      rows.push(h("div", { class: "he-ly" + (sel && sel.added === a.added ? " sel" : ""), onclick: () => send("select", { added: a.added }) },
        eye(a.hidden, () => send("toggle-hide", { added: a.added })),
        h("span", { class: "ic" }, a.kind === "shape" ? SHAPE_ICON[a.shape || "rect"] || "▭" : ICON[a.kind] || "□"),
        h("span", { class: "nm", title: a.name }, a.name),
        a.behind ? h("span", { class: "tag ch", title: "Behind the HUD" }, "behind") : null,
        h("span", { class: "tag new", title: "You added it" }, "added"),
        lock(a.locked, () => send("toggle-lock", { added: a.added }))));
    });
    let skipBelow = Infinity;
    for (const n of nodes) {
      if (n.depth > skipBelow) continue;
      skipBelow = Infinity;
      if (!showHidden && !n.shown && !n.edited) { skipBelow = n.depth; continue; }
      if (q && !n.name.toLowerCase().includes(q)) continue;
      const shut = collapsed.has(n.sel);
      if ((shut || n.deleted) && !q) skipBelow = n.depth;
      const on = sel && !sel.added && (sel.sel === n.sel);
      rows.push(h("div", { class: "he-ly" + (on ? " sel" : "") + (n.deleted ? " deleted" : n.shown ? "" : " gone"), style: { paddingLeft: (q ? 6 : 4 + n.depth * 11) + "px" },
        onclick: () => send("select", { sel: n.sel }), title: n.sel },
        n.kids && !q && !n.deleted ? h("span", { class: "he-caret", onclick: e => { e.stopPropagation(); shut ? collapsed.delete(n.sel) : collapsed.add(n.sel); renderParts(); } }, shut ? "▸" : "▾") : h("span", { class: "he-caret" }),
        n.deleted ? null : eye(n.hidden, () => send("toggle-hide", { sel: n.sel })),
        h("span", { class: "ic" }, ICON[n.kind] || "□"),
        h("span", { class: "nm" }, n.name),
        n.deleted ? h("button", { class: "small rst", title: "Put it back", onclick: e => { e.stopPropagation(); send("restore", { sel: n.sel }); } }, "Restore")
          : n.edited ? h("span", { class: "tag ch", title: "Changed" }, "changed") : null,
        n.deleted ? null : lock(n.locked, () => send("toggle-lock", { sel: n.sel }))));
    }
    if (!rows.length) rows.push(h("p", { class: "hint muted" }, frameReady ? "Nothing on screen here. Tick “Show every part”." : "Opening the HUD…"));
    const keep = box.scrollTop;
    box.replaceChildren(...rows);
    box.scrollTop = keep;
  }

  // --- the properties of what's picked ---------------------------------------------------
  const lab = (t, el) => h("label", {}, h("span", { class: "muted small" }, t), el);
  const grid = (...kids) => h("div", { class: "grid2" }, ...kids.filter(Boolean));
  const grid4 = (...kids) => h("div", { class: "grid4" }, ...kids.filter(Boolean));
  const btn = (text, onclick, attrs) => h("button", Object.assign({ class: "small", onclick }, attrs || {}), text);
  const sect = (title, ...kids) => h("div", { class: "sect" }, title ? h("h4", {}, title) : null, ...kids.filter(Boolean));
  const set = props => send("set", { props });
  function numIn(k, value, placeholder, onSet, attrs) {
    return h("input", Object.assign({ type: "number", value: value == null ? "" : value, placeholder: placeholder == null ? "" : placeholder, dataset: { k },
      onchange: e => onSet(e.target.value === "" ? null : +e.target.value) }, attrs || {}));
  }
  function colourIn(k, value, now, onSet) {
    const text = h("input", { value: value || "", placeholder: now ? `${now} (as it is)` : "as it is", dataset: { k: k + "-t" },
      onchange: e => onSet(e.target.value.trim() || null) });
    const pick = h("input", { type: "color", value: /^#[0-9a-f]{6}$/i.test(value || "") ? value : (/^#[0-9a-f]{6}$/i.test(now || "") ? now : "#ffffff"), dataset: { k },
      onchange: e => onSet(e.target.value) });
    return h("div", { class: "colour-row" }, pick, text, value ? h("button", { class: "small ghost", title: "Back to the HUD's own colour", onclick: () => onSet(null) }, "×") : null);
  }
  // Recent fonts: shared with the Composer and the custom HUD editor (same key).
  const RECENT_FONTS = "sccbe-recent-fonts";
  function recentFonts() {
    try { const a = JSON.parse(localStorage.getItem(RECENT_FONTS) || "[]"); return Array.isArray(a) ? a.filter(f => typeof f === "string" && f) : []; }
    catch (e) { return []; }
  }
  function useFont(name) {
    if (!name) return;
    try { localStorage.setItem(RECENT_FONTS, JSON.stringify([name, ...recentFonts().filter(f => f !== name)].slice(0, 12))); } catch (e) { }
  }
  function fontIn(value, now, onSet) {
    const fonts = (info && info.fonts) || [];
    const all = [...new Set([...fonts, value, now, "Arial", "Arial Black", "Segoe UI", "Impact", "Verdana", "Tahoma", "Georgia", "Bahnschrift", "Consolas"].filter(Boolean))];
    const recent = recentFonts().filter(f => all.includes(f)).slice(0, 8);
    let picked = false;
    const opt = f => h("option", { value: f, selected: !picked && f === value ? (picked = true) : false }, f);
    const set = v => { useFont(v); onSet(v); };
    const s = h("select", { dataset: { k: "font" }, onchange: e => {
      if (e.target.value === "\u0000upload") { e.target.value = value || ""; return uploadFont(set); }
      set(e.target.value || null);
    } },
      h("option", { value: "" }, now ? `${now} (as it is)` : "As it is"),
      recent.length ? h("optgroup", { label: "Recent" }, recent.map(opt)) : null,
      recent.length ? h("optgroup", { label: "All fonts" }, all.map(opt)) : null,
      ...(recent.length ? [] : all.map(opt)),
      h("option", { value: "\u0000upload" }, "Add a font file…"));
    return s;
  }
  const WEIGHTS = [["", "As it is"], [300, "Light"], [400, "Regular"], [500, "Medium"], [600, "Semibold"], [700, "Bold"], [800, "Extra bold"], [900, "Black"]];
  const CASES = [["", "As it is"], ["upper", "UPPER CASE"], ["lower", "lower case"], ["capitalize", "Title Case"], ["none", "As typed"]];
  const pickList = (k, options, value, onSet) => h("select", { dataset: { k }, onchange: e => onSet(e.target.value === "" ? null : (isNaN(+e.target.value) ? e.target.value : +e.target.value)) },
    ...options.map(([v, t]) => h("option", { value: v, selected: String(v) === String(value == null ? "" : value) }, t)));

  function renderProps() {
    const box = $("#he-props");
    if (!box) return;
    const focusK = document.activeElement && box.contains(document.activeElement) ? document.activeElement.dataset.k : null;
    const s = info && info.selected;
    if (!open) return box.replaceChildren();
    if (!s) {
      box.replaceChildren(
        sect(null, h("h3", {}, open.design.name), h("span", { class: "muted small" }, `${open.title} HUD`),
          lab("Test view (the HUD's own previews)", h("input", { value: testView, placeholder: "e.g. rwin=1", dataset: { k: "testview" },
            onchange: e => { const v = e.target.value.trim(); if (v === testView) return; if (info && info.dirty && !confirm("Reopening the HUD drops the changes you haven't saved. Go on?")) { e.target.value = testView; return; } testView = v; load(); } }))),
        sect("How it works",
          h("p", { class: "muted small" }, "Click any part of the HUD to change it: drag to move, pull the corners to resize (Shift stretches), arrow keys nudge (Shift: 10 px). Delete takes it off (Restore in Layers, or Ctrl+Z, puts it back)."),
          h("p", { class: "muted small" }, "T, ▭, ◯, ▱, 🖼 and More above Layers add text, shapes and pictures of your own over the HUD (Ctrl+D duplicates one)."),
          h("p", { class: "muted small" }, "Its live data stays as it is: names, scores, timers and pictures from the game keep coming in."),
          h("p", { class: "muted small" }, "Parts that only show now and then (the scoreboard, a round win, the Ace): use the Show buttons above the HUD (Everything shows them all), or tick “Show every part”."),
          h("p", { class: "muted small" }, "Save puts your changes on air at once, everywhere this HUD is shown. Every saved version is kept (Versions).")),
        ...settingsSects(),
        sect("Whole HUD", h("button", { class: "small danger", onclick: () => { if (confirm("Take every change off this HUD? (Save to put that on air; Versions keeps the old one.)")) send("reset-all"); } }, "Undo all changes")));
      if (focusK) { const el = box.querySelector(`[data-k="${focusK}"]`); if (el) el.focus(); }
      return;
    }
    box.replaceChildren(...(s.added ? addedProps(s) : partProps(s)));
    if (focusK) { const el = box.querySelector(`[data-k="${focusK}"]`); if (el) el.focus(); }
  }

  // The HUD's own settings: when parts come in and go out, how long things stay up.
  function settingsSects() {
    const dec = (info && info.declared) || [], vals = (info && info.settings) || {};
    if (!dec.length) return [];
    const groups = [];
    dec.forEach(d => { let g = groups.find(x => x.name === (d.group || "Settings")); if (!g) groups.push(g = { name: d.group || "Settings", list: [] }); g.list.push(d); });
    const put = (k, v) => send("setting", { key: k, value: v });
    return groups.map(g => sect(g.name, ...g.list.map(d => {
      const v = vals[d.key];
      const changed = v !== undefined && v !== null && v !== "" && v !== d.def;
      let input;
      if (d.type === "bool") input = h("label", { class: "check" }, h("input", { type: "checkbox", dataset: { k: "s:" + d.key }, checked: v === undefined ? !!d.def : !!v, onchange: e => put(d.key, e.target.checked === !!d.def ? null : e.target.checked) }), " " + d.label);
      else if (d.type === "choice") input = lab(d.label, h("select", { dataset: { k: "s:" + d.key }, onchange: e => put(d.key, e.target.value === String(d.def) ? null : e.target.value) },
        ...d.options.map(([ov, ot]) => h("option", { value: ov, selected: String(v === undefined ? d.def : v) === String(ov) }, ot))));
      else input = lab(d.label + (d.unit ? ` (${d.unit})` : ""), h("input", { type: "number", step: d.step || "any", min: d.min, max: d.max, dataset: { k: "s:" + d.key },
        value: v === undefined || v === null ? d.def : v, onchange: e => put(d.key, e.target.value === "" || +e.target.value === d.def ? null : +e.target.value) }));
      return h("div", { class: "he-setting" + (changed ? " changed" : "") }, input,
        d.help ? h("p", { class: "muted small" }, d.help + (changed ? ` (normally ${d.type === "bool" ? (d.def ? "on" : "off") : d.def}${d.unit ? " " + d.unit : ""})` : "")) : null);
    })));
  }

  const KIND_NAME = { text: "Text part", picture: "Picture part", group: "Group", shape: "Shape part", box: "Box part" };
  function partProps(s) {
    const r = s.rule || {}, now = s.now || {};
    const out = [];
    if (s.deleted || s.inDeleted) {
      out.push(sect(null, h("h3", {}, r.label || s.name || "Part"),
        h("div", { class: "gone-note small" }, s.deleted ? "Deleted: it isn't on air." : "The part it's in is deleted, so it isn't on air."),
        h("div", { class: "row-gap" }, btn("Restore", () => send("restore", { sel: s.deleted ? s.sel : s.inDeleted }), { class: "small primary" }))));
      return out;
    }
    renderPos.box = h("div", {});
    out.push(sect(null,
      h("h3", { title: s.sel }, KIND_NAME[s.kind] || "Part"),
      lab("Name", h("input", { value: r.label || "", placeholder: s.name || "", dataset: { k: "label" }, onchange: e => set({ label: e.target.value.trim() || null }) })),
      renderPos.box,
      h("div", { class: "row-gap" },
        btn("Centre", () => s.rect && send("rect", { x: Math.round((1920 - s.rect.w) / 2), y: Math.round((1080 - s.rect.h) / 2) }), { title: "Centre on the HUD" }),
        s.parent ? btn("Part around it", () => send("select", { sel: s.parent }), { title: "Pick the part this one is in" }) : null,
        h("span", { class: "grow" }),
        btn("Delete", () => send("delete"), { class: "small danger", title: "Take it off the HUD (Delete key). Restore or Ctrl+Z puts it back" })),
      h("label", { class: "check", title: "A locked part can't be picked, moved, resized or deleted on the HUD" },
        h("input", { type: "checkbox", checked: !!s.locked, onchange: e => set({ lock: e.target.checked || null }) }), " Locked"),
      s.inLocked ? h("p", { class: "small muted" }, "The part it's in is locked, so it can't be moved on the HUD.") : null,
      s.similar ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: s.all, onchange: e => send("all", { on: e.target.checked }) }), ` The same for all ${s.similar} like it`) : null,
      s.exists ? null : h("p", { class: "small warn" }, "It isn't on the page right now. Changes are kept for when it is.")));
    fillPos(s);
    out.push(sect("Show",
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!r.hide, onchange: e => set({ hide: e.target.checked || null }) }), " Hide it on air (it keeps its place)")));
    if (s.hasText) {
      out.push(sect("Text",
        lab("Font", fontIn(r.font, now.font, v => set({ font: v }))),
        h("div", { class: "grid3" }, lab("Size", numIn("size", r.size, now.size, v => set({ size: v }), { min: 1, step: 1 })),
          lab("Weight", pickList("weight", WEIGHTS, r.weight, v => set({ weight: v }))),
          lab("Tracking", numIn("spacing", r.spacing, now.spacing, v => set({ spacing: v }), { step: 0.5 }))),
        lab("Colour", colourIn("color", r.color, now.color, v => set({ color: v }))),
        lab("Case", pickList("case", CASES, r.case, v => set({ case: v })))));
    }
    out.push(sect(s.svg ? "Fill" : "Background",
      lab(s.svg ? "Fill colour" : "Background colour", colourIn("bg", r.bg, now.bg, v => set({ bg: v }))),
      s.svg ? null : lab("Corner radius", numIn("radius", r.radius, now.radius, v => set({ radius: v }), { min: 0 }))));
    if (s.picture) {
      out.push(sect("Picture",
        h("div", { class: "row-gap" },
          btn(r.img ? "Another picture…" : "Replace the picture…", () => upload("image/*,video/webm,video/mp4", name => set({ img: name, imgKind: s.picture }))),
          r.img ? h("button", { class: "small ghost", onclick: () => set({ img: null }) }, "Back to the HUD's own") : null),
        /logo|team|flag|agent|champ|hero|photo|crest/i.test(s.src || "") ? h("p", { class: "muted small" }, "This picture may come from the game data (a team logo, an agent…). A picture put here replaces it for every team.") : null));
    }
    const motion = (now.motion || "");
    out.push(sect("Animation",
      h("p", { class: "muted small" }, motion ? `It animates: ${motion}.` : "No animation of its own (the part around it may have one)."),
      grid(lab("Speed (seconds)", numIn("dur", r.dur, "as it is", v => set({ dur: v }), { min: 0, step: 0.05 })),
        lab("Wait before (seconds)", numIn("delay", r.delay, "as it is", v => set({ delay: v }), { min: 0, step: 0.05 }))),
      lab("Feel", pickList("ease", [["", "As it is"], ["snappy", "Snappy"], ["ease", "Smooth"], ["ease-out", "Slow at the end"], ["ease-in", "Slow at the start"], ["linear", "Even"], ["bounce", "Bounce"]], r.ease, v => set({ ease: v }))),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!r.noanim, onchange: e => set({ noanim: e.target.checked || null }) }), " No animation (it just appears)"),
      h("p", { class: "muted small" }, (info && info.states && info.states.length) ? "Press ▶ Replay, or switch between the Show buttons, to watch it." : "Press ▶ Replay to watch it.")));
    out.push(sect(null, h("button", { class: "small", disabled: !Object.keys(r).filter(k => k !== "svg").length, onclick: () => send("reset-part") }, "Undo all changes to this part")));
    return out;
  }
  function fillPos(s) {
    const r = s.rule || {}, b = renderPos.box, now = s.now || {};
    if (!b) return;
    const rc = s.rect || { x: 0, y: 0, w: 0, h: 0 };
    const place = (k, v) => v != null && send("rect", { [k]: v });
    b.replaceChildren(
      grid4(lab("X", numIn("x", rc.x, "", v => place("x", v))), lab("Y", numIn("y", rc.y, "", v => place("y", v))),
        lab("W", numIn("w", rc.w, "", v => place("w", v), { min: 1 })), lab("H", numIn("h", rc.h, "", v => place("h", v), { min: 1 }))),
      grid4(lab("Opacity", numIn("op", r.op == null ? "" : r.op, Math.round((now.opacity == null ? 1 : now.opacity) * 100) / 100, v => set({ op: v == null ? null : Math.max(0, Math.min(1, v)) }), { min: 0, max: 1, step: 0.05 })),
        lab("Rotate °", numIn("rot", r.rot || 0, 0, v => set({ rot: v || null }))),
        lab("Width %", numIn("sx", Math.round((r.sx == null ? 1 : r.sx) * 1000) / 10, 100, v => set({ sx: v == null ? null : v / 100 }), { min: 1, step: 1 })),
        lab("Height %", numIn("sy", Math.round((r.sy == null ? 1 : r.sy) * 1000) / 10, 100, v => set({ sy: v == null ? null : v / 100 }), { min: 1, step: 1 }))));
  }
  // (while dragging: just the numbers)
  function renderPos() {
    const s = info && info.selected;
    if (!s) return;
    if (s.added) return renderProps();
    if (document.activeElement && renderPos.box && renderPos.box.contains(document.activeElement)) return;
    fillPos(s);
  }

  const SHAPES = [["rect", "Rectangle"], ["ellipse", "Circle"], ["slant", "Slanted box"], ["triangle", "Triangle"], ["line", "Line"], ["arrow", "Arrow"], ["chevron", "Chevron"], ["star", "Star"]];
  function addedProps(s) {
    const a = s.item || {};
    const shape = a.type === "box" ? "rect" : a.shape || "rect";
    const isShape = a.type === "box" || a.type === "shape";
    const kind = isShape ? "Shape" : { text: "Text", image: "Picture" }[a.type] || "";
    const out = [];
    out.push(sect(null,
      h("h3", {}, kind + " layer"),
      lab("Name", h("input", { value: a.label || "", placeholder: s.name, dataset: { k: "label" }, onchange: e => set({ label: e.target.value.trim() || null }) })),
      grid4(lab("X", numIn("ax", a.x, 0, v => set({ x: v || 0 }))), lab("Y", numIn("ay", a.y, 0, v => set({ y: v || 0 }))),
        lab("W", numIn("aw", a.w, 200, v => set({ w: Math.max(1, v || 1) }), { min: 1 })), lab("H", numIn("ah", a.h, 60, v => set({ h: Math.max(1, v || 1) }), { min: 1 }))),
      grid4(lab("Opacity", numIn("aop", a.op == null ? 1 : a.op, 1, v => set({ op: v == null || v >= 1 ? null : Math.max(0, v) }), { min: 0, max: 1, step: 0.05 })),
        lab("Rotate °", numIn("arot", a.rot || 0, 0, v => set({ rot: v || null })))),
      h("div", { class: "row-gap" },
        btn("Duplicate", () => send("duplicate"), { title: "Ctrl+D" }),
        btn("Fill", () => set({ x: 0, y: 0, w: 1920, h: 1080 }), { title: "Full screen" }),
        btn("Centre", () => set({ x: Math.round((1920 - (a.w || 0)) / 2), y: Math.round((1080 - (a.h || 0)) / 2) }), { title: "Centre on the HUD" }),
        h("span", { class: "grow" }),
        btn("Delete", () => send("delete"), { class: "small danger", title: "Delete key" })),
      h("label", { class: "check", title: "A locked layer can't be picked, moved, resized or deleted on the HUD" },
        h("input", { type: "checkbox", checked: !!a.lock, onchange: e => set({ lock: e.target.checked || null }) }), " Locked")));
    if (isShape) {
      const fill = a.fill || a.bg || "#ffffff";
      out.push(sect("Shape",
        h("div", { class: "he-shapes" }, ...SHAPES.map(([k, t]) => h("button", { class: "small" + (k === shape ? " on" : ""), title: t,
          onclick: () => set(a.type === "box" ? { type: "shape", shape: k, fill: fill, bg: null } : { shape: k }) }, SHAPE_ICON[k]))),
        lab(shape === "line" ? "Colour" : "Fill", colourIn("afill", fill, "#ffffff", v => set({ fill: v || "#ffffff", bg: null }))),
        shape === "line" ? null : lab("Second colour (a gradient)", colourIn("afill2", a.fill2, "", v => set({ fill2: v }))),
        a.fill2 && shape !== "line" ? lab("Gradient angle °", numIn("aangle", a.angle, 90, v => set({ angle: v }))) : null,
        shape === "line"
          ? grid(lab("Thickness", numIn("asw", a.strokeWidth, 6, v => set({ strokeWidth: v }), { min: 1 })),
                 h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!a.radius, onchange: e => set({ radius: e.target.checked ? 1 : null }) }), " Round ends"))
          : grid(lab("Border", colourIn("astroke", a.stroke || a.borderColor, "#ffffff", v => set({ stroke: v, borderColor: null }))),
                 lab("Border width", numIn("asw", a.strokeWidth != null ? a.strokeWidth : a.border, 0, v => set({ strokeWidth: v, border: null }), { min: 0 }))),
        shape === "rect" ? lab("Corner radius", numIn("aradius", a.radius, 0, v => set({ radius: v }), { min: 0 })) : null,
        shape === "slant" ? lab("Slant (px, minus leans the other way)", numIn("aslant", a.slant, Math.round((a.h || 60) * 0.5), v => set({ slant: v }))) : null));
    }
    if (a.type === "text") out.push(sect("Text",
      h("textarea", { rows: 2, dataset: { k: "text" }, onchange: e => set({ text: e.target.value }) }, a.text || ""),
      lab("Font", fontIn(a.font, "", v => set({ font: v }))),
      h("div", { class: "grid3" }, lab("Size", numIn("size", a.size, 32, v => set({ size: v }), { min: 1 })),
        lab("Weight", pickList("weight", WEIGHTS, a.weight, v => set({ weight: v }))),
        lab("Tracking", numIn("spacing", a.spacing, 0, v => set({ spacing: v }), { step: 0.5 }))),
      lab("Colour", colourIn("color", a.color, "#ffffff", v => set({ color: v }))),
      grid(lab("Align", pickList("align", [["left", "Left"], ["center", "Centre"], ["right", "Right"]], a.align || "left", v => set({ align: v }))),
        lab("Case", pickList("case", CASES, a.case, v => set({ case: v })))),
      h("div", { class: "row-gap" },
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!a.italic, onchange: e => set({ italic: e.target.checked || null }) }), " Italic"),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!a.shadow, onchange: e => set({ shadow: e.target.checked || null }) }), " Shadow")),
      lab("Background colour", colourIn("abg", a.bg, "", v => set({ bg: v })))));
    if (a.type === "image") out.push(sect("Source",
      btn("Another picture…", () => upload("image/*,video/webm,video/mp4", name => set({ img: name }))),
      lab("Fit", pickList("fit", [["contain", "Fit inside"], ["cover", "Fill and crop"], ["fill", "Stretch"]], a.fit || "contain", v => set({ fit: v }))),
      grid(lab("Corner radius", numIn("aradius", a.radius, 0, v => set({ radius: v }), { min: 0 })),
        lab("Border width", numIn("aborder", a.border, 0, v => set({ border: v }), { min: 0 }))),
      +a.border ? lab("Border colour", colourIn("abc", a.borderColor, "#ffffff", v => set({ borderColor: v }))) : null));
    out.push(sect("Layer",
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!a.behind, onchange: e => set({ behind: e.target.checked || null }) }), " Behind the HUD"),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!a.hide, onchange: e => set({ hide: e.target.checked || null }) }), " Hide it on air"),
      h("div", { class: "row-gap" },
        btn("Bring forward", () => send("order", { id: a.id, by: 1 })),
        btn("Send back", () => send("order", { id: a.id, by: -1 })))));
    return out;
  }

  // --- files (pictures, fonts) go to the HUD's own app -----------------------------------
  function upload(accept, then) {
    const input = h("input", { type: "file", accept, onchange: async () => {
      const f = input.files[0];
      if (!f) return;
      try { then(await sendFile(f), f); } catch (e) { toast(e.message, true); }
    } });
    input.click();
  }
  async function sendFile(f) {
    // (text/plain: a plain request the HUD answers without asking first)
    const r = await fetch(hudUrl(`/hudedit/upload?name=${encodeURIComponent(f.name)}`), { method: "POST", body: await readFile(f), headers: { "Content-Type": "text/plain" } });
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || `Couldn't send it (${r.status})`);
    return j.name;
  }
  function uploadFont(onSet) {
    upload(".ttf,.otf,.woff,.woff2", (name, f) => {
      const family = f.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim();
      send("font", { family, file: name });
      onSet(family);
    });
  }

  function addItem(type) {
    const make = item => send("add", { item: Object.assign({ x: 860, y: 480, w: 200, h: 60, type }, item) });
    const SIZE = { rect: [240, 80], ellipse: [140, 140], slant: [300, 70], triangle: [140, 120], line: [300, 20], arrow: [220, 90], chevron: [160, 80], star: [140, 140] };
    if (SIZE[type]) {
      const [w, hh] = SIZE[type];
      return send("add", { item: { type: "shape", shape: type, fill: "#ffffff", x: Math.round((1920 - w) / 2), y: Math.round((1080 - hh) / 2), w, h: hh } });
    }
    if (type === "text") make({ text: "Text", size: 40, weight: 700, color: "#ffffff", w: 300, h: 60, x: 810, y: 510 });
    if (type === "image") upload("image/*,video/webm,video/mp4", (name, f) => {
      const img = new Image();
      const done = (w, hh) => { const k = Math.min(1, 600 / w, 400 / hh); make({ img: name, w: Math.round(w * k), h: Math.round(hh * k), label: f.name.replace(/\.[^.]+$/, "") }); };
      img.onload = () => done(img.naturalWidth || 300, img.naturalHeight || 200);
      img.onerror = () => done(320, 180);
      img.src = URL.createObjectURL(f);
    });
  }

  // --- versions ----------------------------------------------------------------------
  async function versions() {
    const dlg = $("#he-versions");
    const box = $("#he-versions-list");
    box.replaceChildren(h("p", { class: "muted" }, "Loading…"));
    dlg.showModal();
    try {
      const r = await (await fetch(hudUrl(`/hudedit/history?design=${encodeURIComponent(currentKey())}`), { cache: "no-store" })).json();
      const list = r.versions || [];
      if (!list.length) return box.replaceChildren(h("p", { class: "muted" }, "No earlier versions yet. Each Save keeps the one before it here."));
      box.replaceChildren(...list.map(v => h("div", { class: "he-ver" },
        h("span", {}, new Date(v.saved * 1000).toLocaleString()), h("span", { class: "muted small" }, `${v.parts} parts changed, ${v.added} added`),
        h("button", { class: "small", onclick: async () => {
          if (info && info.dirty && !confirm("Drop the changes you haven't saved and put this version back?")) return;
          try {
            const res = await fetch(hudUrl("/hudedit/restore"), { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify({ design: currentKey(), version: v.version }) });
            const j = await res.json();
            if (!res.ok || j.error) throw new Error(j.error || "Couldn't put it back");
            dlg.close(); send("discard"); send("reload"); toast("That version is back on air");
          } catch (e) { toast(e.message, true); }
        } }, "Put back"))));
    } catch (e) { box.replaceChildren(h("p", { class: "error" }, e.message)); }
  }
  const currentKey = () => (info && info.design) || open.design.key;

  // --- wiring ---------------------------------------------------------------------------
  function wire() {
    $("#he-back").onclick = () => { location.hash = "#/game-huds"; };
    $("#he-delete").onclick = () => send("delete");
    $("#he-replay").onclick = replay;
    $("#he-add-more").onchange = e => { const v = e.target.value; e.target.value = ""; if (v) addItem(v); };
    $("#he-undo").onclick = () => send("undo");
    $("#he-redo").onclick = () => send("redo");
    $("#he-save").onclick = () => send("save");
    $("#he-discard").onclick = () => { if (confirm("Drop the changes you haven't saved?")) send("discard"); };
    $("#he-versions-btn").onclick = versions;
    $$("[data-he-add]").forEach(b => { b.onclick = () => addItem(b.dataset.heAdd); });
    $("#he-bg").onchange = e => { $("#he-canvas").dataset.bg = e.target.value; };
    $("#he-search").oninput = e => { filter = e.target.value; renderParts(); };
    $("#he-hidden").onchange = e => { showHidden = e.target.checked; send("reveal", { on: showHidden }); renderParts(); };
    $("#he-refresh").onclick = () => send("tree");
    addEventListener("keydown", e => {
      if (document.body.dataset.page !== "hud-edit") return;
      const t = e.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
      const mod = e.ctrlKey || e.metaKey, step = e.shiftKey ? 10 : 1;
      let m = null;
      if (mod && /^z$/i.test(e.key)) m = { hudedit: e.shiftKey ? "redo" : "undo" };
      else if (mod && /^y$/i.test(e.key)) m = { hudedit: "redo" };
      else if (mod && /^s$/i.test(e.key)) m = { hudedit: "save" };
      else if (e.key === "ArrowLeft") m = { hudedit: "nudge", dx: -step, dy: 0 };
      else if (e.key === "ArrowRight") m = { hudedit: "nudge", dx: step, dy: 0 };
      else if (e.key === "ArrowUp") m = { hudedit: "nudge", dx: 0, dy: -step };
      else if (e.key === "ArrowDown") m = { hudedit: "nudge", dx: 0, dy: step };
      else if (e.key === "Escape") m = { hudedit: "select", sel: null };
      else if ((e.key === "Delete" || e.key === "Backspace") && info && info.selected) m = { hudedit: "delete" };
      else if (mod && /^d$/i.test(e.key) && info && info.selected && info.selected.added) m = { hudedit: "duplicate" };
      if (m) { e.preventDefault(); post(m); }
    });
    addEventListener("beforeunload", e => { if (info && info.dirty) { e.preventDefault(); e.returnValue = ""; } });
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", wire) : wire();

  return {
    list,
    isOpen: () => !!open,
    // Leaving the editor: OK when nothing's unsaved (or the user says so).
    leave() {
      if (open && info && info.dirty && !confirm("Leave without saving your changes to this HUD?")) return false;
      if (open) { frame().src = "about:blank"; open = null; info = null; }
      return true;
    },
    shown() { requestAnimationFrame(fit); }
  };
})();
