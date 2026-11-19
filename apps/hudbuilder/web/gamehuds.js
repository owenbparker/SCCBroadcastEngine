// HUD Builder > Game HUDs: every built-in game HUD (League, VALORANT, CoD,
// Rocket League, Smash, Overwatch, each of their designs and profiles) opened
// as it is, to change in place: move, resize, recolour, other fonts and
// pictures, hide parts, add boxes, text and pictures. Save puts it on air.
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
      h("div", { class: "gh-cards" }, ...g.designs.map(d => h("div", { class: "gh-card" + (g.running ? "" : " off"), onclick: () => g.running && edit(g, d) },
        h("b", {}, d.name), h("span", { class: "muted small" }, d.what),
        h("button", { class: "small primary", disabled: !g.running, onclick: e => { e.stopPropagation(); edit(g, d); } }, "Edit")))))));
  }

  // --- the editor -------------------------------------------------------------------
  function edit(g, d) {
    open = { game: g.game, title: g.title, port: g.port, design: d };
    info = null; nodes = []; added = []; frameReady = false; collapsed = new Set(); filter = ""; testView = ""; autoState = false;
    $("#he-title").textContent = `${g.title} · ${d.name}`;
    $("#he-test").value = "";
    $("#he-search").value = "";
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
    if (m.hudedit === "live") return renderPos();
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
    box.replaceChildren(...[
      h("span", { class: "muted small" }, "Show:"),
      chip("", "Live", "As it is on air right now"),
      ...list.map(x => chip(x.id, x.label, x.help)),
      list.length ? h("button", { class: "small ghost", title: "Play this state's animations again", onclick: replay }, "▶ Replay") : null,
      h("label", { class: "check small he-reveal" }, h("input", { type: "checkbox", checked: !!(info && info.revealAll), onchange: e => { showHidden = e.target.checked; $("#he-hidden").checked = showHidden; send("reveal", { on: e.target.checked }); } }), " Show every part")].filter(Boolean));
  }
  function replay() {
    const cur = (info && info.state) || "";
    const list = (info && info.states) || [];
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
    $("#he-redo").disabled = !(info && info.canRedo);
    if (frameReady) $("#he-status").textContent = dirty ? "Not saved yet" : "Saved · on air";
    $("#he-status").classList.toggle("warn", dirty);
  }

  // --- the parts list -------------------------------------------------------------
  const ICON = { text: "T", picture: "▣", group: "▤", shape: "◆", box: "□" };
  function renderParts() {
    const box = $("#he-parts");
    if (!box) return;
    const sel = info && info.selected;
    const rows = [];
    if (added.length) {
      rows.push(h("div", { class: "he-sub" }, "Added"));
      added.forEach(a => rows.push(h("div", { class: "lrow" + (sel && sel.added === a.added ? " sel" : ""), onclick: () => send("select", { added: a.added }) },
        h("span", { class: "lic" }, ICON[a.kind] || "□"), h("span", { class: "lname" }, a.name), a.shown ? null : h("span", { class: "lmeta" }, "hidden"))));
      rows.push(h("div", { class: "he-sub" }, "The HUD"));
    }
    const q = filter.trim().toLowerCase();
    let skipBelow = Infinity;
    for (const n of nodes) {
      if (n.depth > skipBelow) continue;
      skipBelow = Infinity;
      if (!showHidden && !n.shown && !n.edited) { skipBelow = n.depth; continue; }
      if (q && !n.name.toLowerCase().includes(q)) continue;
      const shut = collapsed.has(n.sel);
      if (shut && !q) skipBelow = n.depth;
      const on = sel && !sel.added && (sel.sel === n.sel);
      rows.push(h("div", { class: "lrow he-row" + (on ? " sel" : "") + (n.shown ? "" : " gone"), style: { paddingLeft: (q ? 6 : 6 + n.depth * 12) + "px" },
        onclick: () => send("select", { sel: n.sel }), title: n.sel },
        n.kids && !q ? h("span", { class: "he-caret", onclick: e => { e.stopPropagation(); shut ? collapsed.delete(n.sel) : collapsed.add(n.sel); renderParts(); } }, shut ? "▸" : "▾") : h("span", { class: "he-caret" }),
        h("span", { class: "lic" }, ICON[n.kind] || "□"),
        h("span", { class: "lname" }, n.name),
        n.edited ? h("span", { class: "he-dot", title: "Changed" }) : null));
    }
    if (!rows.length) rows.push(h("p", { class: "hint muted" }, frameReady ? "Nothing on screen here. Tick “Show every part”." : "Opening the HUD…"));
    const keep = box.scrollTop;
    box.replaceChildren(...rows);
    box.scrollTop = keep;
  }

  // --- the properties of what's picked ---------------------------------------------------
  const lab = (t, el) => h("label", {}, h("span", { class: "muted small" }, t), el);
  const grid = (...kids) => h("div", { class: "grid2" }, ...kids.filter(Boolean));
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
  function fontIn(value, now, onSet) {
    const fonts = (info && info.fonts) || [];
    const all = [...new Set([...fonts, value, now, "Arial", "Arial Black", "Segoe UI", "Impact", "Verdana", "Tahoma", "Georgia", "Bahnschrift", "Consolas"].filter(Boolean))];
    const s = h("select", { dataset: { k: "font" }, onchange: e => {
      if (e.target.value === "\u0000upload") { e.target.value = value || ""; return uploadFont(onSet); }
      onSet(e.target.value || null);
    } },
      h("option", { value: "" }, now ? `${now} (as it is)` : "As it is"),
      ...all.map(f => h("option", { value: f, selected: f === value }, f)),
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
      box.replaceChildren(h("div", { class: "props-head" }, h("h3", {}, open.design.name), h("span", { class: "muted" }, open.title)),
        sect(null,
          h("p", { class: "muted small" }, "Click any part of the HUD to change it: drag to move, pull the corners to resize (Shift stretches), arrow keys nudge (Shift: 10 px)."),
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

  function partProps(s) {
    const r = s.rule || {}, now = s.now || {};
    const out = [h("div", { class: "props-head" }, h("h3", { title: s.sel }, r.label || s.name || "Part"), h("span", { class: "muted" }, s.kind || ""))];
    out.push(sect(null,
      lab("Name (just for you)", h("input", { value: r.label || "", placeholder: s.name || "", dataset: { k: "label" }, onchange: e => set({ label: e.target.value.trim() || null }) })),
      h("div", { class: "row-gap" },
        s.parent ? h("button", { class: "small", onclick: () => send("select", { sel: s.parent }) }, "Pick the part around it") : null),
      s.similar ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: s.all, onchange: e => send("all", { on: e.target.checked }) }), ` The same for all ${s.similar} like it`) : null,
      s.exists ? null : h("p", { class: "small warn" }, "It isn't on the page right now. Changes are kept for when it is.")));
    renderPos.box = h("div", { class: "grid2" });
    out.push(sect("Position and size", renderPos.box,
      s.rect ? h("p", { class: "muted small", id: "he-rect" }, rectText(s.rect)) : null));
    fillPos(s);
    out.push(sect("Show",
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!r.hide, onchange: e => set({ hide: e.target.checked || null }) }), " Hide it on air"),
      lab("Opacity %", numIn("op", r.op == null ? "" : Math.round(r.op * 100), Math.round((now.opacity == null ? 1 : now.opacity) * 100), v => set({ op: v == null ? null : Math.max(0, Math.min(100, v)) / 100 }), { min: 0, max: 100, step: 5 }))));
    if (s.hasText) {
      out.push(sect("Text",
        lab("Font", fontIn(r.font, now.font, v => set({ font: v }))),
        grid(lab("Size (px)", numIn("size", r.size, now.size, v => set({ size: v }), { min: 1, step: 1 })),
          lab("Weight", pickList("weight", WEIGHTS, r.weight, v => set({ weight: v })))),
        lab("Colour", colourIn("color", r.color, now.color, v => set({ color: v }))),
        grid(lab("Letter spacing", numIn("spacing", r.spacing, now.spacing, v => set({ spacing: v }), { step: 0.5 })),
          lab("Case", pickList("case", CASES, r.case, v => set({ case: v }))))));
    }
    out.push(sect(s.svg ? "Fill" : "Background",
      lab(s.svg ? "Fill colour" : "Background colour", colourIn("bg", r.bg, now.bg, v => set({ bg: v }))),
      s.svg ? null : lab("Rounded corners (px)", numIn("radius", r.radius, now.radius, v => set({ radius: v }), { min: 0 }))));
    const motion = (now.motion || "");
    out.push(sect("Animation",
      h("p", { class: "muted small" }, motion ? `It animates: ${motion}.` : "No animation of its own (the part around it may have one)."),
      grid(lab("Speed (seconds)", numIn("dur", r.dur, "as it is", v => set({ dur: v }), { min: 0, step: 0.05 })),
        lab("Wait before (seconds)", numIn("delay", r.delay, "as it is", v => set({ delay: v }), { min: 0, step: 0.05 }))),
      lab("Feel", pickList("ease", [["", "As it is"], ["snappy", "Snappy"], ["ease", "Smooth"], ["ease-out", "Slow at the end"], ["ease-in", "Slow at the start"], ["linear", "Even"], ["bounce", "Bounce"]], r.ease, v => set({ ease: v }))),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!r.noanim, onchange: e => set({ noanim: e.target.checked || null }) }), " No animation (it just appears)"),
      (info && info.states && info.states.length) ? h("p", { class: "muted small" }, "Press ▶ Replay above, or switch between the Show buttons, to watch it.") : null));
    if (s.picture) {
      out.push(sect("Picture",
        h("div", { class: "row-gap" },
          h("button", { class: "small", onclick: () => upload("image/*,video/webm,video/mp4", name => set({ img: name, imgKind: s.picture })) }, r.img ? "Another picture…" : "Replace the picture…"),
          r.img ? h("button", { class: "small ghost", onclick: () => set({ img: null }) }, "Back to the HUD's own") : null),
        /logo|team|flag|agent|champ|hero|photo|crest/i.test(s.src || "") ? h("p", { class: "muted small" }, "This picture may come from the game data (a team logo, an agent…). A picture put here replaces it for every team.") : null));
    }
    out.push(sect(null, h("button", { class: "small danger", disabled: !Object.keys(r).filter(k => k !== "svg").length, onclick: () => send("reset-part") }, "Undo all changes to this part")));
    return out;
  }
  const rectText = r => `On the page: ${r.x}, ${r.y} · ${r.w} × ${r.h}`;
  function fillPos(s) {
    const r = s.rule || {}, b = renderPos.box;
    if (!b) return;
    b.replaceChildren(
      lab("Move across (px)", numIn("x", r.x || 0, 0, v => set({ x: v || null }))),
      lab("Move down (px)", numIn("y", r.y || 0, 0, v => set({ y: v || null }))),
      lab("Width %", numIn("sx", Math.round((r.sx == null ? 1 : r.sx) * 1000) / 10, 100, v => set({ sx: v == null ? null : v / 100 }), { min: 1, step: 1 })),
      lab("Height %", numIn("sy", Math.round((r.sy == null ? 1 : r.sy) * 1000) / 10, 100, v => set({ sy: v == null ? null : v / 100 }), { min: 1, step: 1 })),
      lab("Rotate °", numIn("rot", r.rot || 0, 0, v => set({ rot: v || null }))));
  }
  // (while dragging: just the numbers)
  function renderPos() {
    const s = info && info.selected;
    if (!s) return;
    if (s.added) return renderProps();
    if (document.activeElement && renderPos.box && renderPos.box.contains(document.activeElement)) return;
    fillPos(s);
    const t = $("#he-rect");
    if (t && s.rect) t.textContent = rectText(s.rect);
  }

  function addedProps(s) {
    const a = s.item || {};
    const kind = { box: "Box", text: "Text", image: "Picture" }[a.type] || "";
    const out = [h("div", { class: "props-head" }, h("h3", {}, s.name), h("span", { class: "muted" }, `${kind} you added`))];
    out.push(sect(null, lab("Name (just for you)", h("input", { value: a.label || "", dataset: { k: "label" }, onchange: e => set({ label: e.target.value.trim() || null }) }))));
    if (a.type === "text") out.push(sect("Text",
      h("textarea", { rows: 2, dataset: { k: "text" }, onchange: e => set({ text: e.target.value }) }, a.text || ""),
      lab("Font", fontIn(a.font, "", v => set({ font: v }))),
      grid(lab("Size (px)", numIn("size", a.size, 32, v => set({ size: v }), { min: 1 })), lab("Weight", pickList("weight", WEIGHTS, a.weight, v => set({ weight: v })))),
      lab("Colour", colourIn("color", a.color, "#ffffff", v => set({ color: v }))),
      grid(lab("Line up", pickList("align", [["left", "Left"], ["center", "Centre"], ["right", "Right"]], a.align || "left", v => set({ align: v }))),
        lab("Case", pickList("case", CASES, a.case, v => set({ case: v })))),
      lab("Letter spacing", numIn("spacing", a.spacing, 0, v => set({ spacing: v }), { step: 0.5 }))));
    if (a.type === "image") out.push(sect("Picture",
      h("button", { class: "small", onclick: () => upload("image/*,video/webm,video/mp4", name => set({ img: name })) }, "Another picture…"),
      lab("Fit", pickList("fit", [["contain", "Whole picture"], ["cover", "Fill the box"], ["fill", "Stretch"]], a.fit || "contain", v => set({ fit: v })))));
    out.push(sect("Position and size",
      grid(lab("X", numIn("ax", a.x, 0, v => set({ x: v || 0 }))), lab("Y", numIn("ay", a.y, 0, v => set({ y: v || 0 }))),
        lab("Width", numIn("aw", a.w, 200, v => set({ w: Math.max(1, v || 1) }))), lab("Height", numIn("ah", a.h, 60, v => set({ h: Math.max(1, v || 1) }))),
        lab("Rotate °", numIn("arot", a.rot || 0, 0, v => set({ rot: v || null }))),
        lab("Opacity %", numIn("aop", a.op == null ? 100 : Math.round(a.op * 100), 100, v => set({ op: v == null ? null : Math.max(0, Math.min(100, v)) / 100 }), { min: 0, max: 100, step: 5 })))));
    out.push(sect(a.type === "text" ? "Box behind the text" : "Look",
      lab(a.type === "text" ? "Background colour" : a.type === "box" ? "Colour" : "Background colour", colourIn("abg", a.bg, a.type === "box" ? "#ffffff" : "", v => set({ bg: v }))),
      grid(lab("Rounded corners", numIn("aradius", a.radius, 0, v => set({ radius: v }), { min: 0 })),
        lab("Outline (px)", numIn("aborder", a.border, 0, v => set({ border: v }), { min: 0 }))),
      +a.border ? lab("Outline colour", colourIn("abc", a.borderColor, "#ffffff", v => set({ borderColor: v }))) : null));
    out.push(sect(null,
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!a.behind, onchange: e => set({ behind: e.target.checked || null }) }), " Behind the HUD"),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!a.hide, onchange: e => set({ hide: e.target.checked || null }) }), " Hide it on air"),
      h("div", { class: "row-gap" },
        h("button", { class: "small", onclick: () => send("order", { id: a.id, by: 1 }) }, "Forward"),
        h("button", { class: "small", onclick: () => send("order", { id: a.id, by: -1 }) }, "Back"),
        h("button", { class: "small", onclick: () => send("add", { item: Object.assign({}, a, { id: undefined, x: (a.x || 0) + 20, y: (a.y || 0) + 20 }) }) }, "Duplicate"),
        h("button", { class: "small danger", onclick: () => send("remove-added", { id: a.id }) }, "Delete"))));
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
    if (type === "box") make({ bg: "#ffffff", w: 240, h: 80 });
    if (type === "text") make({ text: "Text", size: 40, weight: 700, color: "#ffffff", w: 300, h: 60, label: "" });
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
    $("#he-undo").onclick = () => send("undo");
    $("#he-redo").onclick = () => send("redo");
    $("#he-save").onclick = () => send("save");
    $("#he-discard").onclick = () => { if (confirm("Drop the changes you haven't saved?")) send("discard"); };
    $("#he-versions-btn").onclick = versions;
    $$("[data-he-add]").forEach(b => { b.onclick = () => addItem(b.dataset.heAdd); });
    $("#he-bg").onchange = e => { $("#he-canvas").dataset.bg = e.target.value; };
    $("#he-test").onchange = e => { testView = e.target.value.trim(); if (open) { if (info && info.dirty && !confirm("Reopening the HUD drops the changes you haven't saved. Go on?")) return; load(); } };
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
      else if ((e.key === "Delete" || e.key === "Backspace") && info && info.selected && info.selected.added) m = { hudedit: "remove-added", id: info.selected.added.toString() };
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
