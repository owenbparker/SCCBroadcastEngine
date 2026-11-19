/* HUD Builder > Game HUDs: changes made to a game HUD, applied over the page.
 *
 * Loaded by every game HUD page:  <script src="/hudedit.js" data-design="KEY"></script>
 * (a page with several looks, like League's profiles, calls HudEdit.setDesign(id)).
 *
 * On air it reads the saved changes (/hudedit/edits) and follows them, so a Save
 * in HUD Builder shows within a second. The HUD's own code and data are never
 * changed: moved / resized / recoloured / hidden parts are CSS over the page,
 * and added boxes, text and pictures sit in layers of their own.
 *
 * Opened by HUD Builder with ?hudedit=1 (in its frame) it is also the editor's
 * hands: picking parts, dragging and resizing them, and saving. HUD Builder
 * talks to it with postMessage ({hudedit: ...}); see apps/hudbuilder/web/gamehuds.js.
 */
(function () {
  "use strict";
  if (window.HudEdit) return;
  var me = document.currentScript;
  var baseKey = (me && me.dataset.design) || ("page" + location.pathname.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
  var params = new URLSearchParams(location.search);
  var editing = params.get("hudedit") === "1" && window.parent !== window;
  var sub = "", rev = -1, edits = blank(), savedJson = JSON.stringify(blank());
  var styleEl = null, front = null, back = null;
  var POLL_MS = 1000;

  function blank() { return { rules: {}, added: [], fonts: [], settings: {} }; }
  function key() { return sub ? baseKey + ":" + sub : baseKey; }
  function asset(name) { return "/hudedit/asset/" + encodeURIComponent(name); }
  function num(v, d) { return typeof v === "number" && isFinite(v) ? v : d; }
  function storeKey() { return "hudedit:" + key(); }

  // --- applying ---------------------------------------------------------------

  function css(ed) {
    var out = [];
    (ed.fonts || []).forEach(function (f) {
      out.push('@font-face{font-family:"' + f.family + '";src:url("' + asset(f.file) + '")}');
    });
    var rules = ed.rules || {};
    Object.keys(rules).forEach(function (sel) {
      var r = rules[sel], d = [], t = [];
      var x = num(r.x, 0), y = num(r.y, 0), sx = num(r.sx, 1), sy = num(r.sy, 1), rot = num(r.rot, 0);
      if (x || y) d.push("translate:" + x + "px " + y + "px");
      if (sx !== 1 || sy !== 1) d.push("scale:" + sx + " " + sy);
      if (rot) d.push("rotate:" + rot + "deg");
      if (r.svg && (sx !== 1 || sy !== 1 || rot)) d.push("transform-box:fill-box", "transform-origin:50% 50%");
      if (r.hide) d.push(editing ? "opacity:.22" : "opacity:0", editing ? "outline:2px dashed rgba(255,80,80,.9)" : "visibility:hidden");
      else if (r.op != null) d.push("opacity:" + r.op);
      if (r.bg) d.push(r.svg ? "fill:" + r.bg : "background-color:" + r.bg);
      if (r.radius != null) d.push("border-radius:" + r.radius + "px");
      if (r.size) d.push("font-size:" + r.size + "px");
      if (r.noanim) d.push("transition:none", "animation:none");
      else {
        if (r.dur != null) d.push("transition-duration:" + r.dur + "s", "animation-duration:" + r.dur + "s");
        if (r.delay != null) d.push("transition-delay:" + r.delay + "s", "animation-delay:" + r.delay + "s");
        if (r.ease) { var e = EASE[r.ease] || r.ease; d.push("transition-timing-function:" + e, "animation-timing-function:" + e); }
      }
      if (r.img && r.imgKind === "img") d.push('content:url("' + asset(r.img) + '")', "object-fit:contain");
      if (r.img && r.imgKind === "bg") d.push('background-image:url("' + asset(r.img) + '")');
      if (r.color) t.push("color:" + r.color);
      if (r.font) t.push('font-family:"' + r.font + '"');
      if (r.weight) t.push("font-weight:" + r.weight);
      if (r.spacing != null) t.push("letter-spacing:" + r.spacing + "px");
      if (r.case) t.push("text-transform:" + r.case);
      if (d.length) out.push(sel + "{" + d.map(imp).join(";") + "}");
      if (t.length) out.push(sel + "," + sel + " *{" + t.map(imp).join(";") + "}");
      if (r.color) out.push(sel + ":is(text,tspan)," + sel + " :is(text,tspan){fill:" + r.color + " !important}");
    });
    return out.join("\n");
  }
  function imp(s) { return s + " !important"; }
  var EASE = { snappy: "cubic-bezier(.2,.8,.2,1)", bounce: "cubic-bezier(.2,1.4,.4,1)" };

  function layer(tag, z) {
    var el = document.createElement(tag);
    el.setAttribute("style", "position:fixed;left:0;top:0;width:100vw;height:100vh;pointer-events:none;overflow:visible;z-index:" + z);
    document.body.appendChild(el);
    return el;
  }

  function addedEl(a) {
    var el = document.createElement("hudedit-item");
    el.id = "hudedit-a-" + a.id;
    el.dataset.hudeditAdded = a.id;
    var s = el.style;
    s.position = "absolute"; s.boxSizing = "border-box"; s.display = a.hide && !editing ? "none" : "flex";
    s.left = num(a.x, 0) + "px"; s.top = num(a.y, 0) + "px";
    s.width = num(a.w, 200) + "px"; s.height = num(a.h, 60) + "px";
    if (a.rot) s.rotate = a.rot + "deg";
    s.opacity = a.hide ? ".22" : String(num(a.op, 1));
    if (a.radius) s.borderRadius = a.radius + "px";
    if (a.border) s.border = a.border + "px solid " + (a.borderColor || "#ffffff");
    if (a.type === "box") s.background = a.bg || "#ffffff";
    if (a.type === "text") {
      s.alignItems = "center"; s.whiteSpace = "pre"; s.overflow = "visible";
      s.justifyContent = a.align === "right" ? "flex-end" : a.align === "center" ? "center" : "flex-start";
      s.color = a.color || "#ffffff"; s.fontSize = num(a.size, 32) + "px"; s.fontWeight = a.weight || 700;
      if (a.font) s.fontFamily = '"' + a.font + '"';
      if (a.spacing) s.letterSpacing = a.spacing + "px";
      if (a.case) s.textTransform = a.case;
      if (a.bg) s.background = a.bg;
      el.textContent = a.text || "";
    }
    if (a.type === "image" && a.img) {
      var ext = a.img.split(".").pop();
      var m = document.createElement(ext === "webm" || ext === "mp4" ? "video" : "img");
      m.src = asset(a.img);
      if (m.tagName === "VIDEO") { m.muted = true; m.loop = true; m.autoplay = true; m.playsInline = true; }
      m.setAttribute("style", "width:100%;height:100%;object-fit:" + (a.fit || "contain") + ";display:block");
      el.appendChild(m);
    }
    return el;
  }

  function applyAdded() {
    if (!document.body) return;
    if (!front) { back = layer("hudedit-back", -1); front = layer("hudedit-front", 2147482000); }
    front.replaceChildren(); back.replaceChildren();
    (edits.added || []).forEach(function (a) { (a.behind ? back : front).appendChild(addedEl(a)); });
  }

  // SVG <image> pictures can't be swapped by CSS: their href is (and put back).
  var swapped = [];
  function applySvgImages() {
    swapped = swapped.filter(function (s) {
      var r = (edits.rules || {})[s.sel];
      if (r && r.img && r.imgKind === "svg" && s.el.isConnected) return true;
      if (s.el.isConnected) s.el.setAttribute("href", s.orig);
      return false;
    });
    var rules = edits.rules || {};
    Object.keys(rules).forEach(function (sel) {
      var r = rules[sel];
      if (!r.img || r.imgKind !== "svg") return;
      var want = asset(r.img);
      var list;
      try { list = document.querySelectorAll(sel); } catch (e) { return; }
      list.forEach(function (el) {
        if (el.getAttribute("href") === want) return;
        var known = swapped.find(function (s) { return s.el === el; });
        if (!known) swapped.push({ el: el, sel: sel, orig: el.getAttribute("href") || "" });
        else known.orig = el.getAttribute("href") || known.orig;
        el.setAttribute("href", want);
      });
    });
  }

  function apply() {
    if (!styleEl) {
      styleEl = document.createElement("style");
      styleEl.id = "hudedit-css";
      (document.head || document.documentElement).appendChild(styleEl);
    } else if (styleEl.nextSibling && document.head) {
      document.head.appendChild(styleEl);   // (stay last, after any style the page added)
    }
    styleEl.textContent = css(edits);
    if (document.body) { applyAdded(); applySvgImages(); }
    if (editing) drawSelection();
  }

  function setEdits(doc, fromServer) {
    var before = JSON.stringify(edits.settings || {});
    edits = { rules: doc.rules || {}, added: doc.added || [], fonts: doc.fonts || [], settings: doc.settings || {} };
    if (JSON.stringify(edits.settings) !== before) settingsChanged();
    if (fromServer) {
      rev = doc.rev || 0;
      savedJson = JSON.stringify(edits);
      try { localStorage.setItem(storeKey(), JSON.stringify(doc)); } catch (e) { /* no storage */ }
    }
    apply();
  }

  function fetchEdits(onlyIfNew) {
    var url = "/hudedit/edits?design=" + encodeURIComponent(key()) + (onlyIfNew && rev >= 0 ? "&rev=" + rev : "");
    return fetch(url, { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (doc) {
      if (doc.error) return null;
      if (doc.same) return doc;
      return doc;
    });
  }

  function load() {
    var k = key();
    try {   // (the last saved changes at once, before the app answers)
      var cached = JSON.parse(localStorage.getItem(storeKey()) || "null");
      if (cached && cached.rules) setEdits(cached, false);
      else setEdits(blank(), false);
    } catch (e) { setEdits(blank(), false); }
    rev = -1;
    return fetchEdits(false).then(function (doc) {
      if (doc && k === key()) {
        setEdits(doc, true);
        if (editing) { history = [JSON.stringify(edits)]; future = []; say("loaded", info()); }
      }
    }).catch(function () { /* the app is restarting; try on the next poll */ });
  }

  function poll() {
    if (!editing || !dirty()) {
      var k = key();
      fetchEdits(true).then(function (doc) {
        if (!doc || k !== key()) return;
        if (!doc.same && doc.rev !== rev) {
          if (editing && dirty()) return;
          setEdits(doc, true);
          if (editing) { history = [JSON.stringify(edits)]; future = []; say("loaded", info()); }
        }
      }).catch(function () { });
    }
    setTimeout(poll, POLL_MS);
  }

  var observerQueued = false;
  function watchDom() {
    // (pages that build parts later, or rebuild them: SVG pictures swapped again)
    new MutationObserver(function (list) {
      if (observerQueued) return;
      for (var i = 0; i < list.length; i++) {
        var t = list[i].target;
        if (t === front || t === back || (ui && ui.contains(t)) || (t.closest && t.closest("hudedit-front,hudedit-back,hudedit-ui"))) continue;
        observerQueued = true;
        requestAnimationFrame(function () { observerQueued = false; applySvgImages(); if (editing) drawSelection(); });
        return;
      }
    }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["href"] });
  }

  // A page's own settings (timings, when parts come in and out) and the
  // states it can be shown in while editing (HudEdit.settings / .states).
  var declared = [], stateList = [], forced = "", listeners = [];
  function settingsChanged() { listeners.forEach(function (f) { try { f(); } catch (e) { } }); }
  function getSetting(k, d) {
    var v = (edits.settings || {})[k];
    if (v === undefined || v === null || v === "") {
      var dec = declared.filter(function (x) { return x.key === k; })[0];
      return dec && dec.def !== undefined ? dec.def : d;
    }
    return v;
  }

  window.HudEdit = {
    settings: function (list) { declared = list || []; if (editing && ui) say("selected", info()); },
    states: function (list) { stateList = list || []; if (editing && ui) say("selected", info()); },
    get: getSetting,
    state: function () { return forced; },
    onChange: function (f) { listeners.push(f); },
    editing: editing,
    setDesign: function (id) {
      id = String(id || "").toLowerCase().replace(/[^a-z0-9._-]+/g, "-");
      if (id === sub) return;
      sub = id;
      load();
      if (editing) say("design", { design: key() });
    },
    design: key
  };

  // --- the editor's hands (only with ?hudedit=1 inside HUD Builder) -------------

  var ui = null, hoverBox = null, selBox = null, selected = null, history = [], future = [];
  var peeked = [];

  function dirty() { return JSON.stringify(edits) !== savedJson; }
  function say(type, data) {
    var m = Object.assign({ hudedit: type, design: key() }, data || {});
    try { window.parent.postMessage(m, "*"); } catch (e) { /* gone */ }
  }
  function okOrigin(o) { return /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(o) || o === location.origin; }

  function ours(el) { return !!(el && el.closest && el.closest("hudedit-ui,hudedit-front,hudedit-back")); }
  var SKIP = { SCRIPT: 1, STYLE: 1, LINK: 1, META: 1, TITLE: 1, HEAD: 1, NOSCRIPT: 1, TEMPLATE: 1, BR: 1 };
  var SVG_SKIP = { defs: 1, clipPath: 1, mask: 1, linearGradient: 1, radialGradient: 1, stop: 1, filter: 1, symbol: 1, pattern: 1, marker: 1, title: 1, desc: 1, metadata: 1, style: 1 };
  function skipEl(el) {
    if (!el || !el.tagName || SKIP[el.tagName.toUpperCase()] || ours(el)) return true;
    if (el instanceof SVGElement && (SVG_SKIP[el.localName] || el.closest("defs,clipPath,mask,pattern,symbol,marker,filter"))) return true;
    return false;
  }

  function idSafe(id) { return /^[A-Za-z_][\w-]*$/.test(id) && document.querySelectorAll("#" + id).length === 1; }
  function stepOf(el) {
    var tag = el.localName, i = 1, s = el;
    while ((s = s.previousElementSibling)) if (s.localName === tag) i++;
    return tag + ":nth-of-type(" + i + ")";
  }
  function selectorFor(el) {
    var parts = [];
    while (el && el !== document.body && el !== document.documentElement) {
      if (el.id && idSafe(el.id)) { parts.unshift("#" + el.id); return parts.join(" > "); }
      parts.unshift(stepOf(el));
      el = el.parentElement;
    }
    parts.unshift("body");
    return parts.join(" > ");
  }
  // Everything like it beside it (the same tag and classes, under the same parent).
  function similarFor(el) {
    var cls = Array.prototype.filter.call(el.classList || [], function (c) { return /^[A-Za-z_][\w-]*$/.test(c) && !/^(active|show|shown|hide|hidden|on|off|live|win|won|lose|lost|in|out|visible|anim|enter|leave|left|right|blue|red|planted|dead|alive)$/i.test(c); });
    if (!cls.length || !el.parentElement || (el.id && idSafe(el.id))) return null;
    var parentSel = el.parentElement === document.body ? "body" : selectorFor(el.parentElement);
    var sel = parentSel + " > " + el.localName + "." + cls.join(".");
    var n = 0;
    try { n = document.querySelectorAll(sel).length; } catch (e) { return null; }
    return n > 1 ? { sel: sel, count: n } : null;
  }
  function first(sel) { try { return document.querySelector(sel); } catch (e) { return null; } }

  function nameOf(el) {
    if (el.dataset && el.dataset.hudeditAdded) {
      var a = findAdded(el.dataset.hudeditAdded);
      return a ? (a.label || (a.type === "text" ? "Text: " + (a.text || "").slice(0, 24) : a.type === "box" ? "Box" : "Picture")) : "Added";
    }
    var r = (edits.rules || {})[selectorFor(el)];
    if (r && r.label) return r.label;
    var bits = [];
    if (el.id) bits.push(el.id.replace(/[-_]+/g, " "));
    else if (el.classList && el.classList.length) bits.push(Array.prototype.slice.call(el.classList, 0, 2).join(" ").replace(/[-_]+/g, " "));
    var src = el.getAttribute && (el.getAttribute("src") || el.getAttribute("href"));
    if (src && /^(IMG|image|VIDEO)$/i.test(el.localName)) bits.push(decodeURIComponent(src.split("?")[0].split("/").pop()).slice(0, 28));
    var own = "";
    for (var c = el.firstChild; c; c = c.nextSibling) if (c.nodeType === 3) own += c.nodeValue;
    own = own.trim();
    if (own && bits.length < 2) bits.push("“" + own.slice(0, 22) + "”");
    if (!bits.length) bits.push(el.localName);
    return bits.join(" · ");
  }
  function kindOf(el) {
    var tag = el.localName;
    if (tag === "img" || tag === "image" || tag === "video") return "picture";
    if (tag === "text" || tag === "tspan") return "text";
    if (/^(rect|path|circle|ellipse|polygon|line|polyline)$/.test(tag)) return "shape";
    if (tag === "svg" || tag === "g") return "group";
    var hasText = false;
    for (var c = el.firstChild; c; c = c.nextSibling) if (c.nodeType === 3 && c.nodeValue.trim()) hasText = true;
    if (hasText) return "text";
    if (el.children.length) return "group";
    var bg = getComputedStyle(el).backgroundImage;
    if (bg && bg !== "none" && /url\(/.test(bg)) return "picture";
    return "box";
  }
  function shown(el) {
    var r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
      var cs = getComputedStyle(e);
      if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) return false;
    }
    return true;
  }

  function tree() {
    var out = [];
    function walk(el, depth) {
      for (var c = el.firstElementChild; c; c = c.nextElementSibling) {
        if (skipEl(c)) continue;
        if (out.length > 1500) return;
        var sel = selectorFor(c);
        out.push({ sel: sel, name: nameOf(c), kind: kindOf(c), depth: depth, shown: shown(c), edited: !!(edits.rules || {})[sel],
                   kids: !!c.firstElementChild });
        if (depth < 14) walk(c, depth + 1);
      }
    }
    walk(document.body, 0);
    var added = (edits.added || []).map(function (a) {
      return { added: a.id, name: nameOf({ dataset: { hudeditAdded: a.id } }), kind: a.type === "image" ? "picture" : a.type, depth: 0, shown: !a.hide };
    });
    return { nodes: out, added: added };
  }

  function findAdded(id) { return (edits.added || []).find(function (a) { return a.id === id; }); }

  function firstFamily(f) { return String(f || "").split(",")[0].trim().replace(/^["']|["']$/g, ""); }
  function rgbHex(c) {
    var m = String(c || "").match(/rgba?\(([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?/);
    if (!m) return "";
    if (m[4] !== undefined && parseFloat(m[4]) === 0) return "";
    return "#" + [m[1], m[2], m[3]].map(function (v) { return (+v | 0).toString(16).padStart(2, "0"); }).join("");
  }

  function info() {
    var s = selected, base = { dirty: dirty(), rev: rev, fonts: fontList(), canUndo: history.length > 1, canRedo: future.length > 0,
      declared: declared, settings: edits.settings || {}, states: stateList, state: forced, revealAll: revealAll };
    if (!s) return Object.assign(base, { selected: null });
    if (s.added) {
      var a = findAdded(s.added);
      return Object.assign(base, { selected: a ? { added: a.id, item: a, name: nameOf({ dataset: { hudeditAdded: a.id } }) } : null });
    }
    var el = first(s.sel);
    var rule = (edits.rules || {})[s.sel] || {};
    var out = { sel: s.sel, rule: rule, exists: !!el, similar: s.similar || null, all: !!s.all };
    if (el) {
      var cs = getComputedStyle(el), r = el.getBoundingClientRect();
      var textEl = el;
      if (kindOf(el) !== "text") {   // (a box with text inside: what the text looks like)
        var t = el.querySelector("text,tspan,span,div,p,b,strong");
        if (t) textEl = t;
      }
      var ts = getComputedStyle(textEl);
      var src = el.getAttribute("src") || el.getAttribute("href") || "";
      var bgImg = cs.backgroundImage && /url\(/.test(cs.backgroundImage);
      Object.assign(out, {
        name: nameOf(el), kind: kindOf(el), tag: el.localName, svg: el instanceof SVGElement,
        rect: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
        hasText: !!(el.textContent || "").trim(),
        picture: el.localName === "img" ? "img" : el.localName === "image" ? "svg" : bgImg ? "bg" : "",
        src: src,
        now: {
          color: rgbHex(el instanceof SVGElement ? ts.fill : ts.color) || rgbHex(ts.color),
          font: firstFamily(ts.fontFamily), size: Math.round(parseFloat(ts.fontSize) * 10) / 10,
          weight: parseInt(ts.fontWeight, 10) || 400, spacing: parseFloat(ts.letterSpacing) || 0,
          bg: rgbHex(el instanceof SVGElement ? cs.fill : cs.backgroundColor), radius: parseFloat(cs.borderTopLeftRadius) || 0,
          opacity: parseFloat(cs.opacity),
          motion: motionText(cs)
        },
        parent: el.parentElement && el.parentElement !== document.body && !skipEl(el.parentElement) ? selectorFor(el.parentElement) : null
      });
    }
    return Object.assign(base, { selected: out });
  }

  function motionText(cs) {
    var out = [];
    var props = cs.transitionProperty.split(","), durs = cs.transitionDuration.split(","), dels = cs.transitionDelay.split(",");
    props.forEach(function (p, i) {
      var d = parseFloat(durs[i % durs.length]) || 0, l = parseFloat(dels[i % dels.length]) || 0;
      if (d > 0 && p.trim() !== "none") out.push(p.trim() + " " + d + "s" + (l ? " after " + l + "s" : ""));
    });
    if (cs.animationName && cs.animationName !== "none") out.push("animation " + cs.animationName + " " + cs.animationDuration);
    return out.join(", ");
  }

  // "Show every part": everything hidden right now shown (while editing only).
  var revealAll = false, revealTimer = null;
  function revealPass() {
    if (!revealAll) return;
    var all = document.body.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (skipEl(el) || ours(el)) continue;
      var cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) {
        var was = el.getAttribute("style");
        if (cs.display === "none") el.style.setProperty("display", el instanceof SVGElement ? "inline" : "block", "important");
        if (cs.visibility === "hidden") el.style.setProperty("visibility", "visible", "important");
        if (parseFloat(cs.opacity) === 0) el.style.setProperty("opacity", "1", "important");
        revealed.push({ el: el, style: was });
      }
    }
  }
  var revealed = [];
  function setReveal(on) {
    revealAll = !!on;
    clearInterval(revealTimer);
    for (var i = revealed.length - 1; i >= 0; i--) {
      var p = revealed[i];
      if (p.style == null) p.el.removeAttribute("style"); else p.el.setAttribute("style", p.style);
    }
    revealed = [];
    if (revealAll) { revealPass(); revealTimer = setInterval(revealPass, 500); }
  }

  function fontList() {
    var seen = {};
    try { document.fonts.forEach(function (f) { seen[f.family.replace(/^["']|["']$/g, "")] = 1; }); } catch (e) { }
    (edits.fonts || []).forEach(function (f) { seen[f.family] = 1; });
    return Object.keys(seen).sort();
  }

  function remember() {
    var now = JSON.stringify(edits);
    if (history[history.length - 1] !== now) { history.push(now); future = []; if (history.length > 200) history.shift(); }
  }
  function changed(keepTree) {
    apply();
    remember();
    say("changed", Object.assign(info(), keepTree ? {} : { tree: tree() }));
  }

  // The selection and hover outlines (and the handles to resize with).
  function drawBox(box, el, all) {
    if (!el) { box.style.display = "none"; return; }
    var r = el.getBoundingClientRect();
    box.style.display = "block";
    box.style.left = r.left + "px"; box.style.top = r.top + "px";
    box.style.width = Math.max(r.width, 1) + "px"; box.style.height = Math.max(r.height, 1) + "px";
    if (all) box.dataset.all = "1"; else delete box.dataset.all;
  }
  var view = 1;
  function drawSelection() {
    if (!selBox) return;
    var el = selected ? (selected.added ? document.getElementById("hudedit-a-" + selected.added) : first(selected.sel)) : null;
    drawBox(selBox, el);
    selBox.querySelectorAll("i").forEach(function (h) { h.style.width = h.style.height = Math.round(10 / view) + "px"; h.style.margin = Math.round(-5 / view) + "px"; });
    selBox.style.borderWidth = Math.max(1, Math.round(2 / view)) + "px";
    // (everything the rule changes, when it's for all of them)
    ui.querySelectorAll(".hud-also").forEach(function (b) { b.remove(); });
    if (selected && selected.all) {
      try {
        document.querySelectorAll(selected.sel).forEach(function (o) {
          if (o === el) return;
          var b = document.createElement("hudedit-box"); b.className = "hud-also"; ui.appendChild(b); drawBox(b, o);
        });
      } catch (e) { }
    }
  }

  function buildUi() {
    ui = document.createElement("hudedit-ui");
    ui.setAttribute("style", "position:fixed;left:0;top:0;width:100vw;height:100vh;pointer-events:none;z-index:2147483600");
    var st = document.createElement("style");
    st.textContent =
      "hudedit-ui hudedit-box{position:fixed;display:none;box-sizing:border-box;pointer-events:none}" +
      "hudedit-ui .hud-hover{border:1px solid rgba(80,170,255,.9);background:rgba(80,170,255,.08)}" +
      "hudedit-ui .hud-sel{border:2px solid #3aa0ff;box-shadow:0 0 0 1px rgba(0,0,0,.5)}" +
      "hudedit-ui .hud-also{display:block;border:1px dashed #3aa0ff}" +
      "hudedit-ui .hud-sel i{position:absolute;width:10px;height:10px;background:#fff;border:2px solid #3aa0ff;box-sizing:border-box;pointer-events:auto;border-radius:2px}" +
      "html.hudedit-on, html.hudedit-on *{cursor:default}" +
      "html.hudedit-on body *:not(hudedit-ui,hudedit-ui *,hudedit-front,hudedit-back){pointer-events:auto !important}" +   // (HUD parts are often click-through)
      "html.hudedit-on hudedit-front, html.hudedit-on hudedit-back{pointer-events:none}" +
      "html.hudedit-on hudedit-item{pointer-events:auto}";
    ui.appendChild(st);
    hoverBox = document.createElement("hudedit-box"); hoverBox.className = "hud-hover";
    selBox = document.createElement("hudedit-box"); selBox.className = "hud-sel";
    [[-1, -1, "nwse"], [0, -1, "ns"], [1, -1, "nesw"], [1, 0, "ew"], [1, 1, "nwse"], [0, 1, "ns"], [-1, 1, "nesw"], [-1, 0, "ew"]].forEach(function (h) {
      var i = document.createElement("i");
      i.dataset.hx = h[0]; i.dataset.hy = h[1];
      i.style.left = (h[0] + 1) * 50 + "%"; i.style.top = (h[1] + 1) * 50 + "%";
      i.style.cursor = h[2] + "-resize";
      selBox.appendChild(i);
    });
    ui.appendChild(hoverBox); ui.appendChild(selBox);
    document.body.appendChild(ui);
    document.documentElement.classList.add("hudedit-on");
  }

  // Does it draw anything itself (not just hold other parts)?
  function paints(el) {
    if (/^(img|image|video|canvas|text|tspan|rect|path|circle|ellipse|polygon|line|polyline|use|hudedit-item)$/.test(el.localName)) return true;
    for (var c = el.firstChild; c; c = c.nextSibling) if (c.nodeType === 3 && c.nodeValue.trim()) return true;
    if (!el.firstElementChild) return true;
    var cs = getComputedStyle(el);
    if (cs.backgroundImage !== "none" || cs.boxShadow !== "none" || parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderLeftWidth) > 0) return true;
    var bg = cs.backgroundColor.match(/[\d.]+/g);
    return !!(bg && (bg.length < 4 || parseFloat(bg[3]) > 0));
  }
  function pick(x, y) {
    var list = document.elementsFromPoint(x, y);
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (el.closest && el.closest("hudedit-ui")) continue;
      var item = el.closest && el.closest("hudedit-item");
      if (item) return item;
      if (ours(el) || el === document.body || el === document.documentElement || skipEl(el)) continue;
      var r = el.getBoundingClientRect();   // (a full-screen stage or SVG: what's in it, not it)
      if (r.width * r.height > innerWidth * innerHeight * 0.85) continue;
      if (!paints(el)) continue;   // (an empty box around other parts: what's in it)
      if (!shown(el) && !peeked.some(function (pk) { return pk.el === el || el.contains(pk.el) || pk.el.contains(el); })) continue;   // (not on screen now)
      return el;
    }
    return null;
  }

  function select(sel, opts) {
    opts = opts || {};
    unpeek();
    if (!sel) selected = null;
    else if (sel.added) selected = { added: sel.added };
    else {
      var el = first(sel.sel);
      var sim = el ? similarFor(el) : null;
      selected = { sel: sel.sel, similar: sim ? sim.count : null, simSel: sim ? sim.sel : null, one: sel.sel, all: false };
      if (el && opts.peek && !shown(el)) peek(el);
    }
    drawSelection();
    say("selected", info());
  }

  // A part that isn't on screen right now (a banner between rounds): shown while it's picked.
  function peek(el) {
    for (var e = el; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
      var cs = getComputedStyle(e);
      var was = e.getAttribute("style");
      var touched = false;
      if (cs.display === "none") { e.style.setProperty("display", e instanceof SVGElement ? "inline" : "block", "important"); touched = true; }
      if (cs.visibility === "hidden") { e.style.setProperty("visibility", "visible", "important"); touched = true; }
      if (parseFloat(cs.opacity) === 0) { e.style.setProperty("opacity", "1", "important"); touched = true; }
      if (touched) peeked.push({ el: e, style: was });
    }
  }
  function unpeek() {
    peeked.forEach(function (p) { if (p.style == null) p.el.removeAttribute("style"); else p.el.setAttribute("style", p.style); });
    peeked = [];
  }

  // How many page pixels one pixel of the part's own moves is (a page inside a scaled box).
  function localScale(el) {
    var p = el.parentElement;
    if (el instanceof SVGElement && el.parentNode && el.parentNode.getScreenCTM) {
      var m = el.parentNode.getScreenCTM();
      if (m && m.a) return Math.abs(m.a);
    }
    for (; p && p !== document.documentElement; p = p.parentElement) {
      if (p.offsetWidth > 0) {
        var r = p.getBoundingClientRect();
        if (r.width > 0) return r.width / p.offsetWidth;
      }
    }
    return 1;
  }

  function rule(sel) {
    edits.rules = edits.rules || {};
    return edits.rules[sel] || (edits.rules[sel] = {});
  }
  function tidy(sel) {
    var r = edits.rules[sel];
    if (!r) return;
    Object.keys(r).forEach(function (k) { if (r[k] === null || r[k] === "" || r[k] === undefined) delete r[k]; });
    if (r.x === 0) delete r.x; if (r.y === 0) delete r.y;
    if (r.sx === 1) delete r.sx; if (r.sy === 1) delete r.sy; if (r.rot === 0) delete r.rot;
    if (r.op === 1) delete r.op; if (r.hide === false) delete r.hide;
    var left = Object.keys(r).filter(function (k) { return k !== "svg" && k !== "imgKind"; });
    if (!left.length) delete edits.rules[sel];
  }

  var drag = null;
  function onDown(e) {
    if (e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    var handle = e.target && e.target.closest && e.target.closest("hudedit-ui i");
    if (!handle) {
      var el = pick(e.clientX, e.clientY);
      if (!el) { select(null); return; }
      var target = el.dataset && el.dataset.hudeditAdded ? { added: el.dataset.hudeditAdded } : { sel: selectorFor(el) };
      var same = selected && (target.added ? selected.added === target.added : selected.sel === target.sel || (selected.all && first(selected.sel) && document.querySelectorAll(selected.sel).length && Array.prototype.indexOf.call(document.querySelectorAll(selected.sel), el) >= 0));
      if (!same) select(target);
    }
    if (!selected) return;
    var node = selected.added ? document.getElementById("hudedit-a-" + selected.added) : first(selected.sel);
    if (!node) return;
    var r = node.getBoundingClientRect();
    var a = selected.added ? findAdded(selected.added) : null;
    var ru = a ? null : rule(selected.sel);
    if (ru && node instanceof SVGElement) ru.svg = true;
    drag = { x: e.clientX, y: e.clientY, hx: handle ? +handle.dataset.hx : null, hy: handle ? +handle.dataset.hy : null,
             w: r.width, h: r.height, k: a ? 1 : localScale(node), moved: false,
             start: a ? { x: a.x, y: a.y, w: a.w, h: a.h } : { x: num(ru.x, 0), y: num(ru.y, 0), sx: num(ru.sx, 1), sy: num(ru.sy, 1) } };
  }
  function onMove(e) {
    if (!drag) {
      var el = pick(e.clientX, e.clientY);
      drawBox(hoverBox, el && !(selected && !selected.added && el === first(selected.sel)) ? el : null);
      return;
    }
    e.preventDefault();
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
    drag.moved = true;
    hoverBox.style.display = "none";
    var s = drag.start, a = selected.added ? findAdded(selected.added) : null;
    if (drag.hx === null) {   // moving
      if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
      if (a) { a.x = Math.round(s.x + dx); a.y = Math.round(s.y + dy); }
      else { var r = rule(selected.sel); r.x = Math.round((s.x + dx / drag.k) * 10) / 10; r.y = Math.round((s.y + dy / drag.k) * 10) / 10; }
    } else {                  // resizing from a handle (the opposite side stays put)
      var W = Math.max(4, drag.w + drag.hx * dx), H = Math.max(4, drag.h + drag.hy * dy);
      var corner = drag.hx !== 0 && drag.hy !== 0;
      if (corner && !e.shiftKey) {   // (corners keep the shape; Shift to stretch)
        var f = Math.max(W / drag.w, H / drag.h);
        W = drag.w * f; H = drag.h * f;
      }
      if (drag.hx === 0) W = drag.w;
      if (drag.hy === 0) H = drag.h;
      if (a) {
        a.w = Math.round(W); a.h = Math.round(H);
        a.x = Math.round(drag.hx < 0 ? s.x + (drag.w - W) : s.x);
        a.y = Math.round(drag.hy < 0 ? s.y + (drag.h - H) : s.y);
      } else {
        var ru = rule(selected.sel);
        ru.sx = Math.round(s.sx * W / drag.w * 1000) / 1000;
        ru.sy = Math.round(s.sy * H / drag.h * 1000) / 1000;
        // (scaling is about the middle, so the move keeps the far side where it was)
        ru.x = Math.round((s.x + drag.hx * (W - drag.w) / 2 / drag.k) * 10) / 10;
        ru.y = Math.round((s.y + drag.hy * (H - drag.h) / 2 / drag.k) * 10) / 10;
      }
    }
    apply();
    say("live", info());
  }
  function onUp() {
    if (!drag) return;
    var moved = drag.moved;
    drag = null;
    if (selected && selected.sel) tidy(selected.sel);
    if (moved) changed(true);
  }

  function nudge(dx, dy) {
    if (!selected) return;
    if (selected.added) { var a = findAdded(selected.added); if (!a) return; a.x += dx; a.y += dy; }
    else {
      var el = first(selected.sel), k = el ? localScale(el) : 1, r = rule(selected.sel);
      if (el instanceof SVGElement) r.svg = true;
      r.x = Math.round((num(r.x, 0) + dx / k) * 10) / 10; r.y = Math.round((num(r.y, 0) + dy / k) * 10) / 10;
      tidy(selected.sel);
    }
    changed(true);
  }

  function keydown(e) {
    var t = e.target;
    if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    command(keyCommand(e), e);
  }
  function keyCommand(e) {
    var k = e.key, mod = e.ctrlKey || e.metaKey, step = e.shiftKey ? 10 : 1;
    if (mod && (k === "z" || k === "Z")) return e.shiftKey ? { hudedit: "redo" } : { hudedit: "undo" };
    if (mod && (k === "y" || k === "Y")) return { hudedit: "redo" };
    if (mod && (k === "s" || k === "S")) return { hudedit: "save" };
    if (k === "ArrowLeft") return { hudedit: "nudge", dx: -step, dy: 0 };
    if (k === "ArrowRight") return { hudedit: "nudge", dx: step, dy: 0 };
    if (k === "ArrowUp") return { hudedit: "nudge", dx: 0, dy: -step };
    if (k === "ArrowDown") return { hudedit: "nudge", dx: 0, dy: step };
    if (k === "Escape") return { hudedit: "select", sel: null };
    if ((k === "Delete" || k === "Backspace") && selected && selected.added) return { hudedit: "remove-added", id: selected.added };
    return null;
  }

  function newId() { return Math.random().toString(36).slice(2, 10); }

  function save() {
    var body = { design: key(), edits: edits, base_rev: rev < 0 ? null : rev };
    return fetch("/hudedit/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); })
      .then(function (res) {
        if (res.j.ok) {
          rev = res.j.rev; savedJson = JSON.stringify(edits);
          try { localStorage.setItem(storeKey(), JSON.stringify(Object.assign({ rev: rev }, edits))); } catch (e) { }
          say("saved", Object.assign(info(), { saved: res.j.saved }));
        } else say("error", { text: res.j.error || "Couldn't save", conflict: !!res.j.conflict });
      })
      .catch(function (e) { say("error", { text: "Couldn't reach the HUD to save (" + e.message + ")" }); });
  }

  function command(m, e) {
    if (!m) return;
    if (e) e.preventDefault();
    var t = m.hudedit;
    if (t === "undo" && history.length > 1) { future.push(history.pop()); setEdits(JSON.parse(history[history.length - 1])); say("changed", Object.assign(info(), { tree: tree() })); }
    else if (t === "redo" && future.length) { var n = future.pop(); history.push(n); setEdits(JSON.parse(n)); say("changed", Object.assign(info(), { tree: tree() })); }
    else if (t === "nudge") nudge(m.dx, m.dy);
    else if (t === "save") save();
    else if (t === "tree") say("tree", tree());
    else if (t === "info") say("selected", info());
    else if (t === "select") select(m.sel ? (m.added ? { added: m.added } : { sel: m.sel }) : (m.added ? { added: m.added } : null), { peek: true });
    else if (t === "all") {   // the change for every one like it, or just this one
      if (!selected || !selected.sel) return;
      selected.all = !!m.on;
      selected.sel = m.on && selected.simSel ? selected.simSel : selected.one;
      drawSelection(); say("selected", info());
    } else if (t === "set") {  // {props}: null takes a change off
      if (!selected) return;
      if (selected.added) { var a = findAdded(selected.added); if (!a) return; Object.keys(m.props).forEach(function (k) { if (m.props[k] === null) delete a[k]; else a[k] = m.props[k]; }); }
      else {
        var r = rule(selected.sel), el = first(selected.sel);
        if (el instanceof SVGElement) r.svg = true;
        Object.keys(m.props).forEach(function (k) { if (m.props[k] === null) delete r[k]; else r[k] = m.props[k]; });
        if (m.props.img === null) delete r.imgKind;
        tidy(selected.sel);
      }
      changed(!("label" in m.props || "text" in m.props || "hide" in m.props));
    } else if (t === "reset-part") {
      if (selected && selected.sel) { delete edits.rules[selected.sel]; changed(); }
    } else if (t === "reset-all") {
      edits = blank(); selected = null; changed();
    } else if (t === "add") {
      var item = Object.assign({ id: newId() }, m.item);
      edits.added = (edits.added || []).concat([item]);
      apply();
      selected = { added: item.id };
      changed();
      say("selected", info());
    } else if (t === "remove-added") {
      edits.added = (edits.added || []).filter(function (x) { return x.id !== m.id; });
      if (selected && selected.added === m.id) selected = null;
      changed();
    } else if (t === "order") {   // an added item one step up or down
      var list = edits.added || [], i = list.findIndex(function (x) { return x.id === m.id; }), j = i + m.by;
      if (i < 0 || j < 0 || j >= list.length) return;
      var x = list[i]; list[i] = list[j]; list[j] = x;
      changed();
    } else if (t === "font") {    // an uploaded font: {family, file}
      edits.fonts = (edits.fonts || []).filter(function (f) { return f.family !== m.family; }).concat([{ family: m.family, file: m.file }]);
      changed(true);
    } else if (t === "view") { view = m.scale || 1; drawSelection(); }
    else if (t === "state") { forced = m.id || ""; setTimeout(function () { say("changed", Object.assign(info(), { tree: tree() })); }, 700); say("selected", info()); }
    else if (t === "reveal") { setReveal(m.on); setTimeout(function () { say("changed", Object.assign(info(), { tree: tree() })); }, 100); }
    else if (t === "setting") {
      edits.settings = edits.settings || {};
      if (m.value === null || m.value === undefined) delete edits.settings[m.key]; else edits.settings[m.key] = m.value;
      settingsChanged();
      changed(true);
    }
    else if (t === "reload") { load().then(function () { say("tree", tree()); }); }
    else if (t === "discard") { setEdits(JSON.parse(savedJson)); history = [savedJson]; future = []; say("changed", Object.assign(info(), { tree: tree() })); }
  }

  function startEditing() {
    buildUi();
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("pointermove", onMove, true);
    window.addEventListener("pointerup", onUp, true);
    window.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); }, true);
    window.addEventListener("keydown", keydown, true);
    window.addEventListener("message", function (e) {
      if (e.source !== window.parent || !okOrigin(e.origin) || !e.data || !e.data.hudedit) return;
      command(e.data);
    });
    window.addEventListener("scroll", drawSelection, true);
    setInterval(function () { if (!drag) drawSelection(); }, 250);   // (parts that move by themselves)
    history = [JSON.stringify(edits)];
    say("ready", Object.assign(info(), { tree: tree(), title: document.title }));
  }

  function boot() {
    apply();
    watchDom();
    if (editing) startEditing();
  }

  load();
  setTimeout(poll, POLL_MS);
  if (document.body) boot();
  else document.addEventListener("DOMContentLoaded", boot);
})();
