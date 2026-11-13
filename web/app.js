// SCC Broadcast Engine: the top bar, Home, Settings and first start.
// Every part (the GFX Engine, each game HUD, HUD Builder, Multistream) shows
// its own pages in a frame under the top bar, from its usual port.
"use strict";

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ICONS = {
  home: '<path d="M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6h-6v6H4a1 1 0 01-1-1z"/>',
  live: '<circle cx="12" cy="12" r="2.5"/><path d="M7.8 7.8a6 6 0 000 8.4M16.2 7.8a6 6 0 010 8.4M5 5a10 10 0 000 14M19 5a10 10 0 010 14"/>',
  cams: '<rect x="2" y="6" width="14" height="12" rx="2"/><path d="M16 10l6-3v10l-6-3z"/>',
  stream: '<path d="M4 12h3l2-6 4 12 2-6h5"/>',
  games: '<rect x="2" y="7" width="20" height="11" rx="5"/><path d="M7 11v3M5.5 12.5h3"/><circle cx="16" cy="11.5" r="1"/><circle cx="18" cy="13.5" r="1"/>',
  composer: '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>',
  builder: '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="10" width="8" height="11" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/>',
  global: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
  teams: '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 19c0-3 2.7-5 6-5s6 2 6 5M15 14.5c3 0 6 1.5 6 4.5"/>',
  bracket: '<path d="M3 5h5v6H3M3 19h5v-6M8 8h4v8H8M12 12h9"/>',
  schedule: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  assets: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
  data: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  transitions: '<rect x="3" y="6" width="9" height="12" rx="1.5"/><rect x="12" y="6" width="9" height="12" rx="1.5" opacity=".5"/><path d="M9 12h7m-2-2l2 2-2 2"/>',
  outputs: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  link: '<path d="M10 14a4 4 0 005.6 0l3-3a4 4 0 00-5.6-5.6l-1 1M14 10a4 4 0 00-5.6 0l-3 3a4 4 0 005.6 5.6l1-1"/>',
  appearance: '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 010 18z" fill="currentColor"/>',
  log: '<path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  hudpc: '<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4M6 13l3-4 3 3 2-2 3 3"/>',
};
const icon = (name, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
function paintIcons(root = document) {
  for (const el of root.querySelectorAll("i[data-i]")) el.outerHTML = icon(el.dataset.i, el.className);
}

// What each game's card shows (its own pages, as in its app today).
const GAME_INFO = {
  lol: { short: "League", tags: ["Live Game", "Champ Select", "Sponsors"] },
  val: { short: "VALORANT", tags: ["Live Game", "Agent Select", "Map Bans"] },
  cod: { short: "Call of Duty", tags: ["Live Game", "Webcams", "Post-game Stats"] },
  rl: { short: "Rocket League", tags: ["Live Game", "Composer HUD"] },
  smash: { short: "Smash", tags: ["Crew Battle", "Stock Reader"] },
  ow: { short: "Overwatch", tags: ["Match", "Map Bans", "Stats"] },
};
const ROLES = [
  { key: "control", icon: "live", name: "Control PC", text: "Runs the GFX Engine: Control, Composer, Event and the OBS outputs. Add the games it reads." },
  { key: "hud", icon: "hudpc", name: "HUD PC", text: "Reads one or more games. Control, Composer and Event open from the Control PC over the network." },
  { key: "stream", icon: "stream", name: "Stream PC", text: "Multistream: OBS streams here once and it goes out to every platform." },
];
const STATUS = { on: ["g", "Running"], starting: ["y", "Starting…"], stopping: ["y", "Stopping…"], error: ["r", "Didn't start"], off: ["", "Off"] };

let S = null;              // the latest /api/state
let route = "home";
const frames = {};         // part key -> iframe
let monFrames = null;      // Home's Preview / Program monitors
let navSeq = 0;            // goes up each time the top bar (or the address) changes page

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
function apply(state) {
  const prev = S;
  S = state;
  if (!prev || prev.settings.background !== S.settings.background || prev.settings.solid_colour !== S.settings.solid_colour) renderBackground();
  render();
}
async function refresh() {
  try { apply(await api("/api/state")); } catch (e) { /* the app is closing */ }
}
async function post(path, body) {
  try { apply(await api(path, body)); } catch (e) { alertBox(e.message); }
}
function alertBox(msg) {
  const el = document.createElement("div");
  el.className = "glass";
  el.style.cssText = "position:fixed;z-index:50;left:50%;top:84px;transform:translateX(-50%);padding:12px 18px;max-width:640px;color:#ffd60a";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 6000);
}
const part = key => S && S.parts.find(p => p.key === key);
const partUrl = p => `http://127.0.0.1:${p.port}${p.entry}`;
const iconSrc = p => p.icon.endsWith(".svg") && !["lol.svg", "valorant.svg"].includes(p.icon) ? "" : `assets/games/${p.icon}`;
function partIcon(p, cls = "") {
  const src = iconSrc(p);
  if (src) return `<img class="${cls}" src="${src}" alt="">`;
  return icon(p.key === "builder" ? "builder" : "stream");
}

// --- routing ----------------------------------------------------------------

function go(r) { if (location.hash !== "#" + r) location.hash = r; else show(); }
addEventListener("hashchange", show);
function show() {
  route = location.hash.slice(1) || "home";
  navSeq++;
  try { localStorage.setItem("sccbe-route", route); } catch (e) { /* private window */ }
  closeMenus();
  render();
}

function render() {
  if (!S) return;
  renderBar();
  document.body.classList.toggle("setup-mode", !S.settings.setup_done);
  if (!S.settings.setup_done) return showView("setup");
  if (route === "setup") route = "home";
  const [head, sub] = route.split("/");
  rosPanel(head === "engine" && (sub || "control") === "control");
  Ros.show("builder", head === "ros");
  if (head === "ros") return showView("ros");
  if (head === "home") return showView("home");
  if (head === "settings") { showView("settings"); if (sub === "updates") $("#updates").scrollIntoView({ block: "center" }); return; }
  if (head === "engine") return showEngine(sub || "control");
  const p = part(head);
  if (!p) return showView("home");
  if (p.status !== "on") return showOff(p);
  showFrame(p.key, partUrl(p));
}

function showView(name) {
  for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== "v-" + name;
  for (const f of Object.values(frames)) f.hidden = true;
  if (name === "home") renderHome(); else stopMonitors();
  if (name === "settings") renderSettings();
  if (name === "setup") renderSetup();
}

function showFrame(key, url) {
  for (const v of document.querySelectorAll(".view")) v.hidden = true;
  stopMonitors();
  let f = frames[key];
  if (f && f.dataset.base !== url.replace(/#.*$/, "")) { f.remove(); f = null; }
  if (!f) {
    f = document.createElement("iframe");
    f.dataset.base = url.replace(/#.*$/, "");
    f.allow = "camera; microphone; display-capture; autoplay; clipboard-read; clipboard-write; fullscreen";
    f.src = url;
    f.className = key;
    $("#frames").appendChild(f);
    frames[key] = f;
  } else if (f.dataset.seq !== String(navSeq)) {
    f.src = url;   // (only the #tab changes: the page switches tab without reloading)
  }
  f.dataset.seq = String(navSeq);
  for (const [k, other] of Object.entries(frames)) other.hidden = k !== key;
}

function showEngine(tab) {
  const e = S.engine, p = part("engine");
  if (!e.base) {
    return showOffView(p, "No GFX Engine on this PC",
      "Switch the GFX Engine on here, or (on a HUD PC) enter the Control PC's address so Control, Composer and Event open from it.",
      [["Switch on the GFX Engine here", () => post("/api/part", { key: "engine", on: true }), true], ["Enter the Control PC", () => go("settings")]]);
  }
  if (!e.remote && p.status !== "on") return showOff(p);
  showFrame("engine", `${e.base}/control#${tab}`);
}

function showOff(p) {
  const st = p.status;
  if (st === "starting" || st === "stopping") return showOffView(p, p.title, st === "starting" ? "Starting…" : "Stopping…", []);
  if (st === "error") {
    return showOffView(p, p.title, p.error, [["Try again", () => post("/api/part/restart", { key: p.key }), true], ["Settings", () => go("settings")]], true);
  }
  showOffView(p, p.title, `${p.title} is switched off on this PC.`,
    [[`Switch on ${p.title}`, () => post("/api/part", { key: p.key, on: true }), true]]);
}
function showOffView(p, title, text, actions, err) {
  showView("off");
  $("#off-icon").src = p ? (iconSrc(p) || "assets/logo.png") : "assets/logo.png";
  $("#off-title").textContent = title;
  $("#off-text").textContent = text;
  $("#off-text").className = err ? "err" : "";
  const box = $("#off-actions");
  box.innerHTML = "";
  for (const [label, fn, k] of actions) {
    const b = document.createElement("button");
    b.textContent = label;
    if (k) b.className = "k";
    b.onclick = fn;
    box.appendChild(b);
  }
}

// --- top bar ------------------------------------------------------------------

function renderBar() {
  const [head, sub] = route.split("/");
  const navKey = head === "engine" ? (["control", "cameras"].includes(sub) ? route : head + "/menu") : head;
  for (const t of document.querySelectorAll("#nav [data-go]")) t.classList.toggle("on", t.dataset.go === navKey);
  const games = S.parts.filter(p => p.kind === "game");
  $('[data-menu="games"]').classList.toggle("on", games.some(g => g.key === head));
  $('[data-menu="build"]').classList.toggle("on", head === "builder" || (head === "engine" && ["composer", "assets", "transitions"].includes(sub)));
  $('[data-menu="event"]').classList.toggle("on", head === "ros" || (head === "engine" && ["global", "teams", "tournament", "schedule"].includes(sub)));
  $('[data-menu="system"]').classList.toggle("on", head === "settings" || (head === "engine" && ["outputs", "data", "appearance", "home"].includes(sub)));
  renderWorkspaceChip(head);
  fitBar();
  $("#chip-settings").classList.toggle("on", head === "settings");
  const anyGame = games.find(g => g.status === "on");
  $("#d-games").className = "d" + (anyGame ? " g" : games.some(g => g.status === "error") ? " r" : "");
  const st = part("stream");
  $("#d-stream").className = "d" + (st.status === "on" ? " g" : st.status === "error" ? " r" : "");

  const e = S.engine, chip = $("#chip-engine");
  const [cls, word] = !e.base ? ["", "off"] : e.ok ? (e.program && e.program.length ? ["g", "on air"] : ["g", e.remote ? "Control PC" : "ready"])
    : part("engine").status === "starting" ? ["y", "starting"] : ["r", e.remote ? "can't reach" : "not running"];
  chip.querySelector(".dot").className = "dot " + cls;
  chip.querySelector("b").textContent = word;
  chip.title = e.base ? `The GFX Engine at ${e.base}` : "No GFX Engine on this PC";
  const m = e.ok && e.match;
  $("#chip-match").hidden = !m;
  if (m) $("#chip-match b").textContent = `${m.left.short || m.left.name || "Left"} ${m.left.score} – ${m.right.score} ${m.right.short || m.right.name || "Right"}`;
  const up = S.update;
  $("#chip-update").hidden = !up.available;
  $("#chip-update").textContent = up.status === "downloading" ? `Updating ${up.progress}%` : `Update to ${up.latest}`;

  renderGamesMenu(games);
  const b = part("builder");
  $("#st-builder").innerHTML = statusHtml(b);
}

function statusHtml(p) {
  const [c, w] = STATUS[p.status] || STATUS.off;
  return `<span class="dot ${c}"></span>${w}`;
}

function renderGamesMenu(games) {
  const head = route.split("/")[0];
  $("#menu-games").innerHTML = `<div class="hd">Game HUDs</div>` + games.map(g =>
    `<a class="mi${g.key === head ? " on" : ""}${g.status === "off" ? " off" : ""}" href="#${g.key}">${partIcon(g)}${esc(g.title)}<span class="st">${statusHtml(g)}</span></a>`).join("")
    + `<div class="hd"><a href="#settings">Switch games on or off in Settings ›</a></div>`;
}

// --- the run of show on Control, and the workspaces ---------------------------------

let rosOn = false;
function rosPanel(on) {
  // (only when the engine's Control page is what's showing)
  on = on && !!S.engine.base && (S.engine.remote || part("engine").status === "on");
  if (on === rosOn) return;
  rosOn = on;
  $("#ros-panel").hidden = !on;
  document.body.classList.toggle("ros-on", on);
  Ros.show("panel", on);
}

let wsList = null;
function renderWorkspaceChip(head) {
  const chip = $("#chip-ws"), e = S.engine;
  chip.hidden = !(head === "engine" && e.ok);
  if (chip.hidden) return;
  chip.querySelector("b").textContent = e.workspace || "Workspace";
  const pic = chip.querySelector(".wspic");
  const cur = wsList && wsList.workspaces.find(w => w.id === wsList.current);
  const want = cur && cur.picture ? `url("${e.base}/api/workspace-picture/${encodeURIComponent(cur.id)}")` : "";
  if (pic.style.backgroundImage !== want) pic.style.backgroundImage = want;
  if (!wsList) loadWorkspaces();
  fitBar();
}
// When the bar is too narrow for everything, first drop the app name, then
// the labels on the tabs that aren't open (their icons stay).
function fitBar() {
  const bar = $("#bar");
  bar.classList.remove("compact", "icons");
  const nav = $("#nav");
  for (const t of nav.querySelectorAll(".t")) if (!t.title) t.title = t.textContent.replace(/▾/g, "").trim();
  const over = () => bar.scrollWidth > bar.clientWidth + 1 || nav.scrollWidth > nav.clientWidth + 1 ||
    $("#nav").getBoundingClientRect().right > bar.querySelector(".right").getBoundingClientRect().left - 6;
  if (over()) bar.classList.add("compact");
  if (over()) bar.classList.add("icons");
}
async function loadWorkspaces() {
  try { wsList = await api("/api/engine/workspaces"); } catch (e) { wsList = { workspaces: [], current: "" }; }
  renderWorkspaceMenu();
}
function renderWorkspaceMenu() {
  const e = S.engine, ws = (wsList && wsList.workspaces) || [];
  $("#menu-ws").innerHTML = `<div class="hd">Workspaces</div>` + ws.map(w => `<button class="mi${w.id === wsList.current ? " on" : ""}" data-ws="${esc(w.id)}">
      <span class="wspic"${w.picture ? ` style="background-image:url('${e.base}/api/workspace-picture/${encodeURIComponent(w.id)}?v=${Math.round(w.updated || 0)}')"` : ""}>${w.picture ? "" : esc((w.name || "?").slice(0, 1))}</span>
      <span class="wsn">${esc(w.name)}<small>${w.graphics || 0} graphics</small></span>${w.id === wsList.current ? `<span class="st">open</span>` : ""}</button>`).join("")
    + `<a class="mi" href="#engine/home">${icon("settings")}Manage workspaces<span class="st">new, rename, picture</span></a>`;
}
$("#menu-ws").addEventListener("click", async ev => {
  const b = ev.target.closest("[data-ws]");
  if (!b) return;
  closeMenus();
  if (b.dataset.ws === wsList.current) return;
  try { wsList = await api("/api/engine/workspace", { id: b.dataset.ws }); renderWorkspaceMenu(); refresh(); }
  catch (err) { alertBox(err.message); }
});

function closeMenus() { for (const m of document.querySelectorAll(".menu")) m.hidden = true; }
for (const b of document.querySelectorAll("[data-menu]")) {
  b.addEventListener("click", e => {
    e.stopPropagation();
    const menu = $("#menu-" + b.dataset.menu), open = menu.hidden;
    closeMenus();
    if (!open) return;
    if (b.dataset.menu === "ws") loadWorkspaces();
    const r = b.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(r.left, innerWidth - 320)) + "px";
    menu.hidden = false;
  });
}
document.addEventListener("click", e => { if (!e.target.closest(".menu")) closeMenus(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenus(); });
for (const m of document.querySelectorAll(".menu")) m.addEventListener("click", e => { if (e.target.closest("a")) closeMenus(); });

// --- Home ---------------------------------------------------------------------

function greeting() {
  const h = new Date().getHours();
  const part = h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  const name = (S.settings.name || "").trim();
  return name ? `${part}, ${name}.` : `${part}.`;
}

function renderHome() {
  $("#greeting").textContent = greeting();
  const games = S.parts.filter(p => p.kind === "game");
  const box = $("#home-games");
  box.innerHTML = games.map(g => {
    const info = GAME_INFO[g.key] || { tags: [] };
    const [c, w] = STATUS[g.status] || STATUS.off;
    const act = g.status === "off" ? `<button data-on="${g.key}">Switch on</button>`
      : g.status === "error" ? `<button data-restart="${g.key}">Try again</button>` : "";
    return `<div class="game glass2 ${g.key}${g.status === "on" ? " on" : ""}${g.status === "off" ? " disabled" : ""}" data-open="${g.key}">
      <span class="st">${c ? `<span class="dot ${c}"></span>` : ""}${w}</span>
      <div class="logo"><img src="assets/games/${g.icon}" alt=""></div>
      <h2>${esc(info.short || g.title)}</h2><p>HUD, readers, cams and engine link</p>
      <div class="tags">${info.tags.map(t => `<span>${esc(t)}</span>`).join("")}</div>
      ${act ? `<div class="act">${act}</div>` : ""}</div>`;
  }).join("");

  const e = S.engine, m = e.ok && e.match;
  const team = (sel, t) => {
    const el = $(sel);
    el.querySelector("b").textContent = t ? (t.name || t.short) : "–";
    const logo = el.querySelector(".logo");
    logo.style.backgroundColor = t && t.color ? t.color : "#2c2c2e";
    logo.style.backgroundImage = t && t.logo ? `url("${t.logo}")` : "none";
  };
  team("#m-left", m && m.left);
  team("#m-right", m && m.right);
  $("#m-score").textContent = m ? `${m.left.score} – ${m.right.score}` : "–";
  $("#m-event").textContent = m ? [m.event, m.stage].filter(Boolean).join(" · ") || "–" : (e.base ? "Engine not reachable" : "No GFX Engine");
  $("#m-format").textContent = m && m.best_of ? `Best of ${m.best_of}` : "–";
  $("#m-ws").textContent = e.ok ? e.workspace || "–" : "–";
  $("#t-pvw").textContent = "Preview" + (e.ok && e.preview.length ? " · " + e.preview.join(", ") : "");
  $("#t-pgm").textContent = "Program" + (e.ok && e.program.length ? " · " + e.program.join(", ") : "");
  startMonitors();

  $("#home-parts").innerHTML = S.parts.filter(p => p.status !== "off" || p.kind !== "game").map(p =>
    `<a class="part-row" href="#${p.key === "engine" ? "engine/control" : p.key}">${partIcon(p)}<span>${esc(p.title)}</span>
      <span class="v">${statusHtml(p)}${p.status === "on" ? ` · ${p.port}` : ""}</span></a>`).join("")
    + (e.remote && e.base ? `<div class="part-row">${icon("link")}<span>Control PC</span><span class="v"><span class="dot ${e.ok ? "g" : "r"}"></span>${esc(e.base.replace(/^https?:\/\//, ""))}</span></div>` : "");
}

function startMonitors() {
  const e = S.engine;
  if (!e.ok) return stopMonitors();
  if (monFrames && monFrames.base === e.base) return;
  stopMonitors();
  monFrames = { base: e.base, els: [] };
  for (const [sel, q] of [["#mon-pvw", "?bus=preview"], ["#mon-pgm", ""]]) {
    const f = document.createElement("iframe");
    f.src = `${e.base}/output${q}`;
    f.tabIndex = -1;
    $(sel).appendChild(f);
    monFrames.els.push(f);
  }
  scaleMonitors();
}
function stopMonitors() {
  if (!monFrames) return;
  for (const f of monFrames.els) f.remove();
  monFrames = null;
}
function scaleMonitors() {
  for (const mon of document.querySelectorAll(".mon")) {
    const f = mon.querySelector("iframe");
    if (f) f.style.transform = `scale(${mon.clientWidth / 1920})`;
  }
}
addEventListener("resize", scaleMonitors);
addEventListener("resize", () => fitBar());

$("#home-games").addEventListener("click", e => {
  const on = e.target.closest("[data-on]"), re = e.target.closest("[data-restart]"), card = e.target.closest("[data-open]");
  if (on) { e.stopPropagation(); post("/api/part", { key: on.dataset.on, on: true }).then(() => go(on.dataset.on)); return; }
  if (re) { e.stopPropagation(); post("/api/part/restart", { key: re.dataset.restart }); return; }
  if (card) go(card.dataset.open);
});

// --- Settings -----------------------------------------------------------------

function roleCards(box, current, onPick) {
  box.innerHTML = ROLES.map(r => `<button class="role${r.key === current ? " on" : ""}" data-role="${r.key}">${icon(r.icon)}<b>${r.name}</b><span>${r.text}</span></button>`).join("");
  for (const b of box.querySelectorAll("[data-role]")) b.onclick = () => onPick(b.dataset.role);
}

const PART_TEXT = {
  engine: "Control, Composer, Event, Cameras and the OBS outputs (port 8782)",
  builder: "Design a HUD for any game (port 8800)",
  stream: "OBS streams here once; it goes out to every platform (port 8775, RTMP 1935)",
};

function renderSettings() {
  const s = S.settings;
  roleCards($("#roles"), s.role, role => post("/api/setup", { role }));
  $("#parts-list").innerHTML = S.parts.map(p => {
    const [c, w] = STATUS[p.status] || STATUS.off;
    const on = !!s.parts[p.key];
    const desc = PART_TEXT[p.key] || `Game HUD (port ${p.port})`;
    return `<div class="part-set"><span class="ic">${partIcon(p)}</span>
      <div class="nm"><b>${esc(p.title)}</b><span>${c ? `<span class="dot ${c}"></span>${w} · ` : ""}${esc(desc)}</span>
      ${p.status === "error" ? `<span class="err">${esc(p.error)}</span>` : ""}</div>
      ${p.status === "on" || p.status === "error" ? `<button class="small" data-restart="${p.key}">Restart</button>` : ""}
      <button class="toggle${on ? " on" : ""}" data-toggle="${p.key}" aria-pressed="${on}" title="${on ? "Switch off" : "Switch on"}"></button></div>`;
  }).join("");
  const cp = $("#control-pc");
  if (document.activeElement !== cp) cp.value = s.control_pc || "";
  const e = S.engine;
  $("#control-pc-status").innerHTML = e.remote
    ? (e.base ? `<span class="dot ${e.ok ? "g" : "r"}"></span> ${e.ok ? "Connected to " + esc(e.base) : "Can't reach " + esc(e.base) + (e.error ? " (" + esc(e.error) + ")" : "")}` : "Not set")
    : "This PC runs its own GFX Engine, so this isn't used.";
  for (const b of document.querySelectorAll("#bg-seg button")) b.classList.toggle("on", b.dataset.bg === s.background);
  const sc = $("#solid-colour");
  if (document.activeElement !== sc) sc.value = s.solid_colour || "#0c0c0e";
  const hn = $("#home-name");
  if (document.activeElement !== hn) hn.value = s.name || "";
  const up = S.update;
  $("#u-version").textContent = S.app.version;
  $("#u-latest").textContent = up.status === "checking" ? "Checking…" : up.check_error ? `Couldn't check (${up.check_error})` : up.latest || "–";
  const ib = $("#u-install");
  ib.hidden = !(up.available && up.can_install) && !["downloading", "installing"].includes(up.status);
  ib.disabled = ["downloading", "installing"].includes(up.status);
  ib.textContent = up.status === "downloading" ? `Downloading ${up.progress}%` : up.status === "installing" ? "Installing…" : `Install ${up.latest}`;
  $("#f-app").textContent = S.app.app_dir;
  $("#f-data").textContent = S.app.data_dir;
}

$("#parts-list").addEventListener("click", e => {
  const t = e.target.closest("[data-toggle]"), r = e.target.closest("[data-restart]");
  if (t) post("/api/part", { key: t.dataset.toggle, on: !t.classList.contains("on") });
  if (r) post("/api/part/restart", { key: r.dataset.restart });
});
$("#save-control-pc").onclick = () => post("/api/settings", { control_pc: $("#control-pc").value });
$("#control-pc").addEventListener("keydown", e => { if (e.key === "Enter") $("#save-control-pc").click(); });
for (const b of document.querySelectorAll("#bg-seg button")) b.onclick = () => post("/api/settings", { background: b.dataset.bg });
$("#solid-colour").addEventListener("change", e => post("/api/settings", { solid_colour: e.target.value }));
$("#home-name").addEventListener("change", e => post("/api/settings", { name: e.target.value }));
$("#u-check").onclick = () => post("/api/update/check", {});
$("#u-install").onclick = () => post("/api/update/install", {});
$("#chip-update").addEventListener("click", () => setTimeout(() => go("settings/updates")));
$("#open-data").onclick = () => post("/api/open-folder", { which: "data" });
$("#open-app").onclick = () => post("/api/open-folder", { which: "app" });

// --- background -----------------------------------------------------------------

function renderBackground() {
  if (!S) return;
  const bg = $("#bg"), v = $("#bg-video"), loop = S.settings.background === "loop";
  document.documentElement.style.setProperty("--bg", S.settings.solid_colour || "#0c0c0e");
  bg.className = "bg " + (loop ? "loop" : "solid");
  if (loop && !v.src) { v.src = "assets/bg-loop.webm"; v.play().catch(() => {}); }
  if (!loop && v.src) { v.pause(); v.removeAttribute("src"); v.load(); }
}

// --- first start ----------------------------------------------------------------

const pick = { role: "control", games: new Set() };
function renderSetup() {
  roleCards($("#setup-roles"), pick.role, role => { pick.role = role; renderSetup(); });
  const games = S.parts.filter(p => p.kind === "game");
  $("#setup-games").innerHTML = games.map(g => `<button class="${pick.games.has(g.key) ? "on" : ""}" data-game="${g.key}"><img src="assets/games/${g.icon}" alt="">${esc((GAME_INFO[g.key] || {}).short || g.title)}</button>`).join("");
  for (const b of $("#setup-games").querySelectorAll("[data-game]")) {
    b.onclick = () => { const k = b.dataset.game; pick.games.has(k) ? pick.games.delete(k) : pick.games.add(k); renderSetup(); };
  }
  $("#setup-controlpc").hidden = pick.role !== "hud";
}
$("#setup-go").onclick = () => {
  const parts = {};
  for (const g of S.parts.filter(p => p.kind === "game")) parts[g.key] = pick.games.has(g.key);
  const body = { role: pick.role, parts };
  if (pick.role === "hud") body.control_pc = $("#setup-control-pc").value;
  post("/api/setup", body).then(() => go("home"));
};

// --- start ------------------------------------------------------------------------

paintIcons();
try { const saved = localStorage.getItem("sccbe-route"); if (!location.hash && saved) history.replaceState(null, "", "#" + saved); } catch (e) { /* private window */ }
route = location.hash.slice(1) || "home";
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 2000);
