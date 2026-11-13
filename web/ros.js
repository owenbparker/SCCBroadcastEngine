// Run of show: the panel on the left of Control, and its builder (#ros):
// templates per game, made of blocks of segments, each with its own text
// colour. Tonight's show is laid out from the newest match in the GFX
// Engine's Schedule; times move when a game runs long. See sccbe/ros.py.
"use strict";

const Ros = (() => {
  let R = null;            // the latest /api/ros
  let editing = null;      // the template open in the builder (a copy being edited)
  let saveTimer = null;
  let visible = { panel: false, builder: false };

  const pad = n => String(n).padStart(2, "0");
  const hm = t => { const d = new Date(t * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const mmss = mins => { const s = Math.round(mins * 60); return `${Math.floor(s / 60)}:${pad(s % 60)}`; };
  const uid = () => Math.random().toString(16).slice(2, 12);
  const gameName = k => (R && R.games[k]) || k;

  async function load() {
    try { R = await api("/api/ros"); } catch (e) { return; }
    if (visible.panel) renderPanel();
    if (visible.builder) renderTonight();
  }
  async function send(path, body) {
    try { R = await api(path, body || {}); } catch (e) { alertBox(e.message); return null; }
    if (visible.panel) renderPanel();
    if (visible.builder) renderBuilder();
    return R;
  }

  // --- the panel on Control ---------------------------------------------------

  function matchLine(show) {
    const m = (show && show.match) || {};
    if (!m.team1 && !m.team2 && !m.tournament) return "No match in the Schedule yet · Event › Schedule";
    const teams = [m.team1, m.team2].filter(Boolean).join(" vs ");
    return [m.tournament, teams].filter(Boolean).join(" · ") + " · from Schedule";
  }

  function renderPanel() {
    const box = $("#ros-panel");
    if (!R) { box.innerHTML = `<h2>Run of show</h2><p class="mut small">Loading…</p>`; return; }
    const show = R.show;
    const segs = (show && show.segments) || [];
    const tl = (show && show.timeline) || [];
    const cur = show ? show.current : -1;
    let html = `<div class="ros-head"><h2>Run of show</h2><div class="sub">${esc(matchLine(show))}</div></div><div class="ros-list" id="ros-list">`;
    if (!segs.length) {
      const game = show && show.match && show.match.game_key;
      html += `<div class="ros-empty">${show && show.template_name === "" && game
        ? `No ${esc(gameName(game))} template yet, so tonight starts blank.` : "Nothing in tonight's run of show yet."}
        <button class="k" data-ros="builder">Build a template</button></div>`;
    }
    let lastBlock = null;
    segs.forEach((s, i) => {
      const t = tl[i] || {};
      if (s.block && s.block !== lastBlock) {
        const end = segs.reduce((acc, x, j) => x.block === s.block ? j : acc, i);
        html += `<div class="ros-block" style="--c:${s.block_color}"><span>${esc(s.block)}</span><small>${t.est_start ? "~" : ""}${t.start ? hm(t.start) : ""} – ${tl[end] && tl[end].est_end ? "~" : ""}${tl[end] ? hm(tl[end].end) : ""}</small></div>`;
        lastBlock = s.block;
      }
      const state = i === cur ? "now" : i === cur + 1 ? "next" : i < cur ? "done" : "";
      const label = state === "now" ? `<b class="air">ON AIR</b>` : state === "next" ? `<b class="nxt">NEXT</b>` : "";
      const running = state === "now" && t.start ? `running ${mmss((Date.now() / 1000 - t.start) / 60)}` : "";
      html += `<div class="seg ${state}" data-i="${i}" title="Double-click to put this segment on air">
        <span class="tm">${t.est_start ? "~" : ""}${t.start ? hm(t.start) : ""}</span>
        <div class="bd"><div class="tt" style="color:${s.color}">${esc(s.title)}${label}</div>
          ${s.notes || running ? `<div class="nt">${esc(running || s.notes)}</div>` : ""}
          ${s.graphics.length ? `<div class="tags">${s.graphics.map(g => `<button data-cue="${esc(g)}" title="Put ${esc(g)} on Preview">${esc(g)}</button>`).join("")}</div>` : ""}
        </div></div>`;
    });
    html += `</div><div class="ros-foot">
      <button data-ros="builder">Edit</button>
      <button class="k" data-ros="next" ${segs.length ? "" : "disabled"}>${cur < 0 ? "Start show ›" : cur >= segs.length - 1 ? (cur >= segs.length ? "Show over" : "End show") : "Next segment ›"}</button></div>
      <div class="ros-more"><button data-ros="apply">Rebuild from Schedule</button><button data-ros="reset" ${cur >= 0 ? "" : "disabled"}>Reset times</button></div>`;
    const scroll = (box.querySelector("#ros-list") || {}).scrollTop;
    box.innerHTML = html;
    const list = box.querySelector("#ros-list");
    if (scroll !== undefined) list.scrollTop = scroll;
    else if (cur >= 0) { const el = list.querySelector(".seg.now"); if (el) el.scrollIntoView({ block: "center" }); }
  }

  $("#ros-panel").addEventListener("click", e => {
    const cue = e.target.closest("[data-cue]"), b = e.target.closest("[data-ros]");
    if (cue) {
      api("/api/engine/cue", { name: cue.dataset.cue }).then(() => cue.classList.add("cued"), err => alertBox(err.message));
      setTimeout(() => cue.classList.remove("cued"), 1500);
      return;
    }
    if (!b) return;
    const what = b.dataset.ros;
    if (what === "builder") go("ros");
    if (what === "next") send("/api/ros/next");
    if (what === "reset") send("/api/ros/reset");
    if (what === "apply") send("/api/ros/apply");
  });
  $("#ros-panel").addEventListener("dblclick", e => {
    const seg = e.target.closest(".seg[data-i]");
    if (seg && !e.target.closest("[data-cue]")) send("/api/ros/go", { index: +seg.dataset.i });
  });

  // --- the builder ----------------------------------------------------------------

  function openTemplate(id) {
    const t = R.templates.find(x => x.id === id);
    editing = t ? JSON.parse(JSON.stringify(t)) : null;
    renderBuilder();
  }

  function queueSave() {
    clearTimeout(saveTimer);
    $("#rb-saved").textContent = "Saving…";
    saveTimer = setTimeout(async () => {
      if (!editing) return;
      try {
        const r = await api("/api/ros/template", { template: editing });
        const i = R.templates.findIndex(t => t.id === r.template.id);
        if (i < 0) R.templates.push(r.template); else R.templates[i] = r.template;
        $("#rb-saved").textContent = "Saved";
        renderTemplateList();
      } catch (e) { $("#rb-saved").textContent = "Couldn't save: " + e.message; }
    }, 500);
  }

  function renderTemplateList() {
    const list = $("#rb-templates");
    const games = Object.keys(R.games).filter(k => k !== "any");
    const withT = R.templates;
    let html = withT.map(t => `<button class="tpl${editing && editing.id === t.id ? " on" : ""}" data-open="${t.id}">
      ${t.game !== "any" ? `<img src="assets/games/${gameIcon(t.game)}" alt="">` : icon("live")}
      <span><b>${esc(t.name)}</b><small>${t.blocks.length} block${t.blocks.length === 1 ? "" : "s"} · ${t.blocks.reduce((n, b) => n + b.segments.length, 0)} segments</small></span></button>`).join("");
    const missing = games.filter(g => !withT.some(t => t.game === g));
    if (missing.length) {
      html += `<div class="hd">No template yet</div>` + missing.map(g => `<button class="tpl none" data-new="${g}">
        <img src="assets/games/${gameIcon(g)}" alt=""><span><b>${esc(gameName(g))}</b><small>Run of show starts blank · + make one</small></span></button>`).join("");
    }
    html += `<button class="newtpl" data-new="any">${icon("plus")}New template</button>`;
    list.innerHTML = html;
  }
  const gameIcon = g => ({ lol: "lol.svg", val: "valorant.svg", cod: "cod.png", rl: "rocketleague.png", smash: "smash.png", ow: "overwatch.png" }[g] || "gfx.png");

  function colourDot(colour, path) {
    return `<button class="cdot" style="background:${colour}" data-colour="${path}" title="Text colour in the run of show"></button>`;
  }

  function renderBuilder() {
    if (!R) return;
    if (editing && !R.templates.some(t => t.id === editing.id)) editing = null;
    if (!editing && R.templates.length) {
      const want = R.show && R.show.template_id;
      editing = JSON.parse(JSON.stringify(R.templates.find(t => t.id === want) || R.templates[0]));
    }
    renderTemplateList();
    renderBanner();
    const ed = $("#rb-editor");
    if (!editing) {
      ed.innerHTML = `<div class="rb-none"><h2>No templates yet</h2><p class="mut">A template is tonight's run of show for one game: blocks (Pre-show, Match, Post-show) of segments, each with a length and a text colour. Pick a game on the left to make one.</p></div>`;
      renderTonight();
      return;
    }
    const t = editing;
    const games = Object.entries(R.games).map(([k, n]) => `<option value="${k}"${t.game === k ? " selected" : ""}>${esc(n)}</option>`).join("");
    const bo = [1, 3, 5, 7].map(n => `<option value="${n}"${t.best_of === n ? " selected" : ""}>Best of ${n}</option>`).join("");
    let html = `<div class="rb-title"><input id="rb-name" value="${esc(t.name)}" spellcheck="false">
      <label class="sel">Game <select id="rb-game">${games}</select></label><label class="sel">Series <select id="rb-bo">${bo}</select></label></div>
      <p class="mut small">Blocks group segments. Each segment and block has its own text colour. Fixed segments have a set length; <span style="color:var(--yellow)">game</span> segments last as long as the game does, and everything after them moves when they end. Text can use {{Match.TeamA}}, {{Match.TeamB}}, {{Map.N}}, {{Match.BestOf}}.</p>
      <datalist id="rb-gfx">${((R.engine && R.engine.graphics) || []).map(g => `<option value="${esc(g.name)}">`).join("")}</datalist>`;
    t.blocks.forEach((b, bi) => {
      const total = b.segments.reduce((n, s) => n + (+s.mins || 0), 0);
      html += `<div class="rb-block${b.repeat ? " repeat" : ""}" style="--c:${b.color}">
        <div class="rb-bhead">${colourDot(b.color, `b${bi}`)}<input class="bname" data-b="${bi}" value="${esc(b.name)}" style="color:${b.color}" spellcheck="false"><span class="mut small">block</span>
          <label class="chk" title="Played once per map in the series; stops when a team has won"><input type="checkbox" data-brepeat="${bi}"${b.repeat ? " checked" : ""}> Repeat for each map</label>
          <span class="len">${b.repeat ? "until the series ends" : mmss(total)}</span>
          <span class="acts"><button data-bmove="${bi}:-1" title="Move up">↑</button><button data-bmove="${bi}:1" title="Move down">↓</button><button data-bdel="${bi}" title="Delete block">✕</button></span></div>
        ${b.repeat ? `<div class="rb-rep">↻ Repeat for each map in the series · Best of {{Match.BestOf}} · stops when a team wins</div>` : ""}`;
      b.segments.forEach((s, si) => {
        const p = `${bi}.${si}`;
        html += `<div class="rb-seg">
          ${colourDot(s.color, `s${p}`)}
          <div class="main"><input class="stitle" data-s="${p}" data-k="title" value="${esc(s.title)}" style="color:${s.color}" spellcheck="false">
            <input class="snotes" data-s="${p}" data-k="notes" value="${esc(s.notes)}" placeholder="Notes (what it brings up)" spellcheck="false">
            <input class="sgfx" data-s="${p}" data-k="graphics" value="${esc(s.graphics.join(", "))}" placeholder="Graphics, comma separated (click one in the run of show to put it on Preview)" list="rb-gfx" spellcheck="false"></div>
          <div class="len"><label class="mins"><input type="number" min="0" max="600" step="0.5" data-s="${p}" data-k="mins" value="${s.mins}"> min${s.game ? " (estimate)" : ""}</label>
            <label class="chk" title="Lasts as long as the game: times after it move when it ends"><input type="checkbox" data-s="${p}" data-k="game"${s.game ? " checked" : ""}> Game length</label>
            ${b.repeat ? `<label class="chk" title="Not after the last map of the series"><input type="checkbox" data-s="${p}" data-k="skip_last"${s.skip_last ? " checked" : ""}> Skip after last map</label>` : ""}</div>
          <span class="acts"><button data-smove="${p}:-1" title="Move up">↑</button><button data-smove="${p}:1" title="Move down">↓</button><button data-sdel="${p}" title="Delete segment">✕</button></span></div>`;
      });
      html += `<button class="rb-add" data-sadd="${bi}">${icon("plus")}Segment</button></div>`;
    });
    html += `<div class="row"><button data-badd="0">${icon("plus")}Block</button><button data-badd="1">↻ Repeat block</button>
      <button id="rb-dup">Duplicate template</button><button id="rb-del" class="danger">Delete template</button><span class="mut small" id="rb-saved"></span></div>`;
    ed.innerHTML = html;
    renderTonight();
  }

  function renderBanner() {
    const e = R.engine || {}, show = R.show;
    const m = show && show.match;
    let text;
    if (!e.ok) text = "The GFX Engine isn't reachable, so the Schedule can't be read.";
    else if (!e.schedule.length) text = "No matches in the Schedule yet (Event › Schedule). Tonight's run of show is laid out from the next one.";
    else if (m && (m.team1 || m.team2)) {
      text = `Tonight's next Schedule match is <b>${esc(m.game || gameName(m.game_key) || "")}</b> · <b>${esc([m.team1, m.team2].filter(Boolean).join(" vs "))}</b>${m.best_of ? ` · Bo${m.best_of}` : ""}${m.time ? ` · ${esc(m.time)}` : ""}, so ${show.template_name ? `<b>${esc(show.template_name)}</b> builds the run of show` : "it starts blank (no template for that game)"}.`;
    } else text = "Tonight's run of show is laid out from the next match in the Schedule.";
    $("#rb-banner").innerHTML = `${icon("link")}<span><b class="${R.auto ? "on" : ""}">Auto-apply ${R.auto ? "on" : "off"}.</b> ${text}</span>
      <button id="rb-auto">${R.auto ? "Turn off" : "Turn on"}</button>`;
  }

  function renderTonight() {
    const box = $("#rb-tonight");
    if (!box || !R || box.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
    const show = R.show, segs = (show && show.segments) || [], tl = (show && show.timeline) || [];
    const m = (show && show.match) || {};
    let html = `<h2>Tonight</h2><div class="sub">Live times · ~ = estimated, moves when the game ends</div>
      <div class="li"><span>Match</span><span class="v">${esc([m.team1, m.team2].filter(Boolean).join(" vs ") || "–")}</span></div>
      <div class="li"><span>From Schedule</span><span class="v">${esc([m.date, m.time].filter(Boolean).join(" · ") || "–")}</span></div>
      <div class="li"><span>Template</span><span class="v">${esc((show && show.template_name) || "none (blank)")}</span></div>
      <div class="li"><span>Starts at</span><span class="v"><input id="rb-start" value="${esc(m.time || "")}" placeholder="19:00" size="5"></span></div>
      <div class="tn-list">`;
    let lastBlock = null;
    segs.forEach((s, i) => {
      const t = tl[i] || {};
      if (s.block !== lastBlock) { html += `<div class="ros-block" style="--c:${s.block_color}"><span>${esc(s.block || "")}</span></div>`; lastBlock = s.block; }
      const st = i === show.current ? " now" : i === show.current + 1 ? " next" : i < show.current ? " done" : "";
      html += `<div class="tn${st}"><span class="tm">${t.est_start ? "~" : ""}${t.start ? hm(t.start) : ""}</span><span style="color:${s.color}">${esc(s.title)}</span></div>`;
    });
    html += `</div><div class="row"><button class="k" id="rb-use" ${editing ? "" : "disabled"}>Use ${editing ? "“" + esc(editing.name) + "”" : "this template"} tonight</button></div>`;
    box.innerHTML = html;
  }

  // edits
  function seg(path) { const [b, s] = path.split(".").map(Number); return editing.blocks[b].segments[s]; }
  const ed = $("#rb-editor");
  ed.addEventListener("input", e => {
    const el = e.target;
    if (!editing) return;
    if (el.id === "rb-name") editing.name = el.value;
    else if (el.dataset.b !== undefined && el.classList.contains("bname")) editing.blocks[+el.dataset.b].name = el.value;
    else if (el.dataset.s && el.type !== "checkbox") {
      const s = seg(el.dataset.s), k = el.dataset.k;
      s[k] = k === "mins" ? +el.value || 0 : k === "graphics" ? el.value.split(",").map(x => x.trim()).filter(Boolean) : el.value;
    } else return;
    queueSave();
  });
  ed.addEventListener("change", e => {
    const el = e.target;
    if (!editing) return;
    if (el.id === "rb-game") editing.game = el.value;
    else if (el.id === "rb-bo") editing.best_of = +el.value;
    else if (el.dataset.brepeat !== undefined) editing.blocks[+el.dataset.brepeat].repeat = el.checked;
    else if (el.dataset.s && el.type === "checkbox") seg(el.dataset.s)[el.dataset.k] = el.checked;
    else if (el.dataset.k === "mins") { renderBuilder(); queueSave(); return; }
    else return;
    queueSave();
    renderBuilder();
  });
  ed.addEventListener("click", e => {
    const b = e.target.closest("button");
    if (!b || !editing) return;
    const d = b.dataset, T = editing;
    const move = (arr, i, by) => { const j = i + by; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; };
    if (d.colour) return pickColour(b, d.colour);
    if (d.bmove) { const [i, by] = d.bmove.split(":").map(Number); move(T.blocks, i, by); }
    else if (d.bdel) { if (!confirmBox(`Delete the block “${T.blocks[+d.bdel].name}” and its segments?`)) return; T.blocks.splice(+d.bdel, 1); }
    else if (d.smove) { const [p, by] = d.smove.split(":"); const [bi, si] = p.split(".").map(Number); move(T.blocks[bi].segments, si, +by); }
    else if (d.sdel) { const [bi, si] = d.sdel.split(".").map(Number); T.blocks[bi].segments.splice(si, 1); }
    else if (d.sadd !== undefined) T.blocks[+d.sadd].segments.push({ id: uid(), title: "New segment", notes: "", color: "#ffffff", mins: 5, game: false, skip_last: false, graphics: [] });
    else if (d.badd !== undefined) {
      const rep = d.badd === "1";
      T.blocks.push({ id: uid(), name: rep ? "Match" : "Block", color: rep ? "#64d2ff" : "#bf5af2", repeat: rep,
        segments: rep ? [{ id: uid(), title: "Map {{Map.N}}", notes: "", color: "#30d158", mins: 40, game: true, skip_last: false, graphics: [] }] : [] });
    } else if (b.id === "rb-dup") {
      const copy = JSON.parse(JSON.stringify(T));
      copy.id = uid(); copy.name = T.name + " (copy)";
      editing = copy;
    } else if (b.id === "rb-del") {
      if (!confirmBox(`Delete the template “${T.name}”?`)) return;
      const id = T.id; editing = null;
      send("/api/ros/template/delete", { id });
      return;
    } else return;
    queueSave();
    renderBuilder();
  });
  function confirmBox(msg) { try { return window.confirm(msg); } catch (e) { return true; } }

  // colour swatches
  let colourFor = null;
  function pickColour(btn, path) {
    const pop = $("#rb-colours");
    colourFor = path;
    pop.innerHTML = R.colours.map(c => `<button style="background:${c}" data-c="${c}"></button>`).join("") + `<input type="color" title="Any colour">`;
    const r = btn.getBoundingClientRect();
    pop.style.left = r.left + "px"; pop.style.top = r.bottom + 6 + "px";
    pop.hidden = false;
  }
  function setColour(c) {
    if (!editing || !colourFor) return;
    if (colourFor[0] === "b") editing.blocks[+colourFor.slice(1)].color = c;
    else seg(colourFor.slice(1)).color = c;
    queueSave();
    renderBuilder();
  }
  $("#rb-colours").addEventListener("click", e => { const b = e.target.closest("[data-c]"); if (b) { setColour(b.dataset.c); $("#rb-colours").hidden = true; } });
  $("#rb-colours").addEventListener("change", e => { if (e.target.type === "color") { setColour(e.target.value); $("#rb-colours").hidden = true; } });
  document.addEventListener("click", e => { if (!e.target.closest("#rb-colours") && !e.target.closest("[data-colour]")) $("#rb-colours").hidden = true; });

  $("#rb-templates").addEventListener("click", async e => {
    const open = e.target.closest("[data-open]"), nw = e.target.closest("[data-new]");
    if (open) openTemplate(open.dataset.open);
    if (nw) {
      const r = await api("/api/ros/template/new", { game: nw.dataset.new, best_of: 3 }).catch(err => alertBox(err.message));
      if (!r) return;
      R.templates.push(r.template);
      editing = JSON.parse(JSON.stringify(r.template));
      renderBuilder();
    }
  });
  $("#rb-banner").addEventListener("click", e => { if (e.target.id === "rb-auto") send("/api/ros/auto", { on: !R.auto }); });
  $("#rb-tonight").addEventListener("click", async e => {
    if (e.target.id === "rb-use" && editing) {
      clearTimeout(saveTimer);
      await api("/api/ros/template", { template: editing }).catch(() => {});
      send("/api/ros/apply", { template_id: editing.id });
    }
  });
  $("#rb-tonight").addEventListener("change", e => { if (e.target.id === "rb-start") send("/api/ros/show", { start: e.target.value.trim() }); });

  // --- shown / hidden -----------------------------------------------------------------

  function show(where, on) {
    const was = visible[where];
    visible[where] = on;
    if (on && !was) { load().then(() => { if (where === "builder") renderBuilder(); }); }
  }
  setInterval(() => { if (!document.hidden && (visible.panel || visible.builder)) load(); }, 2000);
  return { show, renderPanel };
})();
