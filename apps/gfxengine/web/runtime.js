// The GFX Engine player: draws graphics (compositions of layers) and plays
// them in and out, and the transitions between Preview and Program.
//
// Used by the outputs (output.html), the control panel's thumbnails and
// Composer canvas, and exported HTML graphics.
(function () {
  "use strict";
  const GFX = (window.GFX = {});
  const W = 1920, H = 1080;
  GFX.W = W; GFX.H = H;
  GFX.base = "";          // where assets/ and fonts/ are (another engine, for ?live=)

  const url = p => (!p ? "" : /^(https?:|data:|blob:)/.test(p) ? p : GFX.base + (GFX.base && !p.startsWith("/") ? "/" : "") + p);
  GFX.url = url;

  // --- fonts ------------------------------------------------------------------
  // Fonts that come with the engine, and stand-ins for broadcast fonts that
  // can't (Gotham, Trade Gothic...) until their files are added to the assets.
  const BUILTIN = [
    ["Inter", "fonts/Inter.ttf", "100 900"],
    ["Bebas Neue", "fonts/BebasNeue.ttf", "400"],
    ["Anton", "fonts/Anton-Regular.ttf", "400"],
    // (stands in for Brick, the Smash scoreboard's names, at Brick's size)
    ["Permanent Marker", "fonts/PermanentMarker-Regular.ttf", "400", "size-adjust:80%"],
    ...[400, 500, 700, 800, 900].map(w => ["Montserrat", `fonts/Montserrat-${w}.woff2`, String(w)]),
    ...[500, 600, 700].map(w => ["Barlow Condensed", `fonts/BarlowCondensed-${w}.woff2`, String(w)]),
    ...[700, 900].map(w => ["Vazirmatn", `fonts/Vazirmatn-${w}.woff2`, String(w)]),
    // (the SCC 2026 graphics' font: Footer, Caster, Head to Head...)
    ...[300, 700].map(w => ["Open Sauce One", `fonts/OpenSauceOne-${w}.woff2`, String(w)]),
  ];
  GFX.builtinFonts = ["Inter", "Montserrat", "Barlow Condensed", "Bebas Neue", "Anton", "Permanent Marker", "Vazirmatn", "Open Sauce One"];
  const STANDINS = [
    [/gotham.*(black|ultra)/i, "Montserrat", 900], [/gotham.*bold/i, "Montserrat", 700],
    [/gotham.*medium/i, "Montserrat", 500], [/gotham/i, "Montserrat", 400],
    [/(trade.?gothic|tradegothic).*(cond|cn|20)/i, "Barlow Condensed", 700], [/trade.?gothic/i, "Barlow Condensed", 600],
    [/vazirmatn.*black/i, "Vazirmatn", 900], [/vazirmatn/i, "Vazirmatn", 700],
    [/open.?sauce.*(light|thin|300)/i, "Open Sauce One", 300], [/open.?sauce/i, "Open Sauce One", 700],
    [/anton/i, "Anton", 400], [/brick/i, "Permanent Marker", 400],
    [/redzone|carbon|bebas|impact|oswald/i, "Bebas Neue", 400],
    [/(helvetica|arial|roboto|sf.?pro|segoe).*(black|heavy)/i, "Inter", 900],
    [/(helvetica|arial|roboto|sf.?pro|segoe).*bold/i, "Inter", 700],
  ];
  let assetFonts = new Set();
  let fontStyle = null;
  GFX.loadFonts = function (fonts) {
    fonts = fonts || [];
    const key = JSON.stringify(fonts.map(f => f.path || [f.postscript, f.adobe, f.kit && f.kit.id])) + GFX.base;
    if (fontStyle && fontStyle.dataset.key === key) return;
    // Each font by its PostScript name, then by its other names (its file
    // name, full name...), which a design may know it by; the first claim wins.
    const named = new Map();
    const files = fonts.filter(f => f.path && !f.system);
    for (const f of files) if (f.postscript && !named.has(f.postscript.toLowerCase())) named.set(f.postscript.toLowerCase(), [f.postscript, f]);
    for (const f of files) for (const a of f.aliases || []) if (a && !named.has(a.toLowerCase())) named.set(a.toLowerCase(), [a, f]);
    // Fonts installed on this PC (Windows' Fonts folder...): by their family
    // ("Gotham", each weight its own face) and by every other name a design may
    // know them by ("Gotham-Bold", "Gotham Bold"). The browser finds them by
    // name (local()), else the engine serves the file (OBS on another PC).
    const installed = fonts.filter(f => f.system);
    const builtinLow = new Set(GFX.builtinFonts.map(x => x.toLowerCase()));
    systemFamilies = new Set();
    const familyCss = [];
    for (const f of installed) {
      const fam = (f.family || "").toLowerCase();
      if (!fam || builtinLow.has(fam) || named.has(fam)) continue;
      systemFamilies.add(fam);
      familyCss.push(`@font-face{font-family:"${cssq(f.family)}";src:${systemSrc(f)};font-weight:${f.weight || 400};` +
        `font-style:${f.italic ? "italic" : "normal"};font-display:block}`);
    }
    for (const f of installed) for (const a of [f.postscript, ...(f.aliases || [])]) {
      const low = String(a || "").toLowerCase();
      if (low && !named.has(low) && !systemFamilies.has(low) && !builtinLow.has(low)) named.set(low, [a, f]);
    }
    assetFonts = new Set([...named.keys()]);
    // Adobe Fonts (no files here): ones Creative Cloud installed on this PC,
    // found by name (local()), then the web project's (its CSS from Adobe).
    adobeFonts = new Map();
    const kits = new Set(), adobeCss = [];
    for (const f of fonts) {
      if (!f.adobe) continue;
      const fams = [];
      if (f.local && f.local.length) {
        const fam = "SCC Adobe " + f.postscript;
        adobeCss.push(`@font-face{font-family:"${cssq(fam)}";src:${f.local.map(n => `local("${cssq(n)}")`).join(",")};` +
          `font-weight:${f.weight || 400};font-style:${f.italic ? "italic" : "normal"};font-display:block}`);
        fams.push(fam);
      }
      if (f.kit && f.kit.family) { fams.push(f.kit.family); if (f.kit.id) kits.add(f.kit.id); }
      if (!fams.length) continue;
      const entry = { stack: fams.map(x => `"${cssq(x)}"`).join(", "), weight: (f.kit && f.kit.weight) || f.weight || 400, italic: !!f.italic };
      for (const a of [f.postscript, ...(f.aliases || [])]) if (a && !adobeFonts.has(fontKey(a))) adobeFonts.set(fontKey(a), entry);
    }
    const css = [...kits].map(id => `@import url("https://use.typekit.net/${encodeURIComponent(id)}.css");`).concat(adobeCss, BUILTIN.map(([fam, file, weight, extra]) =>
      `@font-face{font-family:"${fam}";src:url("${url(file)}");font-weight:${weight};font-display:block${extra ? ";" + extra : ""}}`));
    for (const [name, f] of named.values()) css.push(`@font-face{font-family:"${cssq(name)}";src:${f.system ? systemSrc(f) : `url("${url(encodeURI(f.path))}")`};font-display:block}`);
    css.push(...familyCss);
    if (!fontStyle) { fontStyle = document.createElement("style"); document.head.appendChild(fontStyle); }
    fontStyle.dataset.key = key;
    fontStyle.textContent = css.join("\n");
    if (document.fonts) document.fonts.ready.then(() => GFX.refit());
  };
  const cssq = s => String(s).replace(/["\\]/g, "");
  // An installed font: by its names on this PC, then its file from the engine.
  const systemSrc = f => (f.local || []).map(n => `local("${cssq(n)}")`)
    .concat(f.path ? [`url("${url(encodeURI(f.path))}")`] : []).join(",");
  let systemFamilies = new Set();
  const fontKey = s => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  let adobeFonts = new Map();
  // [font-family stack, weight] for a text layer.
  GFX.fontFor = function (layer) {
    const name = layer.font || "Inter";
    if (assetFonts.has(name.toLowerCase())) return [`"${cssq(name)}", "Inter", sans-serif`, "normal"];
    const adobe = adobeFonts.get(fontKey(name));
    if (adobe) {
      // (where the font can't load, e.g. another PC without it: the usual stand-in)
      const st = STANDINS.find(([re]) => re.test(name));
      return [`${adobe.stack}, ${st ? `"${st[1]}", ` : ""}"Inter", sans-serif`, adobe.weight, adobe.italic];
    }
    if (GFX.builtinFonts.includes(name)) return [`"${name}", "Inter", sans-serif`, layer.weight || 400];
    for (const [re, fam, weight] of STANDINS) if (re.test(name)) return [`"${cssq(name)}", "${fam}", "Inter", sans-serif`, weight];
    return [`"${cssq(name)}", "Inter", sans-serif`, layer.weight || 400];
  };
  GFX.hasFont = name => assetFonts.has(String(name || "").toLowerCase()) || systemFamilies.has(String(name || "").toLowerCase()) ||
    adobeFonts.has(fontKey(name)) || GFX.builtinFonts.includes(name);

  // --- data and fields -----------------------------------------------------------
  const ctx = { tables: {} };
  GFX.setData = function (tables) { ctx.tables = tables || {}; GFX.retext(); tickRotators(); redrawBrackets(); reshow(); };
  // The engine's clock (seconds), so every output changes sponsor at the same moment.
  let clockOffset = 0;
  GFX.setClock = function (engineNow) { if (engineNow) clockOffset = engineNow * 1000 - Date.now(); };
  GFX.now = () => Date.now() + clockOffset;

  const colIndex = s => [...s.toUpperCase()].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0) - 1;
  GFX.lookup = function (rows, ref) {
    ref = ref.trim();
    let m = /^([A-Za-z]{1,3})(\d{1,5})$/.exec(ref);
    if (m) { const r = rows[+m[2] - 1]; return (r && r[colIndex(m[1])]) || ""; }
    m = /^(.*)#\s*(\d+)$/.exec(ref);
    if (m && rows.length) {
      const c = rows[0].findIndex(h => h.trim().toLowerCase() === m[1].trim().toLowerCase());
      if (c >= 0) { const r = rows[+m[2]]; return (r && r[c]) || ""; }
    }
    const row = rows.find(r => r[0] && r[0].trim().toLowerCase() === ref.toLowerCase());
    return row ? row[1] || "" : "";
  };
  const pad = n => String(n).padStart(2, "0");
  function token(t) {
    const now = new Date();
    const low = t.toLowerCase();
    if (low === "time") { const h = now.getHours() % 12 || 12; return `${pad(h)}:${pad(now.getMinutes())} ${now.getHours() < 12 ? "AM" : "PM"}`; }
    if (low === "time24") return `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    if (low === "date") return now.toLocaleDateString(undefined, { weekday: "short", month: "numeric", day: "numeric" }).toUpperCase();
    if (low === "clock") {
      // Global's clock: the time of day, or the countdown for Starting Soon / Be Right Back.
      const g = k => GFX.lookup(ctx.tables.Global || [], k);
      const mode = g("Clock mode"), until = g("Clock until");
      if (mode === "soon" || mode === "brb") return until ? token("countdown:" + until) : "00:00";
      return token("time") + (g("Clock zone") ? " " + g("Clock zone") : "");
    }
    if (low === "timer") return GFX.timerText();
    let m = /^countdown:\s*(\d{1,2}):(\d{2})$/i.exec(t);
    if (m) {
      // To a time of day (today, or tomorrow if it's gone).
      const target = new Date(now); target.setHours(+m[1], +m[2], 0, 0);
      let s = Math.max(0, Math.round((target - now) / 1000));
      if (target < now && now - target > 12 * 3600e3) { target.setDate(target.getDate() + 1); s = Math.round((target - now) / 1000); }
      const h = Math.floor(s / 3600);
      return (h ? `${h}:${pad(Math.floor(s / 60) % 60)}` : pad(Math.floor(s / 60))) + `:${pad(s % 60)}`;
    }
    m = /^countdown:\s*([^!]+![^!]+)$/i.exec(t);
    if (m) {
      // To a moment in the data ({{countdown:Run of show!Next map at}}): the
      // engine's time in seconds, or a time of day.
      const v = token(m[1].trim()).trim();
      if (/^\d{1,2}:\d{2}$/.test(v)) return token("countdown:" + v);
      const at = parseFloat(v);
      if (!isFinite(at) || at <= 0) return "00:00";
      const s = Math.max(0, Math.round(at - GFX.now() / 1000)), h = Math.floor(s / 3600);
      return (h ? `${h}:${pad(Math.floor(s / 60) % 60)}` : pad(Math.floor(s / 60))) + `:${pad(s % 60)}`;
    }
    m = /^([^!]+)!(.+)$/.exec(t);
    if (m) {
      const name = Object.keys(ctx.tables).find(k => k.toLowerCase() === m[1].trim().toLowerCase());
      return name ? GFX.lookup(ctx.tables[name], m[2]) : "";
    }
    return "{{" + t + "}}";
  }
  // Global's timer: started, paused, reset and set from Control (or Companion).
  GFX.timerSecs = function () {
    const g = k => GFX.lookup(ctx.tables.Global || [], k);
    const secs = +g("Timer secs") || 0, started = +g("Timer started") || 0, down = !!g("Timer down");
    if (!started) return secs;
    const run = GFX.now() / 1000 - started;
    return down ? Math.max(0, secs - run) : secs + run;
  };
  GFX.timerText = function () {
    // (counting down, 0:04.2 shows 00:05, so 00:00 is when it runs out)
    const v = GFX.timerSecs(), s = GFX.lookup(ctx.tables.Global || [], "Timer down") ? Math.ceil(v - 0.001) : Math.floor(v);
    const h = Math.floor(s / 3600);
    return (h ? `${h}:${pad(Math.floor(s / 60) % 60)}` : pad(Math.floor(s / 60))) + `:${pad(s % 60)}`;
  };
  GFX.resolve = s => String(s == null ? "" : s).replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (_, t) => token(t));
  const hasTokens = s => /\{\{[^{}]+\}\}/.test(String(s || ""));
  const ticking = s => /\{\{\s*(time|time24|date|clock|timer|countdown:[^}]*)\s*\}\}/i.test(String(s || ""));

  // What a layer shows: its field's value if set, else its own.
  GFX.content = function (layer, values) {
    const v = layer.field && values && values[layer.field] != null && values[layer.field] !== "" ? values[layer.field] : null;
    if (layer.type === "text") return v != null ? String(v) : layer.text || "";
    // (a picture or colour can come from the data too: {{Global!Left logo}})
    const own = v != null ? String(v) : (layer.type === "rect" || layer.type === "path" ? layer.fill : layer.src) || "";
    if (SPONSORS.test(own)) return "{{Sponsors}}";
    // (every sponsor in a row: the list is part of the value, so a new list redraws it)
    if (STRIP.test(own)) return "{{Sponsors all}}" + GFX.sponsors().map(x => "|" + (x.white ? "w:" : "c:") + x.logo).join("");
    const out = hasTokens(own) ? GFX.resolve(own).trim() : own;
    // A picture linked to Global with nothing there yet shows the design's own.
    return !out && layer.placeholder ? layer.placeholder : out;
  };

  // --- the sponsors: one after another, each for its own seconds ---------------
  // A picture layer whose file is {{Sponsors}} shows Global's sponsors in turn.
  const SPONSORS = /^\s*\{\{\s*sponsors\s*\}\}\s*$/i;
  const STRIP = /^\s*\{\{\s*sponsors all\s*\}\}\s*$/i;
  GFX.sponsors = function () {
    return (ctx.tables.Sponsors || []).slice(1).filter(r => r[0])
      .map(r => ({ logo: r[0], secs: Math.max(1, +r[1] || 10), epoch: +r[2] || 0, white: r[3] == null || r[3] === "1" }));
  };
  // {index, left (s), secs, list} of the sponsor on now.
  GFX.sponsorNow = function (list) {
    list = list || GFX.sponsors();
    if (!list.length) return { index: -1, left: 0, secs: 0, list };
    const total = list.reduce((n, s) => n + s.secs, 0);
    let t = ((GFX.now() / 1000 - list[0].epoch) % total + total) % total;
    for (let i = 0; i < list.length; i++) {
      if (t < list[i].secs) return { index: i, left: list[i].secs - t, secs: list[i].secs, list };
      t -= list[i].secs;
    }
    return { index: list.length - 1, left: 0, secs: list[list.length - 1].secs, list };
  };
  const rotators = new Set();
  // A picture layer whose file is {{Sponsors all}}: every sponsor side by side,
  // centred, as tall as the box; each white like the design's unless the sponsor
  // is set to keep its colours (or the layer's "mono" is off).
  function sponsorStrip(layer, logos) {
    const box = el("div", "gfx-media gfx-strip", { gap: Math.round(layer.h * 0.7) + "px" });
    for (const item of logos) {
      const white = item.startsWith("w:") && layer.mono !== false, logo = item.slice(2);
      const img = el("img", "", { height: "100%", maxWidth: Math.round(layer.h * 3.2) + "px", objectFit: "contain",
        filter: white ? "brightness(0) invert(1)" : "" });
      img.src = url(encodeURI(logo));
      box.appendChild(img);
    }
    return box;
  }
  function sponsorBox(layer, opts) {
    const box = el("div", "gfx-media gfx-rot");
    box._layer = layer;
    box._opts = opts;
    if (layer.timer) box.appendChild(el("div", "gfx-rot-bar"));
    rotators.add(box);
    turn(box, true);
    return box;
  }
  function turn(box, first) {
    const layer = box._layer, now = GFX.sponsorNow();
    const logo = now.index >= 0 ? now.list[now.index].logo : layer.placeholder || "";
    const key = now.index + "|" + logo;
    const bar = box.querySelector(".gfx-rot-bar");
    if (bar) bar.style.transform = `scaleX(${now.secs ? Math.max(0, now.left / now.secs) : 0})`;
    if (box._key === key) return;
    box._key = key;
    // (layer.mono: each sponsor white unless it's set to keep its colours)
    const white = layer.mono && now.index >= 0 && now.list[now.index].white;
    const img = el("img", "gfx-rot-img", { objectFit: fitOf(layer.fit), filter: white ? "brightness(0) invert(1)" : "" });
    img.draggable = false;
    if (logo) img.src = url(encodeURI(logo));
    const old = [...box.querySelectorAll(".gfx-rot-img")];
    box.insertBefore(img, bar || null);
    if (first || box._opts.still || !old.length) { old.forEach(o => o.remove()); return; }
    if (layer.swap === "fade") {
      // The old one fades out, then the new one fades in.
      for (const o of old) o.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 500, easing: "ease", fill: "forwards" })
        .finished.then(() => o.remove(), () => o.remove());
      img.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 700, delay: 500, easing: "ease", fill: "backwards" });
      return;
    }
    // The old one lifts away, the new one rises into place.
    for (const o of old) o.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(-35%) scale(.92)", filter: "blur(4px)" }],
      { duration: 450, easing: EASE_OUT, fill: "forwards" }).finished.then(() => o.remove(), () => o.remove());
    img.animate([{ opacity: 0, transform: "translateY(35%) scale(.92)", filter: "blur(4px)" }, { opacity: 1, transform: "none", filter: "blur(0)" }],
      { duration: 650, delay: 200, easing: EASE, fill: "backwards" });
  }
  function tickRotators() { for (const b of rotators) { if (!b.isConnected && b._seen) rotators.delete(b); else { if (b.isConnected) b._seen = true; turn(b); } } }
  setInterval(tickRotators, 100);

  // --- building graphics -----------------------------------------------------------
  const live = new Set();   // text elements that change with time or data

  function el(tag, cls, style) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (style) Object.assign(e.style, style);
    return e;
  }

  function buildContent(layer, value, opts) {
    const t = layer.type;
    if (t === "image" && value === "{{Sponsors}}") return sponsorBox(layer, opts);
    if (t === "image" && value.startsWith("{{Sponsors all}}")) return sponsorStrip(layer, value.split("|").slice(1));
    if (t === "video" && layer.tint) return tintedVideo(layer, value, opts);
    if (t === "bracket") return bracketBox(layer);
    if (t === "image" && layer.recolor && value) {
      // A one-colour shape in another colour (from Global): the picture as a mask.
      const m = el("div", "gfx-media gfx-recolor");
      const src = `url("${url(encodeURI(value))}")`, size = { fill: "100% 100%", cover: "cover" }[layer.fit] || "contain";
      Object.assign(m.style, { webkitMaskImage: src, maskImage: src, webkitMaskSize: size, maskSize: size,
        webkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat", webkitMaskPosition: "center", maskPosition: "center" });
      return m;
    }
    if (t === "image" && layer.topThird && value) {
      // Only the top third of the picture (a headshot's face), across the box.
      return el("div", "gfx-media", { backgroundImage: `url("${url(encodeURI(value))}")`, backgroundSize: "auto 300%",
        backgroundPosition: "center top", backgroundRepeat: "no-repeat" });
    }
    // A page of a game HUD (its agent select, its overlay...), live.
    if (t === "web") {
      if (!value) return opts.showHidden ? el("div", "gfx-media", { background: "repeating-linear-gradient(45deg,#2b2f36 0 12px,#22252b 12px 24px)", outline: "2px dashed #5b6270", outlineOffset: "-2px" }) : el("div");
      const f = el("iframe", "gfx-media", { border: "0", background: "transparent", pointerEvents: "none" });
      f.setAttribute("allowtransparency", "true");
      f.setAttribute("scrolling", "no");
      f.src = url(value);
      return f;
    }
    if (t === "image" && layer.tint && value) return tintedImage(layer, value);
    if (t === "image") {
      if (!value) return el("div");
      const img = el("img", "gfx-media", { objectFit: fitOf(layer.fit), objectPosition: POSITIONS[layer.position] || "" });
      img.draggable = false;
      const done = smoothed.get(smoothKey(value, layer));
      img.src = done || url(encodeURI(value));
      if (!done && layer.fit !== "fill" && !/\.(gif|svg)(\?|$)/i.test(value)) img.addEventListener("load", () => smooth(img, layer, value), { once: true });
      return img;
    }
    if (t === "video") {
      if (!value) return el("div");
      const v = el("video", "gfx-media", { objectFit: fitOf(layer.fit) });
      v.src = url(encodeURI(value));
      v.muted = opts.muted || !layer.audio;
      v.loop = layer.loop !== false;
      v.playsInline = true;
      v.preload = "auto";
      if (opts.still) v.addEventListener("loadeddata", () => { try { v.currentTime = Math.min(1, (v.duration || 2) / 2); } catch (e) { /* not seekable */ } }, { once: true });
      else { v.autoplay = true; v.play().catch(() => { v.muted = true; v.play().catch(() => {}); }); }
      return v;
    }
    return buildOther(layer, value, opts);
  }

  // A video in one colour (the background loop): the video in grey, the colour
  // multiplied over it; the layer's blend (screen) lets the board show through
  // its dark parts. Colour, brightness and speed can come from Global.
  function tintedVideo(layer, value, opts) {
    const box = el("div", "gfx-media gfx-tint");
    if (!value) return box;
    const v = el("video", "gfx-media", { objectFit: "cover",
      filter: `grayscale(1) brightness(${+GFX.resolve(layer.brightness ?? 1.6) || 1.6})` });
    v.src = url(encodeURI(value));
    v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto";
    const speed = Math.max(0.1, Math.min(4, +GFX.resolve(layer.speed ?? 1) || 1));
    v.addEventListener("loadedmetadata", () => { v.playbackRate = speed; });
    if (opts.still) v.addEventListener("loadeddata", () => { try { v.currentTime = 2; } catch (e) { /* */ } }, { once: true });
    else { v.autoplay = true; v.play().catch(() => {}); }
    // (the colour only once there's a picture to colour: on its own it would fill the box)
    const tint = el("div", "gfx-media", { background: GFX.resolve(layer.tint) || "#ffffff", mixBlendMode: "multiply", visibility: "hidden" });
    v.addEventListener("loadeddata", () => { tint.style.visibility = ""; });
    v.addEventListener("error", () => { v.remove(); tint.remove(); });
    box.append(v, tint);
    return box;
  }

  // A picture in another colour (the backdrop under the background loop, in
  // the loop's colour): each pixel keeps its light and dark and its alpha, and
  // takes the colour's hue (a grey colour makes it grey). Done once per
  // picture and colour, then kept.
  const tinted = new Map();   // "address|#colour" -> blob address (or a promise of it)
  const lastTint = new Map(); // address -> its last one made (shown while a new colour is made)
  function hexRgb(c) {
    const m = /^#?([0-9a-f]{6})$/i.exec(String(c || "").trim());
    if (!m) return null;
    const n = parseInt(m[1], 16);
    return [n >> 16 & 255, n >> 8 & 255, n & 255];
  }
  function rgbHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
    if (!d) return [0, 0, l];
    const s = d / (1 - Math.abs(2 * l - 1));
    const h = mx === r ? ((g - b) / d + 6) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, s, l];
  }
  function hslRgb(h, s, l) {
    const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = l - c / 2;
    const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
    return [(r + m) * 255, (g + m) * 255, (b + m) * 255];
  }
  GFX.tintPixels = function (px, colour) {
    const rgb = hexRgb(colour);
    if (!rgb) return px;
    const [th, ts] = rgbHsl(...rgb);
    // (a strong colour keeps the picture's own richness; a greyish one greys it)
    const k = Math.min(1, ts * 2);
    for (let i = 0; i < px.length; i += 4) {
      if (!px[i + 3]) continue;
      const [, s, l] = rgbHsl(px[i], px[i + 1], px[i + 2]);
      const out = hslRgb(th, Math.max(s, ts) * k, l);
      px[i] = out[0]; px[i + 1] = out[1]; px[i + 2] = out[2];
    }
    return px;
  };
  function tintSrc(value, colour) {
    const key = value + "|" + colour;
    if (tinted.has(key)) return tinted.get(key);
    const p = new Promise(done => {
      const img = new Image();
      img.onload = () => {
        try {
          const c = document.createElement("canvas");
          c.width = img.naturalWidth; c.height = img.naturalHeight;
          const ctx = c.getContext("2d");
          ctx.drawImage(img, 0, 0);
          const data = ctx.getImageData(0, 0, c.width, c.height);
          GFX.tintPixels(data.data, colour);
          ctx.putImageData(data, 0, 0);
          c.toBlob(b => {
            const u = b ? URL.createObjectURL(b) : url(encodeURI(value));
            if (tinted.size > 60) { for (const [k2, old] of tinted) if (typeof old === "string" && old.startsWith("blob:")) URL.revokeObjectURL(old); tinted.clear(); lastTint.clear(); }
            tinted.set(key, u);
            lastTint.set(value, u);
            done(u);
          }, "image/png");
        } catch (e) { done(url(encodeURI(value))); }   // (can't be read: as it is)
      };
      img.onerror = () => done(url(encodeURI(value)));
      img.src = url(encodeURI(value));
    });
    tinted.set(key, p);
    return p;
  }
  function tintedImage(layer, value) {
    const colour = GFX.resolve(layer.tint);
    const img = el("img", "gfx-media", { objectFit: fitOf(layer.fit), objectPosition: POSITIONS[layer.position] || "" });
    img.draggable = false;
    if (!hexRgb(colour)) { img.src = url(encodeURI(value)); return img; }
    const ready = tintSrc(value, colour);
    if (typeof ready === "string") img.src = ready;
    else {
      // (until it's in its colour: the colour it had, or hidden; never a frame in the design's own)
      const before = lastTint.get(value);
      if (before && before.startsWith("blob:")) img.src = before; else img.style.visibility = "hidden";
      ready.then(u => { img.src = u; img.style.visibility = ""; });
    }
    return img;
  }

  // --- the knockout bracket: drawn from the "Tournament" data, for 8 or 16
  // teams ({{Tournament!Top teams}}), in the layer's box. The first round's
  // slots are gold, the later ones dark, the champion's outlined; a slot shows
  // the team's logo, name and score, and the team that lost is dimmed.
  const brackets = new Set();
  function bracketBox(layer) {
    const box = el("div", "gfx-media gfx-bracket");
    box._layer = layer;
    brackets.add(box);
    drawBracket(box);
    return box;
  }
  function redrawBrackets() {
    for (const b of brackets) { if (!b.isConnected && b._seen) brackets.delete(b); else { if (b.isConnected) b._seen = true; drawBracket(b); } }
  }
  function drawBracket(box) {
    const layer = box._layer;
    const rows = (ctx.tables.Tournament || []).filter(r => /^Top /.test(r[0] || ""));
    const size = +GFX.lookup(rows, "Top teams") === 16 ? 16 : 8;
    const key = JSON.stringify([rows, layer.w, layer.h, layer.font, layer.color, layer.gold, layer.line]);
    if (box._key === key) return;
    box._key = key;
    box.textContent = "";
    const get = k => GFX.lookup(rows, k);
    const Wd = layer.w, Ht = layer.h, rounds = Math.log2(size);
    const sw = Wd * (size === 16 ? 0.17 : 0.196), cw = Wd * (size === 16 ? 0.25 : 0.278);
    const gap = (Wd - rounds * sw - cw) / rounds;
    const unit = Ht / (size / 2);
    const sh = Math.min(Ht * 0.08, unit * 0.34), g = sh / 6;
    const gold = layer.gold || "#b28a1d", dark = layer.dark || "#000b05", line = layer.line || gold;
    const [family, weight] = GFX.fontFor(layer);
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("width", Wd); svg.setAttribute("height", Ht);
    Object.assign(svg.style, { position: "absolute", left: 0, top: 0, overflow: "visible" });
    box.appendChild(svg);
    const path = d => { const p = document.createElementNS(svgNS, "path"); p.setAttribute("d", d); p.setAttribute("fill", "none");
      p.setAttribute("stroke", line); p.setAttribute("stroke-width", Math.max(2, sh / 18)); svg.appendChild(p); };
    function slot(x, y, w, hgt, team, score, fill, lost, big) {
      const s = el("div", "gfx-bk-slot", { left: x + "px", top: y + "px", width: w + "px", height: hgt + "px", background: fill,
        opacity: lost ? 0.5 : 1, fontFamily: family, fontWeight: weight, color: layer.color || "#ffffff" });
      // (Short names: the team list's short name, when it has one)
      const name = (get("Top short names") === "on" && get(team + " short")) || get(team), logo = get(team + " logo");
      const sq = big ? 0 : hgt * 0.67;
      if (logo) {
        const img = el("img", "gfx-bk-logo", { width: hgt * 0.8 + "px", height: hgt * 0.8 + "px", left: hgt * 0.12 + "px", top: hgt * 0.1 + "px" });
        img.src = url(encodeURI(logo));
        s.appendChild(img);
      }
      const left = logo ? hgt * 1.05 : hgt * 0.25;
      const nameBox = el("div", "gfx-bk-name", { left: left + "px", right: sq + hgt * 0.2 + "px", fontSize: hgt * (big ? 0.42 : 0.6) + "px",
        justifyContent: big ? "center" : "flex-start" });
      nameBox.textContent = name;
      s.appendChild(nameBox);
      if (!big) {
        const sc = el("div", "gfx-bk-score", { width: sq + "px", fontSize: hgt * 0.6 + "px" });
        sc.textContent = get(score);
        s.appendChild(sc);
      }
      box.appendChild(s);
      // (too long: narrower)
      requestAnimationFrame(() => { const k = nameBox.clientWidth / (nameBox.scrollWidth || 1); if (k < 1) nameBox.style.fontSize = parseFloat(nameBox.style.fontSize) * Math.max(0.5, k) + "px"; });
    }
    if (get("Top format") === "double") return drawDouble();
    let centres = [];
    for (let r = 0; r < rounds; r++) {
      const n = size >> (r + 1), x = r * (sw + gap), next = [];
      for (let m = 0; m < n; m++) {
        const cy = r === 0 ? unit * (m + 0.5) : (centres[2 * m] + centres[2 * m + 1]) / 2;
        next.push(cy);
        const k = `Top R${r + 1} M${m + 1}`;
        const winner = get(r + 1 < rounds ? `Top R${r + 2} M${(m >> 1) + 1} team ${(m & 1) + 1}` : "Top champion");
        for (let t = 0; t < 2; t++) {
          const team = `${k} team ${t + 1}`;
          const lost = !!winner && !!get(team) && get(team) !== winner;
          slot(x, t ? cy + g / 2 : cy - g / 2 - sh, sw, sh, team, team + " score", r === 0 ? gold : dark, lost);
        }
        if (r + 1 === rounds) path(`M${x + sw + 4} ${cy}H${x + sw + gap - 4}`);   // (on to the champion)
      }
      if (r + 1 < rounds) {
        // The line on to where the winner goes: the next round's matches sit
        // between the two that feed them.
        for (let m = 0; m < n; m++) {
          const cy = next[m], pair = m >> 1, side = m & 1;
          const ny = (next[2 * pair] + next[2 * pair + 1]) / 2;
          const ty = side ? ny + g / 2 + sh / 2 : ny - g / 2 - sh / 2;
          const x1 = x + sw + 4, x2 = x + sw + gap - 4, xm = (x1 + x2) / 2;
          path(`M${x1} ${cy}H${xm}V${ty}H${x2}`);
        }
      }
      centres = next;
    }
    // The champion.
    const cx = rounds * (sw + gap), ch = sh * 2.4, cy = centres[0];
    const frame = el("div", "gfx-bk-champ", { left: cx + "px", top: cy - ch / 2 + "px", width: cw + "px", height: ch + "px",
      borderColor: layer.champ || "#ffc52a", borderWidth: Math.max(2, sh / 14) + "px" });
    box.appendChild(frame);
    const pad = ch * 0.1;
    slot(cx + pad, cy - ch / 2 + pad, cw - 2 * pad, ch - 2 * pad, "Top champion", "", dark, false, true);

    // Double elimination: the upper bracket on top, the lower bracket under
    // it (its rounds in columns, the upper rounds lined up with the lower
    // rounds they drop teams into), then the grand final, its reset and the
    // champion. The same slots, lines and champion frame as the single one.
    function drawDouble() {
      const k = rounds, L = 2 * k - 2, reset = get("Top reset") !== "off";
      const ncols = L + 1 + (reset ? 1 : 0);
      const sw = Wd / (ncols * 1.22 + 1.15), gap = sw * 0.22, cw = sw * 1.15;
      const lh = Math.max(14, Ht * 0.045), sepH = Ht * 0.03;
      const unit = (Ht - 2 * lh - sepH) / (size * 0.75);
      const sh = Math.min(Ht * 0.08, unit * (size === 16 ? 0.36 : 0.42)), g = sh / 6;
      const uTop = lh, lTop = lh + unit * size / 2 + sepH + lh;
      const colX = c => c * (sw + gap);
      const label = (text, x, y, w, align) => {
        const t = el("div", "gfx-bk-label", { left: x + "px", top: y + "px", width: w + "px", height: lh + "px", fontSize: lh * 0.8 + "px",
          fontFamily: family, fontWeight: weight, color: line, justifyContent: align || "flex-start" });
        t.textContent = text;
        box.appendChild(t);
      };
      label("Upper bracket", 0, 0, Wd * 0.5);
      label("Lower bracket", 0, lTop - lh, Wd * 0.5);
      const match = (key, x, cy, fill, unneeded) => {
        const winner = get(`Top ${key} winner`);
        for (let t = 0; t < 2; t++) {
          const team = `Top ${key} team ${t + 1}`;
          const lost = unneeded || (!!winner && !!get(team) && get(team) !== winner);
          slot(x, t ? cy + g / 2 : cy - g / 2 - sh, sw, sh, team, team + " score", fill, lost);
        }
      };
      // (a line from a match on to a slot of a later one)
      const into = (x, cy, tx, ncy, side) => {
        const ty = side ? ncy + g / 2 + sh / 2 : ncy - g / 2 - sh / 2;
        const x1 = x + sw + 4, x2 = tx - 4, xm = x2 - gap / 2 + 4;
        path(`M${x1} ${cy}H${xm}V${ty}H${x2}`);
      };
      // The upper bracket.
      let ucs = [], ucol = 0;
      for (let r = 0; r < k; r++) {
        const n = size >> (r + 1), col = r === 0 ? 0 : 2 * r - 1, x = colX(col), next = [];
        for (let m = 0; m < n; m++) {
          const cy = r === 0 ? uTop + unit * (m + 0.5) : (ucs[2 * m] + ucs[2 * m + 1]) / 2;
          next.push(cy);
          match(`R${r + 1} M${m + 1}`, x, cy, r === 0 ? gold : dark);
        }
        if (r > 0) for (let m = 0; m < ucs.length; m++) into(colX(ucol), ucs[m], x, next[m >> 1], m & 1);
        ucs = next; ucol = col;
      }
      // The lower bracket.
      let lcs = [];
      for (let r = 0; r < L; r++) {
        const n = (size / 4) >> (r >> 1), x = colX(r), next = [];
        const halves = r > 0 && r % 2 === 0;
        for (let m = 0; m < n; m++) {
          const cy = r === 0 ? lTop + unit * (m + 0.5) : halves ? (lcs[2 * m] + lcs[2 * m + 1]) / 2 : lcs[m];
          next.push(cy);
          match(`L${r + 1} M${m + 1}`, x, cy, dark);
        }
        if (r > 0) for (let m = 0; m < lcs.length; m++) into(colX(r - 1), lcs[m], x, halves ? next[m >> 1] : next[m], halves ? m & 1 : 0);
        lcs = next;
      }
      // The grand final (the upper bracket's winner against the lower's), its reset, the champion.
      const gy = (ucs[0] + lcs[0]) / 2, gx = colX(L);
      into(colX(L - 1), ucs[0], gx, gy, 0);
      into(colX(L - 1), lcs[0], gx, gy, 1);
      label("Grand final", gx, gy - g / 2 - sh - lh * 1.15, sw, "center");
      match("GF", gx, gy, dark);
      let last = gx;
      if (reset) {
        const rx = colX(L + 1);
        label("Reset", rx, gy - g / 2 - sh - lh * 1.15, sw, "center");
        path(`M${gx + sw + 4} ${gy}H${rx - 4}`);
        // (dimmed when the upper bracket's team won the grand final: no reset)
        const gfw = get("Top GF winner");
        match("GF2", rx, gy, dark, !!gfw && gfw === get("Top GF team 1"));
        last = rx;
      }
      const cx = colX(ncols), ch = sh * 2.4;
      path(`M${last + sw + 4} ${gy}H${cx - 4}`);
      const frame = el("div", "gfx-bk-champ", { left: cx + "px", top: gy - ch / 2 + "px", width: cw + "px", height: ch + "px",
        borderColor: layer.champ || "#ffc52a", borderWidth: Math.max(2, sh / 14) + "px" });
      box.appendChild(frame);
      const pad = ch * 0.1;
      slot(cx + pad, gy - ch / 2 + pad, cw - 2 * pad, ch - 2 * pad, "Top champion", "", dark, false, true);
    }
  }

  function buildOther(layer, value, opts) {
    const t = layer.type;
    if (t === "lottie") {
      const box = el("div", "gfx-media");
      if (value && window.lottie) {
        const anim = window.lottie.loadAnimation({ container: box, renderer: "svg", loop: layer.loop !== false,
          autoplay: !opts.still, path: url(encodeURI(value)), rendererSettings: { preserveAspectRatio: layer.fit === "fill" ? "none" : layer.fit === "cover" ? "xMidYMid slice" : "xMidYMid meet" } });
        box._lottie = anim;
        if (opts.still) anim.addEventListener("DOMLoaded", () => anim.goToAndStop(Math.floor(anim.totalFrames / 2), true));
      }
      return box;
    }
    if (t === "path") return pathBox(layer, value);
    if (t === "rect" && (layer.shape || layer.fill2 || Array.isArray(layer.radii))) return shapeBox(layer, value);
    if (t === "rect") {
      return el("div", "gfx-rect", {
        background: value || "transparent", borderRadius: (layer.radius || 0) + "px",
        border: layer.strokeWidth ? `${layer.strokeWidth}px solid ${layer.stroke || "#fff"}` : "none",
      });
    }
    if (t === "text") {
      const box = el("div", "gfx-text");
      const [family, weight, italic] = GFX.fontFor(layer);
      Object.assign(box.style, {
        fontFamily: family, fontWeight: weight, fontStyle: layer.italic || italic ? "italic" : "normal",
        fontSize: layer.size + "px", color: layer.color,
        lineHeight: layer.lineHeight || 1.15, letterSpacing: ((layer.tracking || 0) / 1000) + "em",
        textTransform: layer.caps ? "uppercase" : "none", textAlign: layer.align || "left",
        justifyContent: { left: "flex-start", center: "center", right: "flex-end" }[layer.align || "left"],
        alignItems: { top: "flex-start", middle: "center", bottom: "flex-end" }[layer.valign || "top"],
        textShadow: layer.shadow ? "0 2px 8px rgba(0,0,0,.6)" : "none",
        fontVariant: layer.smallCaps ? "small-caps" : "normal",
      });
      const span = el("span", "gfx-t");
      box.appendChild(span);
      textLayout(box, span, layer);
      box._layer = layer;
      box._raw = value;
      setText(box, opts);
      if (!opts.still && (hasTokens(value))) live.add(box);
      // Fitted (and put on its baseline) once it's on the page with its real
      // size, and again whenever it's shown after being hidden.
      if (sized) sized.observe(box);
      return box;
    }
    return el("div");
  }
  const fitOf = f => ({ fill: "fill", contain: "contain", cover: "cover" }[f] || "contain");
  // Where a picture sits in its box when it doesn't fill it (a headshot stands on the bottom).
  const POSITIONS = { top: "50% 0%", bottom: "50% 100%", left: "0% 50%", right: "100% 50%" };

  // A big picture in a small box (a team's logo, say) is scaled down by the
  // browser in one step, which looks jagged: it's resampled once, smoothly, to
  // twice the size it's shown at.
  // (each picture is resampled once, then kept: the next take has it at once)
  const smoothed = new Map();
  const smoothKey = (value, layer) => [value, layer.w, layer.h, layer.fit].join("|");
  function smooth(img, layer, value) {
    const nw = img.naturalWidth, nh = img.naturalHeight;
    const k = layer.fit === "cover" ? Math.max(layer.w / nw, layer.h / nh) : Math.min(layer.w / nw, layer.h / nh);
    if (!nw || !nh || k * 2 >= 0.75 || !window.createImageBitmap) return;
    const w = Math.max(1, Math.round(nw * k * 2)), h = Math.max(1, Math.round(nh * k * 2));
    const key = smoothKey(value, layer);
    createImageBitmap(img, { resizeWidth: w, resizeHeight: h, resizeQuality: "high" }).then(bmp => {
      const c = document.createElement("canvas");
      c.width = w; c.height = h;
      c.getContext("2d").drawImage(bmp, 0, 0);
      bmp.close && bmp.close();
      c.toBlob(b => {
        if (!b) return;
        const u = URL.createObjectURL(b);
        // (swapped in once it's decoded: no blank frame)
        const next = new Image();
        next.src = u;
        (next.decode ? next.decode() : Promise.resolve()).catch(() => {}).then(() => {
          if (smoothed.size > 400) { for (const old of smoothed.values()) URL.revokeObjectURL(old); smoothed.clear(); }
          smoothed.set(key, u);
          warm.set(u, next);
          if (img.isConnected || !img.complete) img.src = u;
        });
      }, "image/png");
    }).catch(() => {});
  }

  // --- pictures kept ready ----------------------------------------------------------
  // Every picture the graphics show is loaded and decoded ahead, and kept in
  // memory, so a graphic taken to air has all of them on its first frame.
  const warm = new Map();      // address -> decoded <img>
  const warmVideos = new Map(); // address -> <video> kept loading
  GFX.warm = function (comps, valuesOf) {
    const want = new Set(), videos = new Set();
    const add = v => { if (v && !/\{\{/.test(v)) want.add(url(encodeURI(v))); };
    for (const s of GFX.sponsors()) add(s.logo);
    for (const comp of comps || []) {
      const values = valuesOf(comp.id) || {};
      for (const layer of comp.layers || []) {
        if (layer.visible === false) continue;
        if (layer.type !== "image" && layer.type !== "video") continue;
        const v = GFX.content(layer, values);
        if (layer.type === "video") { if (v && !/\{\{/.test(v)) videos.add(url(encodeURI(v))); continue; }
        if (v.startsWith("{{Sponsors")) continue;
        if (layer.tint && v && !/\{\{/.test(v) && hexRgb(GFX.resolve(layer.tint))) tintSrc(v, GFX.resolve(layer.tint));
        add(v);
        const done = smoothed.get(smoothKey(v, layer));
        if (done) want.add(done);
      }
    }
    for (const u of want) {
      if (warm.has(u)) continue;
      const img = new Image();
      img.decoding = "async";
      img.src = u;
      img._ready = (img.decode ? img.decode() : new Promise(r => { img.onload = img.onerror = r; })).catch(() => {});
      warm.set(u, img);
    }
    for (const u of [...warm.keys()]) if (!want.has(u)) warm.delete(u);
    // (the few videos, the background loop say, are kept loaded too)
    for (const u of [...videos].slice(0, 8)) {
      if (warmVideos.has(u)) continue;
      const v = document.createElement("video");
      v.muted = true; v.preload = "auto"; v.src = u;
      warmVideos.set(u, v);
    }
    for (const [u, v] of [...warmVideos]) if (!videos.has(u)) { v.removeAttribute("src"); v.load(); warmVideos.delete(u); }
  };
  // Resolves once a graphic's pictures are ready to show (or after `ms`, whatever comes first).
  GFX.ready = function (root, ms) {
    const waits = [];
    root.querySelectorAll("img").forEach(img => {
      if (!img.src) return;
      const kept = warm.get(img.src);
      if (kept) waits.push(kept._ready);
      else if (!img.complete) waits.push(new Promise(r => { img.addEventListener("load", r, { once: true }); img.addEventListener("error", r, { once: true }); }));
      else if (img.decode) waits.push(img.decode().catch(() => {}));
    });
    // (a game HUD's page: loaded before it's shown, a little longer allowed)
    const pages = root.querySelectorAll("iframe");
    pages.forEach(f => waits.push(new Promise(r => { f.addEventListener("load", r, { once: true }); f.addEventListener("error", r, { once: true }); })));
    if (!waits.length) return Promise.resolve();
    return Promise.race([Promise.all(waits), new Promise(r => setTimeout(r, pages.length ? 1500 : ms || 400))]);
  };

  function setText(box, opts) {
    const layer = box._layer;
    const text = GFX.resolve(box._raw);
    // A picture before the text (a player's flag), sized to the letters.
    const icon = layer.icon ? GFX.resolve(layer.icon).trim() : "";
    if (box._shown === text + "\u0000" + icon && !opts) return;
    box._shown = text + "\u0000" + icon;
    const span = box.firstChild;
    if (layer.scroll > 0) {
      // A ticker: the text twice in a row, sliding along forever.
      box.classList.add("gfx-scroll");
      span.textContent = "";
      const a = tickerRun(layer, text), b = tickerRun(layer, text);
      span.append(a, b);
      requestAnimationFrame(() => {
        const w = a.offsetWidth || 1;
        span.getAnimations().forEach(x => x.cancel());
        span.animate([{ transform: "translateX(0)" }, { transform: `translateX(${-w}px)` }],
          { duration: (w / layer.scroll) * 1000, iterations: Infinity });
      });
      return;
    }
    span.textContent = text;
    if (icon && text) {
      const img = el("img", "gfx-icon");
      img.src = url(encodeURI(icon));
      img.onload = () => fit(box);
      span.insertBefore(img, span.firstChild);
    }
    fit(box);
  }

  // One run of a ticker's text. With a divider, the "|" between its lines is
  // drawn as a bar in the divider's colour.
  function tickerRun(layer, text) {
    const run = el("span", "gfx-tick");
    if (!layer.divider) { run.textContent = text; return run; }
    const w = layer.dividerWidth || 6, gap = layer.dividerGap ?? Math.round(layer.size * 1.4);
    text.split(/\s*\|\s*/).forEach((part, i, all) => {
      if (part) run.appendChild(document.createTextNode(part));
      if (i < all.length - 1) run.appendChild(el("i", "gfx-div", { width: w + "px", background: layer.divider, margin: `0 ${gap}px` }));
    });
    return run;
  }

  // A layer shown only while its "show" value has something in it (and isn't 0):
  // the Schedule's matches beyond how many it shows, say.
  const showing = layer => { const v = GFX.resolve(layer.show).trim(); return !!v && v !== "0" && v.toLowerCase() !== "false"; };
  function reshow() {
    document.querySelectorAll(".gfx-L").forEach(L => {
      if (L._layer && L._layer.show) L.style.display = showing(L._layer) ? "" : "none";
      if (L._layer) restyle(L);
      if (L._layer && L._layer.when && !L._edit) toggle(L);
    });
  }

  // --- live data rules: "Show when" and "Fill by" ----------------------------
  // layer.when: [{value: "{{Rocket League HUD!target_has_cam}}", op, to}], all
  // true for the layer to show. When that changes on air the layer plays its
  // own Out animation and hides (a cam box sliding down), or its In animation.
  const truthy = v => { v = String(v == null ? "" : v).trim().toLowerCase(); return !!v && v !== "0" && v !== "false"; };
  const num = v => { const n = parseFloat(String(v).replace(/[^0-9.+-]/g, "")); return isFinite(n) ? n : 0; };
  GFX.test = function (rule) {
    const v = GFX.resolve(rule.value).trim(), to = GFX.resolve(rule.to == null ? "" : rule.to).trim();
    switch (rule.op || "has") {
      case "has": return truthy(v);
      case "empty": return !truthy(v);
      case "is": return v.toLowerCase() === to.toLowerCase();
      case "not": return v.toLowerCase() !== to.toLowerCase();
      case ">=": return num(v) >= num(to);
      case "<=": return num(v) <= num(to);
      case ">": return num(v) > num(to);
      case "<": return num(v) < num(to);
      default: return true;
    }
  };
  GFX.wanted = layer => (Array.isArray(layer.when) ? layer.when : [layer.when]).filter(r => r && r.value).every(GFX.test);
  GFX.RULE_OPS = [["has", "has something"], ["empty", "is empty"], ["is", "is"], ["not", "isn't"],
    [">=", "is at least"], ["<=", "is at most"], [">", "is more than"], ["<", "is less than"]];
  function toggle(L, first) {
    const want = GFX.wanted(L._layer);
    if (L._on === want) return;
    const was = L._on;
    L._on = want;
    // Faded rather than hidden (an empty series box): just the opacity.
    if (L._layer.otherwise === "dim") {
      L.style.visibility = "";
      const to = want ? (L._layer.opacity == null ? 1 : L._layer.opacity) : 0.25;
      if (first || was == null) L.style.opacity = to;
      else L.animate([{ opacity: getComputedStyle(L).opacity }, { opacity: to }], { duration: 250, fill: "forwards" })
        .finished.then(a => { L.style.opacity = to; }, () => {});
      return;
    }
    const inner = L.firstChild;
    if (L._anim) { L._anim.cancel(); L._anim = null; }
    if (first || was == null || !inner) { L.style.visibility = want ? "" : "hidden"; return; }
    const a = (L._layer.anim && L._layer.anim[want ? "in" : "out"]) || { type: "fade", dur: 300 };
    const f = frames(a.type === "none" ? "fade" : a.type, L._layer);
    L.style.visibility = "";
    const run = inner.animate(want ? f : f.slice().reverse(), { duration: Math.max(1, +a.dur || 300),
      easing: want ? EASE : EASE_OUT, fill: want ? "none" : "forwards" });
    L._anim = run;
    run.finished.then(() => { if (L._anim === run) { L._anim = null; if (!want) { L.style.visibility = "hidden"; run.cancel(); } } }, () => {});
  }

  // layer.meter: {value, max, dir: right|left|up|down|ring, start, sweep}:
  // the layer is cut to how full the value is (a boost bar; the boost dial's
  // ring, swept from "start" degrees round by "sweep").
  function meter(L) {
    const m = L._layer.meter, box = L.firstChild && L.firstChild.firstChild;
    if (!m || !m.value || !box) return;
    const raw = GFX.resolve(m.value).trim();
    const max = num(GFX.resolve(m.max == null || m.max === "" ? "100" : m.max)) || 100;
    const k = raw === "" ? (L._edit ? 1 : 0) : Math.max(0, Math.min(1, num(raw) / max));
    const shape = [m.dir, m.start, m.sweep].join("|");
    if (box._k == null || box._shape !== shape) { box._shape = shape; cut(box, m, box._k = k); return; }
    if (Math.abs((box._to != null ? box._to : box._k) - k) < 0.0005) return;
    // (eases from one value to the next, as the game's numbers come in)
    const from = box._k, at = performance.now();
    box._to = k;
    cancelAnimationFrame(box._raf);
    const step = now => {
      const t = Math.min(1, (now - at) / 180);
      cut(box, m, box._k = from + (k - from) * t);
      if (t < 1) box._raf = requestAnimationFrame(step); else box._to = null;
    };
    box._raf = requestAnimationFrame(step);
  }
  function cut(box, m, k) {
    const p = ((1 - k) * 100).toFixed(2) + "%";
    if (m.dir === "ring") {
      const mask = `conic-gradient(from ${+m.start || 0}deg, #000 ${(k * (+m.sweep || 360)).toFixed(2)}deg, transparent 0)`;
      box.style.webkitMaskImage = box.style.maskImage = mask;
    } else {
      box.style.clipPath = { left: `inset(0 0 0 ${p})`, up: `inset(${p} 0 0 0)`, down: `inset(0 0 ${p} 0)` }[m.dir] || `inset(0 ${p} 0 0)`;
    }
  }

  // What a layer's look takes from the data as it changes: its colour
  // ({{Global!Caster primary}}) and where it's moved to ("dx dy scale", around
  // layer.origin on the canvas: the caster boxes, spaced out by how many there are).
  function restyle(L) {
    const layer = L._layer;
    if (layer.move) {
      const [dx, dy, sc] = GFX.resolve(layer.move).trim().split(/\s+/).map(Number);
      const o = layer.origin || [layer.x, layer.y];
      L.style.transformOrigin = `${o[0] - layer.x}px ${o[1] - layer.y}px`;
      L.style.transform = `translate(${dx || 0}px, ${dy || 0}px) scale(${sc || 1})` + (layer.rotation ? ` rotate(${layer.rotation}deg)` : "");
    }
    if (layer.recolor) { const m = L.querySelector(".gfx-recolor"); if (m) m.style.background = GFX.resolve(layer.recolor) || "#ffffff"; }
    if (layer.type === "text" && hasTokens(layer.color)) { const b = L.querySelector(".gfx-text"); if (b) b.style.color = GFX.resolve(layer.color); }
    if (layer.meter) meter(L);
  }

  // Text from a Photoshop file sits on its baseline where Photoshop put it,
  // whatever the font's own spacing above the letters.
  function baseline(box) {
    const layer = box._layer, span = box.firstChild;
    if (!layer || !span || layer.baseline == null || layer.scroll > 0 || (layer.valign || "top") !== "top") return;
    span.style.marginTop = "";
    let mark = span.querySelector(":scope > .gfx-bl");
    if (!mark) { mark = el("i", "gfx-bl"); }
    span.insertBefore(mark, span.firstChild);
    if (!box.isConnected || !box.offsetHeight) return;
    span.style.marginTop = (layer.baseline - mark.offsetTop) + "px";
  }

  // Text that doesn't fit its box: made smaller ("shrink") or narrower ("squeeze").
  function fit(box) {
    fitSize(box);
    baseline(box);
    sizeToText(box);
  }
  // --- text sizing: Figma's Auto width / Auto height / Fixed size, Truncate and Max lines ---
  // (layer.sizing "autoW" | "autoH" | unset = fixed, as before; layer.fit "truncate" + layer.maxLines.
  //  A layer without them draws exactly as it always did.)
  function textLayout(box, span, layer) {
    if (layer.scroll > 0) return;
    const sizing = layer.sizing === "autoW" || layer.sizing === "autoH" ? layer.sizing : "";
    const lines = Math.max(0, Math.round(+layer.maxLines || 0));
    const cut = layer.fit === "truncate" && sizing !== "autoW";
    const wrap = sizing === "autoH" || (cut && lines > 1);
    if (wrap) Object.assign(box.style, { whiteSpace: "pre-wrap", overflowWrap: "break-word" });
    if (wrap || cut) Object.assign(span.style, { maxWidth: "100%", minWidth: "0" });
    if (cut && wrap && lines > 0) {
      Object.assign(span.style, { display: "-webkit-box", webkitBoxOrient: "vertical", webkitLineClamp: String(lines), overflow: "hidden" });
    } else if (cut && !wrap) {
      Object.assign(span.style, { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "pre" });
    }
  }
  // Auto width / height: the layer's box follows its text, on air too (a longer
  // name grows the box instead of shrinking). Auto width keeps the side it's
  // aligned to (the middle when centred); both keep the top.
  function sizeToText(box) {
    const layer = box._layer, span = box.firstChild;
    if (!layer || !span || layer.scroll > 0 || (layer.sizing !== "autoW" && layer.sizing !== "autoH")) return;
    const L = box.closest(".gfx-L");
    if (!L || !box.getClientRects().length) return;
    const h = Math.max(0, span.offsetTop) + span.offsetHeight;
    if (layer.sizing === "autoW") {
      const w = span.offsetWidth;
      const dx = { center: (layer.w - w) / 2, right: layer.w - w }[layer.align || "left"] || 0;
      L.style.width = w + "px";
      L.style.left = (layer.x + dx) + "px";
    }
    L.style.height = h + "px";
  }
  // Where a text layer's text is on the canvas (the editors use it to fit a box to its text).
  GFX.textFrame = (root, layer) => {
    const L = root && [...root.children].find(c => c.dataset.id === layer.id);
    const box = L && L.querySelector(".gfx-text"), span = box && box.firstChild;
    if (!span || !box.getClientRects().length) return null;
    fit(box);   // (sized now, not when the page next lays out)
    let x = 0, y = 0, w = span.offsetWidth, h = span.offsetHeight, n = span;
    while (n && n !== L) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; }
    if (n !== L) return null;
    // (to a fraction of a pixel, from where it's drawn, when it isn't turned)
    const lr = L.getBoundingClientRect(), sr = span.getBoundingClientRect(), k = lr.width / (L.offsetWidth || 1);
    if (!layer.rotation && L.offsetWidth && k > 0 && isFinite(k) && !span.style.transform) {
      x = (sr.left - lr.left) / k; y = (sr.top - lr.top) / k; w = sr.width / k; h = sr.height / k;
    }
    return { x: (parseFloat(L.style.left) || 0) + x, y: (parseFloat(L.style.top) || 0) + y, w, h,
      box: { x: parseFloat(L.style.left) || 0, y: parseFloat(L.style.top) || 0, w: parseFloat(L.style.width) || 0, h: parseFloat(L.style.height) || 0 } };
  };
  // --- end text sizing ---

  function fitSize(box) {
    const layer = box._layer, span = box.firstChild;
    if (!layer || !span || layer.scroll > 0) return;
    span.style.transform = "";
    box.style.fontSize = layer.size + "px";
    if (!layer.fit || layer.fit === "none" || layer.fit === "truncate" || layer.sizing === "autoW" || layer.sizing === "autoH") return;
    const bw = box.clientWidth, bh = box.clientHeight;
    const sw = span.scrollWidth, sh = span.scrollHeight;
    if (!bw || !sw) return;
    if (layer.fit === "squeeze") {
      if (sw > bw) {
        span.style.transform = `scaleX(${bw / sw})`;
        span.style.transformOrigin = { left: "0 50%", center: "50% 50%", right: "100% 50%" }[layer.align || "left"];
      }
      return;
    }
    const k = Math.min(1, bw / sw, sh > bh * 1.05 ? bh / sh : 1);
    if (k < 1) box.style.fontSize = Math.max(layer.size * 0.25, layer.size * k * 0.99) + "px";
  }
  GFX.refit = () => document.querySelectorAll(".gfx-text").forEach(fit);
  const sized = window.ResizeObserver ? new ResizeObserver(entries => {
    for (const e of entries) if (e.contentRect.width && e.target.isConnected) fit(e.target);
  }) : null;
  // A font that finishes loading after the text was fitted: fitted again.
  if (document.fonts && document.fonts.addEventListener) document.fonts.addEventListener("loadingdone", () => GFX.refit());
  GFX.retext = () => document.querySelectorAll(".gfx-text").forEach(b => { if (hasTokens(b._raw) || hasTokens(b._layer && b._layer.icon)) setText(b); });
  setInterval(() => { for (const b of live) { if (!b.isConnected) live.delete(b); else if (ticking(b._raw)) setText(b); } }, 250);   // (often enough that the timer changes on the second)

  // What else a layer's look takes from the data (a tinted loop's colour...).
  const extraOf = layer => [...(layer.tint ? [layer.tint, layer.brightness, layer.speed] : []), layer.zoom].map(v => GFX.resolve(v ?? "")).join("|");

  // Turning round and round for as long as it's on (a vMix title's RotateContinuous):
  // layer.spin = turns a second, minus = anticlockwise. Uses the separate
  // "rotate" property so it adds to the layer's own transform and its In/Out.
  function spin(content, layer, opts) {
    const turns = +layer.spin || 0;
    if (!turns || opts.still || !content.animate) return;
    content.style.transformOrigin = content.style.transformOrigin || "50% 50%";
    content.animate([{ rotate: "0deg" }, { rotate: (turns > 0 ? 360 : -360) + "deg" }],
      { duration: Math.max(100, 1000 / Math.abs(turns)), iterations: Infinity, easing: "linear" });
  }

  // Shapes (HUD Builder's): an ellipse, an angled bar, a gradient, own corners.
  let gradN = 0;
  const colourOf = v => (hasTokens(v) ? GFX.resolve(v).trim() : String(v || "")) || "transparent";
  function paintOf(layer, value) {
    const a = value || "transparent";
    if (!layer.fill2) return a;
    return `linear-gradient(${+layer.gradAngle || 90}deg, ${a}, ${colourOf(layer.fill2)})`;
  }
  function shapeBox(layer, value) {
    const shape = layer.shape || "rect";
    const sw = +layer.strokeWidth || 0, stroke = colourOf(layer.stroke || "#ffffff");
    if (shape === "angled") {
      const NS = "http://www.w3.org/2000/svg", w = layer.w, h = layer.h, k = +layer.skew || 0;
      const svg = document.createElementNS(NS, "svg");
      svg.setAttribute("width", w); svg.setAttribute("height", h);
      svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
      Object.assign(svg.style, { position: "absolute", left: 0, top: 0, width: "100%", height: "100%", overflow: "visible" });
      const pts = k >= 0 ? [[k, 0], [w, 0], [w - k, h], [0, h]] : [[0, 0], [w + k, 0], [w, h], [-k, h]];
      const poly = document.createElementNS(NS, "polygon");
      poly.setAttribute("points", pts.map(p => p.join(",")).join(" "));
      let fill = value || "transparent";
      if (layer.fill2) {
        const id = "gfxg" + (++gradN), g = document.createElementNS(NS, "linearGradient"), rad = ((+layer.gradAngle || 90) - 90) * Math.PI / 180;
        g.setAttribute("id", id);
        g.setAttribute("x1", 0.5 - Math.cos(rad) / 2); g.setAttribute("y1", 0.5 - Math.sin(rad) / 2);
        g.setAttribute("x2", 0.5 + Math.cos(rad) / 2); g.setAttribute("y2", 0.5 + Math.sin(rad) / 2);
        for (const [off, c] of [[0, fill], [1, colourOf(layer.fill2)]]) {
          const st = document.createElementNS(NS, "stop");
          st.setAttribute("offset", off); st.setAttribute("stop-color", c);
          g.appendChild(st);
        }
        const defs = document.createElementNS(NS, "defs");
        defs.appendChild(g); svg.appendChild(defs);
        fill = `url(#${id})`;
      }
      poly.setAttribute("fill", fill);
      if (sw) { poly.setAttribute("stroke", stroke); poly.setAttribute("stroke-width", sw); poly.setAttribute("stroke-linejoin", "round"); }
      svg.appendChild(poly);
      const box = el("div", "gfx-rect");
      box.appendChild(svg);
      return box;
    }
    const r = Array.isArray(layer.radii) ? layer.radii.map(n => (+n || 0) + "px").join(" ") : (layer.radius || 0) + "px";
    return el("div", "gfx-rect", {
      background: paintOf(layer, value), borderRadius: shape === "ellipse" ? "50%" : r,
      border: sw ? `${sw}px solid ${stroke}` : "none", boxSizing: "border-box",
    });
  }
  // --- design tools: vector paths, flips, effects and masks -------------------------
  // (the same block is in the GFX Engine's and HUD Builder's runtime.js)
  // As in Figma and Photoshop: a pen-tool path (layer.type "path"), flipped
  // layers (flipX / flipY), effects (layer.fx: drop shadow, inner glow, layer
  // blur, background blur), a layer mask (the picture layer.mask, inverted
  // with maskInvert; a fade, layer.fade) and clipping masks (layer.clipBelow:
  // shown only inside the shape of the layer under it, Photoshop's Alt-click;
  // that layer's maskOnly: it isn't drawn itself, Figma's "Use as mask").
  // All of it plain CSS and SVG, so OBS's browser source draws it.
  const SVGNS = "http://www.w3.org/2000/svg";
  const paintIn = v => (hasTokens(v) ? GFX.resolve(v).trim() : String(v || "")) || "";
  // A path's points: {x, y, ix, iy, ox, oy} (the handles in and out, where
  // there are any), in a box of layer.vw x layer.vh (stretched to the layer's).
  GFX.pathD = function (pts, closed) {
    if (!Array.isArray(pts) || !pts.length) return "";
    const n = v => Math.round(v * 100) / 100;
    const seg = (a, b) => (a.ox == null && b.ix == null) ? ` L${n(b.x)} ${n(b.y)}`
      : ` C${n(a.ox ?? a.x)} ${n(a.oy ?? a.y)} ${n(b.ix ?? b.x)} ${n(b.iy ?? b.y)} ${n(b.x)} ${n(b.y)}`;
    let d = `M${n(pts[0].x)} ${n(pts[0].y)}`;
    for (let i = 1; i < pts.length; i++) d += seg(pts[i - 1], pts[i]);
    if (closed && pts.length > 2) d += seg(pts[pts.length - 1], pts[0]) + " Z";
    return d;
  };
  let svgN = 0;
  function gradientDef(svg, layer, first) {
    const id = "gfxp" + (++svgN), g = document.createElementNS(SVGNS, "linearGradient"), rad = ((+layer.gradAngle || 90) - 90) * Math.PI / 180;
    g.setAttribute("id", id);
    g.setAttribute("x1", 0.5 - Math.cos(rad) / 2); g.setAttribute("y1", 0.5 - Math.sin(rad) / 2);
    g.setAttribute("x2", 0.5 + Math.cos(rad) / 2); g.setAttribute("y2", 0.5 + Math.sin(rad) / 2);
    for (const [off, c] of [[0, first], [1, paintIn(layer.fill2) || "transparent"]]) {
      const st = document.createElementNS(SVGNS, "stop");
      st.setAttribute("offset", off); st.setAttribute("stop-color", c);
      g.appendChild(st);
    }
    const defs = document.createElementNS(SVGNS, "defs");
    defs.appendChild(g); svg.appendChild(defs);
    return `url(#${id})`;
  }
  function pathBox(layer, value) {
    const box = el("div", "gfx-rect");
    const vw = +layer.vw || layer.w || 1, vh = +layer.vh || layer.h || 1;
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${vw} ${vh}`);
    svg.setAttribute("preserveAspectRatio", "none");
    Object.assign(svg.style, { position: "absolute", left: 0, top: 0, width: "100%", height: "100%", overflow: "visible" });
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("d", GFX.pathD(layer.points, layer.closed));
    let fill = value || "none";
    if (fill !== "none" && layer.fill2) fill = gradientDef(svg, layer, fill);
    p.setAttribute("fill", fill);
    p.setAttribute("fill-rule", layer.evenodd ? "evenodd" : "nonzero");
    const sw = +layer.strokeWidth || 0;
    if (sw) {
      p.setAttribute("stroke", paintIn(layer.stroke) || "#ffffff");
      p.setAttribute("stroke-width", sw);
      p.setAttribute("vector-effect", "non-scaling-stroke");
      p.setAttribute("stroke-linejoin", layer.join || "round");
      p.setAttribute("stroke-linecap", layer.cap || "round");
    }
    svg.appendChild(p);
    box.appendChild(svg);
    return box;
  }
  GFX.blendModes = ["normal", "multiply", "screen", "overlay", "darken", "lighten", "color-dodge", "color-burn",
    "hard-light", "soft-light", "difference", "exclusion", "hue", "saturation", "color", "luminosity", "plus-lighter"];
  // Flips, effects and the layer's own mask, on its content and inner box.
  function design(layer, inner, content) {
    if (layer.flipX || layer.flipY) content.style.scale = `${layer.flipX ? -1 : 1} ${layer.flipY ? -1 : 1}`;
    const filters = [], shadows = [];
    for (const f of Array.isArray(layer.fx) ? layer.fx : []) {
      if (!f || f.off) continue;
      const c = paintIn(f.color) || "rgba(0,0,0,.5)";
      if (f.type === "shadow") filters.push(`drop-shadow(${+f.x || 0}px ${+f.y || 0}px ${Math.max(0, +f.blur || 0)}px ${c})`);
      else if (f.type === "glow") filters.push(`drop-shadow(0 0 ${Math.max(0, +f.blur || 0)}px ${c})`);
      else if (f.type === "blur" && +f.blur > 0) filters.push(`blur(${+f.blur}px)`);
      else if (f.type === "bgblur" && +f.blur > 0) content.style.backdropFilter = content.style.webkitBackdropFilter = `blur(${+f.blur}px)`;
      else if (f.type === "inner") shadows.push(`inset ${+f.x || 0}px ${+f.y || 0}px ${Math.max(0, +f.blur || 0)}px ${+f.spread || 0}px ${c}`);
    }
    if (filters.length) content.style.filter = [content.style.filter, ...filters].filter(Boolean).join(" ");
    if (shadows.length) content.style.boxShadow = shadows.join(", ");
    // The layer mask: the picture (white / opaque shows), turned inside out, and a fade.
    const fade = layer.fade && typeof layer.fade === "object"
      ? `linear-gradient(${+layer.fade.angle || 0}deg, #000 ${+layer.fade.start || 0}%, transparent ${layer.fade.end == null ? 100 : +layer.fade.end}%)` : "";
    if (!fade && !layer.maskInvert) {
      if (layer.mask && !inner.style.webkitMaskImage && !inner.style.maskImage) {
        const m = `url("${url(encodeURI(layer.mask))}")`;
        Object.assign(inner.style, { webkitMaskImage: m, maskImage: m, webkitMaskSize: "100% 100%", maskSize: "100% 100%",
          webkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat" });
      }
      return;
    }
    const imgs = [], sizes = [], webkitOps = [], ops = [];
    if (fade) { imgs.push(fade); sizes.push("100% 100%"); webkitOps.push("source-in"); ops.push("intersect"); }
    if (layer.mask) {
      const m = `url("${url(encodeURI(layer.mask))}")`;
      if (layer.maskInvert) { imgs.push("linear-gradient(#000,#000)"); sizes.push("100% 100%"); webkitOps.push("xor"); ops.push("exclude"); }
      imgs.push(m); sizes.push("100% 100%"); webkitOps.push("source-over"); ops.push("add");
    } else webkitOps[webkitOps.length - 1] = "source-over";
    Object.assign(inner.style, { webkitMaskImage: imgs.join(", "), maskImage: imgs.join(", "), webkitMaskSize: sizes.join(", "), maskSize: sizes.join(", "),
      webkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat", webkitMaskComposite: webkitOps.join(", "), maskComposite: ops.join(", ") });
  }
  // Clipping masks: each layer with clipBelow shows only inside the layer
  // under it that isn't clipped itself (its "base"): a path's, shape's or
  // picture's own shape, else its box. The mask sits on the layer's outer box,
  // so its own In and Out play inside the base (text sliding out from behind a bar).
  const natural = new Map();   // picture address -> [w, h] (or a promise)
  function sizeOf(src, done) {
    const got = natural.get(src);
    if (Array.isArray(got)) return got;
    if (!got) {
      const img = new Image();
      natural.set(src, img);
      img.onload = () => { natural.set(src, [img.naturalWidth, img.naturalHeight]); done(); };
      img.onerror = () => natural.set(src, [0, 0]);
      img.src = src;
    }
    return null;
  }
  function baseShape(B) {
    // The base's shape in the graphic's pixels, as SVG.
    const cx = B.x + B.w / 2, cy = B.y + B.h / 2;
    const t = B.rotation || B.flipX || B.flipY ? ` transform="${B.rotation ? `rotate(${+B.rotation} ${cx} ${cy}) ` : ""}` +
      (B.flipX || B.flipY ? `translate(${cx} ${cy}) scale(${B.flipX ? -1 : 1} ${B.flipY ? -1 : 1}) translate(${-cx} ${-cy})` : "") + `"` : "";
    if (B.type === "path" && Array.isArray(B.points) && B.points.length > 1) {
      const sx = B.w / (+B.vw || B.w || 1), sy = B.h / (+B.vh || B.h || 1), sw = +B.strokeWidth || 0;
      const stroke = sw ? ` stroke="#000" stroke-width="${sw}" vector-effect="non-scaling-stroke" stroke-linejoin="round"` : "";
      const fill = B.closed || paintIn(B.fill) ? "#000" : "none";
      return `<g${t}><path transform="translate(${B.x} ${B.y}) scale(${sx} ${sy})" d="${GFX.pathD(B.points, B.closed)}" fill="${fill}"${stroke}/></g>`;
    }
    if (B.type === "rect" && B.shape === "ellipse") return `<ellipse${t} cx="${B.x + B.w / 2}" cy="${B.y + B.h / 2}" rx="${B.w / 2}" ry="${B.h / 2}"/>`;
    if (B.type === "rect" && B.shape === "angled") {
      const k = +B.skew || 0, pts = k >= 0 ? [[k, 0], [B.w, 0], [B.w - k, B.h], [0, B.h]] : [[0, 0], [B.w + k, 0], [B.w, B.h], [-k, B.h]];
      return `<polygon${t} points="${pts.map(p => (B.x + p[0]) + "," + (B.y + p[1])).join(" ")}"/>`;
    }
    const r = B.type === "rect" ? (Array.isArray(B.radii) ? Math.max(...B.radii.map(n => +n || 0)) : +B.radius || 0) : 0;
    return `<rect${t} x="${B.x}" y="${B.y}" width="${B.w}" height="${B.h}" rx="${Math.min(r, B.w / 2, B.h / 2)}"/>`;
  }
  const MASK_KEYS = ["webkitMaskImage", "maskImage", "webkitMaskSize", "maskSize", "webkitMaskPosition", "maskPosition", "webkitMaskRepeat", "maskRepeat", "webkitMaskComposite", "maskComposite"];
  function setMask(L, m) {
    const sig = JSON.stringify(m || null);
    if (L._clipSig === sig) return;
    L._clipSig = sig;
    for (const k of MASK_KEYS) L.style[k] = "";
    if (!m) return;
    Object.assign(L.style, { webkitMaskImage: m.image, maskImage: m.image, webkitMaskSize: m.size, maskSize: m.size,
      webkitMaskPosition: m.pos, maskPosition: m.pos, webkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat" });
    if (m.comp) { L.style.webkitMaskComposite = m.comp[0]; L.style.maskComposite = m.comp[1]; }
  }
  function clipMasks(root) {
    let base = null, baseEl = null;
    for (const L of root.children) {
      const C = L._layer;
      if (!C) continue;
      if (C.maskOnly) L.style.opacity = 0;
      if (!C.clipBelow) { base = C; baseEl = L; setMask(L, null); continue; }
      if (!base) { setMask(L, null); continue; }
      // (a hidden base hides what's clipped to it, as in Photoshop)
      if (baseEl.style.display === "none" || (base.visible === false && !(root._opts || {}).showHidden)) { setMask(L, { image: "linear-gradient(transparent,transparent)", size: "100% 100%", pos: "0 0" }); continue; }
      const B = base, src = B.type === "image" && baseEl._value && !/^\{\{/.test(baseEl._value) ? url(encodeURI(baseEl._value)) : "";
      if (src && !B.rotation && !C.rotation && !B.flipX && !B.flipY) {
        // A picture: its own alpha, where it's drawn in its box.
        let r = [B.x, B.y, B.w, B.h];
        if (B.fit !== "fill") {
          const n = sizeOf(src, () => clipMasks(root));
          if (!n) { setMask(L, { image: "linear-gradient(transparent,transparent)", size: "100% 100%", pos: "0 0" }); continue; }
          if (n[0] && n[1]) {
            const k = (B.fit === "cover" ? Math.max : Math.min)(B.w / n[0], B.h / n[1]), w = n[0] * k, h = n[1] * k;
            const ax = B.position === "left" ? 0 : B.position === "right" ? 1 : 0.5, ay = B.position === "top" ? 0 : B.position === "bottom" ? 1 : 0.5;
            r = [B.x + (B.w - w) * ax, B.y + (B.h - h) * ay, w, h];
            if (B.fit === "cover") {
              // (cropped to its box: the box's part of the picture)
              const svg = `<svg xmlns="${SVGNS}" viewBox="${C.x} ${C.y} ${C.w} ${C.h}" preserveAspectRatio="none"><rect x="${B.x}" y="${B.y}" width="${B.w}" height="${B.h}"/></svg>`;
              setMask(L, { image: `url("${src}"), url("data:image/svg+xml,${encodeURIComponent(svg)}")`, size: `${w}px ${h}px, 100% 100%`,
                pos: `${r[0] - C.x}px ${r[1] - C.y}px, 0 0`, comp: ["source-in", "intersect"] });
              continue;
            }
          }
        }
        setMask(L, { image: `url("${src}")`, size: `${r[2]}px ${r[3]}px`, pos: `${r[0] - C.x}px ${r[1] - C.y}px` });
        continue;
      }
      // Anything else: its shape (a path, an ellipse...) or its box, drawn in
      // the clipped layer's own box (turned back if that box is turned).
      const t = C.rotation ? ` transform="rotate(${-C.rotation} ${C.x + C.w / 2} ${C.y + C.h / 2})"` : "";
      const svg = `<svg xmlns="${SVGNS}" viewBox="${C.x} ${C.y} ${Math.max(1, C.w)} ${Math.max(1, C.h)}" preserveAspectRatio="none"><g${t}>${baseShape(B)}</g></svg>`;
      setMask(L, { image: `url("data:image/svg+xml,${encodeURIComponent(svg)}")`, size: "100% 100%", pos: "0 0" });
    }
  }
  GFX.clipMasks = clipMasks;

  function buildLayer(layer, values, opts) {
    const value = GFX.content(layer, values);
    const outer = el("div", "gfx-L", {
      left: layer.x + "px", top: layer.y + "px", width: layer.w + "px", height: layer.h + "px",
      opacity: layer.opacity == null ? 1 : layer.opacity,
      transform: layer.rotation ? `rotate(${layer.rotation}deg)` : "",
      mixBlendMode: layer.blend && layer.blend !== "normal" ? layer.blend : "",
    });
    outer.dataset.id = layer.id;
    if (layer.show && !opts.showHidden && !showing(layer)) outer.style.display = "none";
    const inner = el("div", "gfx-A");
    if (layer.mask) {
      // Shown only where a picture is (its alpha, stretched over the layer's box):
      // the background loop in the shape of a bug's boxes.
      const m = `url("${url(encodeURI(layer.mask))}")`;
      Object.assign(inner.style, { webkitMaskImage: m, maskImage: m, webkitMaskSize: "100% 100%", maskSize: "100% 100%",
        webkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat" });
    }
    const content = buildContent(layer, value, opts);
    // Zoomed in (a number, or from the data: {{Global!Bug loop zoom}}), around the middle, kept in the layer's box.
    const zoom = layer.zoom == null ? 1 : +GFX.resolve(String(layer.zoom)) || 1;
    if (zoom !== 1) { inner.style.overflow = "hidden"; content.style.transform = `scale(${zoom})`; content.style.transformOrigin = "50% 50%"; }
    design(layer, inner, content);
    inner.appendChild(content);
    outer.appendChild(inner);
    spin(content, layer, opts);
    outer._value = value;
    outer._extra = extraOf(layer);
    outer._layer = layer;
    outer._sig = JSON.stringify(layer);
    outer._edit = !!opts.showHidden;
    if (layer.move || layer.recolor || layer.meter || hasTokens(layer.color)) restyle(outer);
    if (layer.when && !opts.showHidden) toggle(outer, true);
    return outer;
  }

  // A graphic's element. opts: {still: no playing media (thumbnails),
  // muted, showHidden: include hidden layers (Composer)}.
  GFX.buildComp = function (comp, values, opts) {
    opts = opts || {};
    const root = el("div", "gfx-comp");
    root.dataset.comp = comp.id;
    root.style.zIndex = 10 + (comp.layer || 0);
    for (const layer of comp.layers || []) {
      if (layer.visible === false && !opts.showHidden) continue;
      const L = buildLayer(layer, values, opts);
      if (layer.visible === false) L.style.visibility = "hidden";
      root.appendChild(L);
    }
    root._comp = comp;
    root._values = values;
    root._opts = opts;
    clipMasks(root);
    return root;
  };

  // New values (or an edited graphic) for a graphic already showing:
  // only the layers that change are rebuilt.
  GFX.updateComp = function (root, comp, values) {
    const opts = root._opts || {};
    const existing = new Map([...root.children].map(c => [c.dataset.id, c]));
    const wanted = (comp.layers || []).filter(l => l.visible !== false || opts.showHidden);
    let prev = null;
    for (const layer of wanted) {
      let L = existing.get(layer.id);
      const value = GFX.content(layer, values);
      if (!L || L._sig !== JSON.stringify(layer) || L._value !== value || L._extra !== extraOf(layer)) {
        const fresh = buildLayer(layer, values, opts);
        if (layer.visible === false) fresh.style.visibility = "hidden";
        // (a rule's layer rebuilt with new data: it carries on from where it was)
        if (L && layer.when && !opts.showHidden && L._on !== fresh._on) { fresh._on = L._on; fresh.style.visibility = L.style.visibility; fresh.style.opacity = L.style.opacity; toggle(fresh); }
        if (L) { destroy(L); L.replaceWith(fresh); } else root.insertBefore(fresh, prev ? prev.nextSibling : root.firstChild);
        L = fresh;
      } else if (L.previousSibling !== prev && prev !== L) {
        root.insertBefore(L, prev ? prev.nextSibling : root.firstChild);
      }
      existing.delete(layer.id);
      prev = L;
    }
    for (const L of existing.values()) { destroy(L); L.remove(); }
    clipMasks(root);
    root._comp = comp;
    root._values = values;
    root.style.zIndex = 10 + (comp.layer || 0);
  };

  function destroy(node) {
    node.querySelectorAll(".gfx-media").forEach(m => {
      if (m._lottie) m._lottie.destroy();
      if (m.tagName === "VIDEO") { m.pause(); m.removeAttribute("src"); m.load(); }
    });
  }
  GFX.destroy = destroy;

  // --- animation -----------------------------------------------------------
  const EASE = "cubic-bezier(.2,.8,.2,1)";
  const EASE_OUT = "cubic-bezier(.6,0,.8,.3)";
  // Keyframes for an animation coming in (reversed for going out).
  function frames(type, layer) {
    const d = Math.max(40, Math.min(240, (layer.w || 300) * 0.15));
    const dv = Math.max(30, Math.min(160, (layer.h || 100) * 0.5));
    switch (type) {
      case "fade": return [{ opacity: 0 }, { opacity: 1 }];
      case "slide-left": return [{ opacity: 0, transform: `translateX(${d}px)` }, { opacity: 1, transform: "none" }];
      case "slide-right": return [{ opacity: 0, transform: `translateX(${-d}px)` }, { opacity: 1, transform: "none" }];
      case "slide-up": return [{ opacity: 0, transform: `translateY(${dv}px)` }, { opacity: 1, transform: "none" }];
      case "slide-down": return [{ opacity: 0, transform: `translateY(${-dv}px)` }, { opacity: 1, transform: "none" }];
      case "wipe-right": return [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }];
      case "wipe-left": return [{ clipPath: "inset(0 0 0 100%)" }, { clipPath: "inset(0 0 0 0)" }];
      case "wipe-down": return [{ clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0 0)" }];
      case "wipe-up": return [{ clipPath: "inset(100% 0 0 0)" }, { clipPath: "inset(0 0 0 0)" }];
      case "grow-x": return [{ transform: "scaleX(0)", transformOrigin: "0 50%" }, { transform: "scaleX(1)", transformOrigin: "0 50%" }];
      case "grow-y": return [{ transform: "scaleY(0)", transformOrigin: "50% 100%" }, { transform: "scaleY(1)", transformOrigin: "50% 100%" }];
      case "scale": return [{ opacity: 0, transform: "scale(.85)" }, { opacity: 1, transform: "none" }];
      case "pop": return [{ opacity: 0, transform: "scale(.6)" }, { opacity: 1, transform: "scale(1.06)", offset: .7 }, { opacity: 1, transform: "none" }];
      case "blur": return [{ opacity: 0, filter: "blur(20px)" }, { opacity: 1, filter: "blur(0)" }];
      default: return null;
    }
  }
  GFX.animTypes = ["none", "fade", "slide-left", "slide-right", "slide-up", "slide-down", "wipe-right", "wipe-left",
    "wipe-down", "wipe-up", "grow-x", "grow-y", "scale", "pop", "blur"];

  // Plays a graphic's layers in (or out), `wait` ms from now. Resolves when done.
  GFX.play = function (root, dir, wait) {
    const runs = [];
    for (const L of root.children) {
      const layer = L._layer;
      const a = (layer && layer.anim && layer.anim[dir]) || { type: "fade", dur: 300, delay: 0 };
      const f = frames(a.type, layer || {});
      const inner = L.firstChild;
      if (!f || !inner) { if (dir === "out") inner && (inner.style.opacity = 0); continue; }
      const anim = inner.animate(dir === "in" ? f : f.slice().reverse(), {
        duration: Math.max(1, +a.dur || 300), delay: Math.max(0, +a.delay || 0) + Math.max(0, wait || 0),
        easing: a.ease || (dir === "in" ? EASE : EASE_OUT), fill: "both" });
      runs.push(anim.finished.catch(() => {}));
    }
    return Promise.all(runs);
  };
  GFX.finish = root => root.querySelectorAll(".gfx-A").forEach(a => a.getAnimations().forEach(x => { try { x.finish(); } catch (e) { x.cancel(); } }));

  // --- a bus: the graphics on Program or Preview, kept in step with the engine --
  //
  // opts: {bus: "program" | "preview", comp: one graphic only, monitor: muted,
  //        stingers: play stinger videos (default: yes, except one-graphic outputs)}
  const KIND_RANK = { board: 0, overlay: 1, "lower third": 2 };
  GFX.Bus = class Bus {
    constructor(stage, opts) {
      this.stage = stage;
      this.opts = Object.assign({ bus: "program" }, opts || {});
      this.scene = el("div", "gfx-scene");
      stage.appendChild(this.scene);
      this.shown = new Map();     // comp id -> element
      this.leaving = new Set();
      this.seen = null;            // {rev, take, seq}
      this.stingers = new Map();   // src -> <video>, ready to go
      this.cleanup = [];
    }

    // A graphic's own output that's switched on (Outputs) always shows it,
    // with what it shows on Program (or else on Preview); switched off, nothing.
    always(state) {
      return !!this.opts.comp && ((state.global || {}).outputs_on || []).includes(this.opts.comp);
    }

    wanted(state) {
      const bus = state.live[this.opts.bus] || { on: [], values: {} };
      let on = bus.on || [];
      const comps = new Map(state.project.compositions.map(c => [c.id, c]));
      if (this.opts.comp) {
        const id = this.opts.comp, pg = state.live.program || {}, pv = state.live.preview || {};
        const values = (pg.values || {})[id] || (pv.values || {})[id] || {};
        return { ids: this.always(state) && comps.has(id) ? [id] : [], comps, values: { [id]: values } };
      }
      return { ids: on.filter(id => comps.has(id)), comps, values: bus.values || {} };
    }

    apply(state) {
      // (nothing it shows changed: nothing to do)
      const sig = [state.project, state.live, state.global, state.data, state.fonts];
      if (this.sig && sig.every((v, i) => v === this.sig[i])) return;
      this.sig = sig;
      GFX.loadFonts(state.fonts);
      this.preload(state.project.transitions || []);
      this.warmUp(state);
      const want = this.wanted(state);
      const bus = state.live[this.opts.bus] || {};
      const take = (state.live.take || {}).seq || 0;
      const first = !this.seen;
      const tookNow = !first && this.opts.bus === "program" && take !== this.seen.take;
      const t = (state.live.take || {}).transition || { type: "cut" };
      this.seen = { rev: state.rev, take, seq: bus.seq };
      if (tookNow) {
        // (one graphic's own output doesn't follow takes: it's on while switched on)
        if (!this.opts.comp) return this.transition(want, t, state);
      }
      return this.sync(want, first ? "cut" : this.opts.bus === "preview" ? "cut" : "update");
    }

    // Shows exactly `want`: new graphics in (with mode's effect), gone ones out,
    // the rest updated in place.
    sync(want, mode, t) {
      t = t || {};
      const ids = new Set(want.ids);
      for (const [id, root] of this.shown) {
        if (!ids.has(id)) {
          this.shown.delete(id);
          // (under a stinger: gone at once, it's covered)
          this.out(root, t.animAt ? "cut" : mode, t);
        } else {
          GFX.updateComp(root, want.comps.get(id), want.values[id] || {});
        }
      }
      for (const id of want.ids) {
        if (this.shown.has(id)) continue;
        const root = GFX.buildComp(want.comps.get(id), want.values[id] || {}, { muted: this.opts.monitor });
        this.scene.appendChild(root);
        this.shown.set(id, root);
        // Played in once its pictures are decoded, so it never comes in half drawn.
        root.style.visibility = "hidden";
        GFX.ready(root, 400).then(() => {
          if (this.shown.get(id) !== root) return;
          root.style.visibility = "";
          this.in(root, mode, t);
        });
      }
      // Stacking: the graphic's "layer" setting, then its kind (full-page
      // boards at the back, overlays over them, lower thirds in front), then
      // its place in the list.
      want.ids.forEach((id, i) => {
        const root = this.shown.get(id), comp = want.comps.get(id);
        if (root) root.style.zIndex = 10 + (comp.layer || 0) * 1000 + (KIND_RANK[comp.kind] ?? 1) * 300 + i;
      });
    }

    in(root, mode, t) {
      if (mode === "animate") GFX.play(root, "in", t.animAt ? t.animAt - performance.now() : 0);
      else if (mode === "fade") root.animate([{ opacity: 0 }, { opacity: 1 }], { duration: t.dur || 500, easing: "linear" });
      else if (mode === "wipe") root.animate(wipe(t.direction, true), { duration: t.dur || 600, easing: EASE });
      requestAnimationFrame(() => root.querySelectorAll(".gfx-text").forEach(fit));
    }

    out(root, mode, t) {
      let done;
      this.leaving.add(root);
      if (mode === "animate") done = GFX.play(root, "out");
      else if (mode === "fade") done = root.animate([{ opacity: 1 }, { opacity: 0 }], { duration: t.dur || 500, easing: "linear", fill: "forwards" }).finished;
      else if (mode === "wipe") done = root.animate(wipe(t.direction, false), { duration: t.dur || 600, easing: EASE, fill: "forwards" }).finished;
      else done = Promise.resolve();
      done.catch(() => {}).then(() => { this.leaving.delete(root); destroy(root); root.remove(); });
    }

    // Ends whatever transition is still playing, at once.
    hurry() {
      for (const fn of this.cleanup.splice(0)) fn();
      for (const root of this.leaving) { destroy(root); root.remove(); }
      this.leaving.clear();
      for (const root of this.shown.values()) { root.getAnimations().forEach(a => a.finish()); GFX.finish(root); }
    }

    transition(want, t, state) {
      this.hurry();
      switch (t.type) {
        case "cut": return this.sync(want, "cut");
        case "fade": return this.sync(want, "fade", t);
        case "wipe": return this.sync(want, "wipe", t);
        case "animate": return this.sync(want, "animate", t);
        case "dip": {
          const cover = el("div", "gfx-cover", { background: t.color || "#000", opacity: 0 });
          this.stage.appendChild(cover);
          const half = (t.dur || 800) / 2;
          const a = cover.animate([{ opacity: 0 }, { opacity: 1 }], { duration: half, fill: "forwards" });
          const end = () => { cover.remove(); };
          this.cleanup.push(() => { this.sync(want, "cut"); end(); });
          a.finished.then(() => {
            this.cleanup = this.cleanup.filter(f => f !== end);
            this.sync(want, "cut");
            cover.animate([{ opacity: 1 }, { opacity: 0 }], { duration: half, fill: "forwards" }).finished.then(end, end);
          }, () => {});
          return;
        }
        case "stinger": return this.stinger(want, t, +state.project.stinger_anim_delay || 0);
        case "delay": {
          const timer = setTimeout(() => this.sync(want, "cut"), t.ms || 0);
          this.cleanup.push(() => { clearTimeout(timer); this.sync(want, "cut"); });
          return;
        }
        default: return this.sync(want, "cut");
      }
    }

    // animDelay: the new graphics come in under the stinger and play their
    // intro animations this long (ms) after the TAKE, once it has cleared
    // (0: they just cut in).
    stinger(want, t, animDelay) {
      if (!t.src) return this.sync(want, "cut");
      const animAt = performance.now() + animDelay;
      const v = this.stingerVideo(t.src);
      v.muted = !!this.opts.monitor || t.audio === false;
      v.volume = t.volume == null ? 1 : +t.volume;
      v.currentTime = 0;
      v.style.visibility = "visible";
      let swapped = false;
      const swap = () => { if (!swapped) { swapped = true; animDelay > 0 ? this.sync(want, "animate", { animAt }) : this.sync(want, "cut"); } };
      const cutAt = Math.max(0, +t.cut || 0) / 1000;
      const hide = () => { v.pause(); v.style.visibility = "hidden"; v.removeEventListener("timeupdate", tick); };
      const tick = () => { if (v.currentTime >= cutAt) swap(); };
      // timeupdate fires only ~4 times a second: a timer catches the cut on time.
      const timer = setTimeout(swap, cutAt * 1000 + 30);
      v.addEventListener("timeupdate", tick);
      v.onended = () => { swap(); hide(); };
      this.cleanup.push(() => { clearTimeout(timer); swap(); hide(); });
      const started = v.play();
      if (started) started.catch(() => { v.muted = true; v.play().catch(() => { clearTimeout(timer); swap(); hide(); }); });
    }

    stingerVideo(src) {
      let v = this.stingers.get(src);
      if (!v) {
        v = el("video", "gfx-stinger");
        v.src = url(encodeURI(src));
        v.preload = "auto";
        v.playsInline = true;
        v.muted = true;
        this.stage.appendChild(v);
        this.stingers.set(src, v);
      }
      return v;
    }

    // The pictures of every graphic that could go on air, ready before the take
    // (on Program; a graphic's own output: its pictures).
    warmUp(state) {
      if (this.opts.bus !== "program" || this.warmed === state.project && this.warmedData === state.data && this.warmedLive === state.live) return;
      this.warmed = state.project; this.warmedData = state.data; this.warmedLive = state.live;
      const live = state.live || {}, pg = live.program || {}, pv = live.preview || {};
      const comps = state.project.compositions.filter(c => !this.opts.comp || c.id === this.opts.comp);
      const go = () => { this.warmTimer = null; this.warmAt = performance.now(); GFX.warm(comps, id => Object.assign({}, (pv.values || {})[id], (pg.values || {})[id])); };
      // (the game's data changes many times a second: looked at again every few seconds at most)
      if (this.warmTimer) clearTimeout(this.warmTimer);
      const wait = this.warmAt == null ? 0 : Math.max(250, 3000 - (performance.now() - this.warmAt));
      this.warmTimer = setTimeout(() => (window.requestIdleCallback || setTimeout)(go, { timeout: 1000 }), wait);
    }

    // Stinger videos load before they're needed, so they start on the button.
    preload(transitions) {
      if (this.opts.bus !== "program" || (this.opts.comp && !this.opts.stingers)) return;
      for (const t of transitions) if (t.type === "stinger" && t.src && t.enabled !== false) this.stingerVideo(t.src);
    }
  };

  function wipe(direction, entering) {
    const from = { left: "inset(0 0 0 100%)", right: "inset(0 100% 0 0)", up: "inset(100% 0 0 0)", down: "inset(0 0 100% 0)" }[direction || "left"];
    const to = { left: "inset(0 100% 0 0)", right: "inset(0 0 0 100%)", up: "inset(0 0 100% 0)", down: "inset(100% 0 0 0)" }[direction || "left"];
    return entering ? [{ clipPath: from }, { clipPath: "inset(0 0 0 0)" }] : [{ clipPath: "inset(0 0 0 0)" }, { clipPath: to }];
  }

  // --- styles ---------------------------------------------------------------
  const css = document.createElement("style");
  css.textContent = `
    .gfx-stage{position:relative;width:${W}px;height:${H}px;overflow:hidden}
    .gfx-scene,.gfx-comp{position:absolute;inset:0;pointer-events:none}
    .gfx-L{position:absolute;box-sizing:border-box}
    .gfx-A{position:absolute;inset:0}
    .gfx-media{position:absolute;inset:0;width:100%;height:100%;display:block}
    .gfx-rect{position:absolute;inset:0;box-sizing:border-box}
    .gfx-text{position:absolute;inset:0;display:flex;white-space:pre;overflow:visible}
    .gfx-t{display:inline-block;max-width:none}
    .gfx-scroll{overflow:hidden}
    .gfx-scroll .gfx-t{display:flex;white-space:pre}
    .gfx-tick{display:inline-flex;align-items:center}
    .gfx-media.gfx-strip{display:flex;align-items:center;justify-content:center}
    .gfx-strip img{min-width:0;flex:0 1 auto}
    .gfx-icon{display:inline-block;height:.72em;width:auto;margin-right:.32em;vertical-align:baseline;border-radius:.06em}
    .gfx-div{display:inline-block;height:1.05em;flex:0 0 auto}
    .gfx-tick{padding-right:1.5em}
    .gfx-bl{display:inline-block;width:0;height:0;vertical-align:baseline}
    .gfx-rot{overflow:visible}
    .gfx-rot-img{position:absolute;inset:0;width:100%;height:100%;display:block}
    .gfx-rot-bar{position:absolute;left:0;right:0;bottom:-8px;height:3px;background:currentColor;color:#f5c518;transform-origin:0 50%;opacity:.85}
    .gfx-bracket{overflow:visible}
    .gfx-bk-slot{position:absolute;box-sizing:border-box;overflow:hidden;transition:opacity .4s}
    .gfx-bk-logo{position:absolute;object-fit:contain}
    .gfx-bk-name{position:absolute;top:0;bottom:0;display:flex;align-items:center;white-space:nowrap;text-transform:uppercase;letter-spacing:-.01em;overflow:hidden}
    .gfx-bk-score{position:absolute;right:0;top:0;bottom:0;background:#000;display:flex;align-items:center;justify-content:center}
    .gfx-bk-label{position:absolute;display:flex;align-items:center;white-space:nowrap;text-transform:uppercase;letter-spacing:.04em}
    .gfx-bk-champ{position:absolute;box-sizing:border-box;border-style:solid}
    .gfx-cover{position:absolute;inset:0;z-index:9000}
    .gfx-stinger{position:absolute;inset:0;width:100%;height:100%;z-index:9500;visibility:hidden;object-fit:cover;pointer-events:none}
  `;
  document.head.appendChild(css);
})();
