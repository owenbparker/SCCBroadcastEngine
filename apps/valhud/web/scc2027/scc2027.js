// The SCC 2027 VALORANT HUD: draws owen's Figma design from the app's
// /api/state (the same state the Default 2026 templates get through
// driver.js), so every feature works the same: teams, logos, series pips,
// score, round and clock, the maps, sponsors, player tabs (agent,
// abilities, ult points, credits, gun, shield, health, spike carrier, the
// spectated player, low health, dead), the buy-phase board with its round
// tracker and timeouts, the spike, timeout / technical pause cards, the
// spectated player's cam (web/cams.js), 2v2, plus the design's Ace and
// Listen In graphics.
//
// URL options: ?fit=1 scales the 1920x1080 page to the window (the HUD on
// the game); ?scoreboard=0 leaves the buy-phase board out; ?part=board is
// only the board (the /scoreboard source). Previews: ?ace=1, ?listen=left.
(function () {
  "use strict";
  var params = new URLSearchParams(location.search);
  var BOARD_ONLY = params.get("part") === "board";
  var NO_BOARD = params.get("scoreboard") === "0";
  var stage = document.getElementById("stage");
  var SIDES = ["left", "right"];
  var COL = { left: "var(--left)", right: "var(--right)" };
  var TAB_TOPS = [551, 657, 763, 869, 975], DUO_TOPS = [500, 790];
  var SIDEARMS = { Classic: 1, Shorty: 1, Frenzy: 1, Ghost: 1, Sheriff: 1, Bandit: 1 };
  var WIN_ICON = { Elimination: 1, Detonation: 1, Deactivation: 1, Time: 1 };

  // ------------------------------------------------------------ helpers
  function el(cls, parent, css, tag) {
    var e = document.createElement(tag || "div");
    if (cls) e.className = cls;
    if (css) Object.assign(e.style, css);
    if (parent) parent.appendChild(e);
    return e;
  }
  function px(n) { return n + "px"; }
  // One line of text: font class (tung / din / dinr / nar / rub / rubm), the
  // Figma box (x from the left, or from the right with side "R"), alignment.
  function text(fontCls, parent, x, y, w, h, align, side, extra) {
    var box = el("t " + fontCls + (align ? " " + align : "") + (extra ? " " + extra : ""), parent);
    box.style.top = px(y);
    if (h) box.style.height = px(h);
    if (w) box.style.width = px(w);
    box.style[side === "R" ? "right" : "left"] = px(x);
    var i = el("", box, null, "i");
    box.i = i;
    return box;
  }
  function place(e, x, y, side) { e.style[side === "R" ? "right" : "left"] = px(x); e.style.top = px(y); return e; }
  function setText(box, value) {
    var v = value == null ? "" : String(value);
    if (box.i.textContent !== v) { box.i.textContent = v; box.fitted = false; }
    fit(box);
  }
  // Shrinks a name to fit its box.
  function fit(box) {
    if (box.fitted || !box.style.width) return;
    box.i.style.fontSize = "";
    var room = parseFloat(box.style.width), w = box.i.scrollWidth;
    if (w > room && w > 0) {
      var size = parseFloat(getComputedStyle(box.i).fontSize) || 20;
      box.i.style.fontSize = Math.max(10, Math.floor(size * room / w)) + "px";
    }
    box.fitted = true;
  }
  function url(path) { return path ? "/" + String(path).replace(/^\//, "").split("/").map(encodeURIComponent).join("/") : ""; }
  function agentArt(agent, file) {
    return agent ? "/hud/Resources/Agentes/" + encodeURIComponent(agent) + "/" + encodeURIComponent(file || agent) + ".png" : "";
  }
  function bg(e, src) {
    var v = src ? 'url("' + src + '")' : "none";
    if (e._bg !== v) { e._bg = v; e.style.backgroundImage = v; }
  }
  function img(e, src) {
    if (e._src === src) return;
    e._src = src;
    e.onerror = function () { e.style.visibility = "hidden"; };   // (a logo that won't load: nothing, not a broken picture)
    if (src) { e.src = src; e.style.visibility = ""; } else { e.removeAttribute("src"); e.style.visibility = "hidden"; }
  }
  function toggle(e, cls, on) { if (e.classList.contains(cls) !== !!on) e.classList.toggle(cls, !!on); }
  function money(n) { return Number(n || 0).toLocaleString("en-US"); }
  function upper(t) { return String(t || "").toUpperCase(); }
  function ordinal(n) {
    var s = ["TH", "ST", "ND", "RD"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }
  var SVGNS = "http://www.w3.org/2000/svg";
  function credIcon() {
    var s = document.createElementNS(SVGNS, "svg");
    s.setAttribute("viewBox", "-3 -3 20 20");
    s.setAttribute("class", "cred-icon");
    s.innerHTML = '<circle cx="7" cy="7" r="5.5" fill="none" stroke="#fff" stroke-width="3"/>' +
      '<path d="M10.8 10.8l3.2 3.2M3.2 10.8L0 14M3.2 3.2L0 0M10.8 3.2L14 0" stroke="#fff" stroke-width="3"/>';
    return s;
  }
  // Credits: the icon, then the amount (or the amount, then the icon).
  function credText(parent, x, y, w, h, align, side, cls, iconAfter) {
    var b = text("rub", parent, x, y, w, h, align, side, cls);
    if (iconAfter) b.appendChild(credIcon()); else b.insertBefore(credIcon(), b.i);
    return b;
  }
  function shieldSvg(parent) {
    var wrap = el("shield", parent);
    wrap.innerHTML = '<svg width="21" height="21" viewBox="-1 -1 22.7 22.7"><path d="M10.33 0L0 5.17 2.58 15.5 10.33 20.67 18.08 15.5 20.66 5.17Z"' +
      ' fill="none" stroke="#fff" stroke-width="1.1" stroke-linejoin="round"/></svg>';
    wrap.num = text("rub", wrap, 0, 0, 21, 21, "c");
    return wrap;
  }
  // Ult points: a ring of segments, the earned ones white.
  function ultRing(parent) {
    var u = el("ult", parent);
    u.svg = document.createElementNS(SVGNS, "svg");
    u.svg.setAttribute("width", "41");
    u.svg.setAttribute("height", "41");
    u.appendChild(u.svg);
    u.icon = el("icon", u);
    return u;
  }
  function setUlt(u, agent, points, max) {
    max = Math.max(1, Math.min(10, max || 7));
    points = Math.max(0, Math.min(max, points || 0));
    var key = max + ":" + points;
    if (u._key !== key) {
      u._key = key;
      var c = 20.5, r = 18, gap = 0.32, step = 2 * Math.PI / max, out = "";
      for (var i = 0; i < max; i++) {
        var a0 = -Math.PI / 2 + i * step + gap / 2, a1 = a0 + step - gap;
        out += '<path d="M' + (c + r * Math.cos(a0)).toFixed(2) + " " + (c + r * Math.sin(a0)).toFixed(2) +
          " A" + r + " " + r + " 0 0 1 " + (c + r * Math.cos(a1)).toFixed(2) + " " + (c + r * Math.sin(a1)).toFixed(2) +
          '" fill="none" stroke="' + (i < points ? "#fff" : "rgba(0,0,0,.75)") + '" stroke-width="4"/>';
      }
      u.svg.innerHTML = out;
    }
    bg(u.icon, agentArt(agent, "X"));
    toggle(u, "ready", points >= max);
  }
  function abilities(parent, xs, y, side, cls) {
    return ["C", "Q", "E"].map(function (key, n) {
      var a = el("abil" + (cls ? " " + cls : ""), parent);
      place(a, xs[n], y, side);
      a.key = key;
      a.bars = el("charges", a);
      return a;
    });
  }
  function setAbilities(list, p) {
    list.forEach(function (a) {
      var v = (p.abilities || {})[a.key] || [0, 1], have = Math.max(0, Math.min(3, v[0] || 0)), max = Math.max(1, Math.min(3, v[1] || 1));
      bg(a, agentArt(p.agent, a.key));
      toggle(a, "none", have === 0);
      var key = have + "/" + max;
      if (a.bars._key !== key) {
        a.bars._key = key;
        a.bars.innerHTML = "";
        for (var i = 0; i < max; i++) el(i < have ? "" : "used", a.bars, null, "b");
      }
    });
  }

  // --------------------------------------------------------------- build
  var ui = { tabs: { left: [], right: [] }, rows: { left: [], right: [] } };

  // Top bar.
  var top = el("phase", stage); top.id = "top";
  ui.topBox = top;
  var tin = el("in", top);
  el("edge l", tin); el("edge r", tin);
  el("div", tin, { left: "203px" }); el("div", tin, { left: "463px" });
  el("spk", tin);   // (the condensed bar's spike, in place of the clock)
  ui.top = {
    logoL: el("logo l", tin, { left: "48px" }, "img"), logoR: el("logo r", tin, { left: "589px" }, "img"),
    triL: text("tung", tin, 88, 18, 102, 22, "c", null, "tri"), subL: text("nar", tin, 84, 45, 110, 10, "c", null, "sub"),
    triR: text("tung", tin, 474, 18, 102, 22, "c", null, "tri"), subR: text("nar", tin, 470, 45, 110, 10, "c", null, "sub"),
    scoreL: text("nar", tin, 227, 28, 60, 33, "c", null, "score"), scoreR: text("nar", tin, 381, 28, 60, 33, "c", null, "score"),
    rnd: text("nar", tin, 285, 11, 100, 10, "c", null, "rnd"),
    clock: text("tung", tin, 285, 27, 100, 34, "c", null, "clock"),
    pipsL: el("pips", tin, { left: "227px" }), pipsR: el("pips", tin, { left: "381px" })
  };
  ui.top.logoL.alt = ui.top.logoR.alt = "";
  ui.top.pipsL.style.setProperty("--c", COL.left);
  ui.top.pipsR.style.setProperty("--c", COL.right);
  ui.planted = el("", stage); ui.planted.id = "planted";
  // The round win banner: the Default 2026 HUD's for now (owen, 2026-11-18).
  ui.rwin = el("", stage); ui.rwin.id = "rwin";
  ui.rwinImg = el("pic", ui.rwin, null, "img"); ui.rwinImg.src = "/hud/Resources/Logos/banner1.png"; ui.rwinImg.alt = "";
  ui.rwinSide = el("side", ui.rwin); ui.rwinLogo = el("logo", ui.rwin, null, "img"); ui.rwinLogo.alt = "";
  ui.rwinTeam = el("team", ui.rwin);
  ui.banner = el("", stage); ui.banner.id = "banner";
  el("bar", ui.banner);
  ui.bannerText = text("nar", ui.banner, 8, 0, null, null, "c", null, "txt");
  ui.bannerText.style.right = "0"; ui.bannerText.style.bottom = "0";

  // Maps strip, event strip, sponsor box.
  ui.maps = el("phase", stage); ui.maps.id = "maps";
  ui.mapSlots = [23, 248, 446].map(function (x) {
    var m = el("m t nar", ui.maps, { left: px(x) });
    return m;
  });
  ui.event = el("phase", stage); ui.event.id = "event";
  ui.eventText = text("nar", ui.event, 0, 7, 433, 9, "c");
  ui.sponsor = el("", stage); ui.sponsor.id = "sponsor";
  ui.sponsorLogo = el("logo white", ui.sponsor);

  // Player tabs, in the side containers the 2v2 cams use too.
  ui.side = {
    left: el("phase L", stage), right: el("phase R", stage)
  };
  ui.side.left.id = "side-left"; ui.side.right.id = "side-right";
  var homes = { left: el("", ui.side.left), right: el("", ui.side.right) };
  homes.left.id = "teamIzquierda"; homes.right.id = "teamDerecha";
  SIDES.forEach(function (side) {
    var S = side === "left" ? "L" : "R";
    for (var slot = 1; slot <= 5; slot++) {
      var t = el("tab p" + slot, homes[side]);
      t.style.setProperty("--c", COL[side]);
      t.style[side === "left" ? "left" : "right"] = "17px";
      var o = { el: t, side: side };
      o.agent = el("agent", t);
      o.name = text("din", t, 61, 17, 108, 14, S === "R" ? "r" : "", S, "name");
      o.abil = abilities(t, [171, 202, 233], 14, S, "aliveonly");
      o.ult = ultRing(t); place(o.ult, 262, 4, S);
      o.creds = credText(t, 11, 57, 96, 14, S === "R" ? "r" : "", S, "creds aliveonly", S === "R");
      o.side_gun = place(el("gun side aliveonly", t), 106, 55, S);
      o.main_gun = place(el("gun main aliveonly", t), 140, 55, S);
      o.shield = shieldSvg(t); place(o.shield, 241, 54, S); o.shield.classList.add("aliveonly");
      o.hp = text("rubm", t, 262, 57, 42, 14, S === "R" ? "" : "r", S, "hp aliveonly");
      o.kda = text("rub", t, 7, 57, 120, 14, S === "R" ? "r" : "", S, "kda deadonly");
      o.dcreds = credText(t, 233, 57, 70, 14, S === "R" ? "" : "r", S, "creds deadonly", S === "R");
      o.hpbar = el("hpbar", t); o.hpfill = el("", o.hpbar, null, "b");
      o.badge = el("spikebadge", homes[side]);
      ui.tabs[side].push(o);
    }
  });

  // The buy-phase board.
  ui.board = el("phase", stage); ui.board.id = "board";
  el("bar", ui.board);
  ui.markL = el("mark", ui.board, { left: "678px" }, "img");
  ui.markR = el("mark", ui.board, { left: "1069px" }, "img");
  var ROW = 785, PITCH = 56;
  var BOXES = { left: { creds: [16, 164], abil: [189, 144], gun: [342, 224], who: [575, 381] },
                right: { creds: [1741, 164], abil: [1588, 144], gun: [1355, 224], who: [965, 381] } };
  SIDES.forEach(function (side) {
    var S = side === "left" ? "L" : "R", B = BOXES[side], inner = S;   // (positions inside a box mirror too)
    for (var slot = 1; slot <= 5; slot++) {
      var y = ROW + (slot - 1) * PITCH, r = { side: side };
      function box(kind) {
        var b = el("box " + S + " p" + slot + " " + kind, ui.board, { left: px(B[kind][0]), top: px(y), width: px(B[kind][1]) });
        b.style.setProperty("--c", COL[side]);
        return b;
      }
      r.cbox = box("creds");
      r.spent = text("rub", r.cbox, 11, 20, 70, 11, inner === "R" ? "r" : "", inner, "spent");
      r.creds = credText(r.cbox, 9, 18, 100, 16, inner === "R" ? "" : "r", inner === "R" ? "L" : "R", "creds", false);
      r.abox = box("abil");
      r.abil = abilities(r.abox, [13, 57, 101], 7, inner);
      r.gbox = box("gun");
      r.shieldImg = place(el("shieldimg", r.gbox), 11, 13, inner);
      r.shield = shieldSvg(r.gbox); place(r.shield, 13, 15, inner);
      r.gun = place(el("gun", r.gbox), 54, 11, inner);
      r.ult = ultRing(r.gbox); place(r.ult, 172, 4.5, inner);
      r.wbox = box("who");
      r.wbox.classList.add("who");
      r.agent = el("agent", r.wbox);
      r.name = text("din", r.wbox, 85, 18, 170, 14, inner === "R" ? "r" : "", inner, "name");
      r.kda = text("rub", r.wbox, 18, 18, 110, 14, inner === "R" ? "" : "r", inner === "R" ? "L" : "R", "kda");
      ui.rows[side].push(r);
    }
  });
  ui.tracker = el("", ui.board); ui.tracker.id = "tracker";

  // Ace.
  ui.ace = el("", stage); ui.ace.id = "ace";
  el("band", ui.ace);
  ui.aceWho = el("who", ui.ace);
  ui.aceTeam = text("din", ui.ace, 433, 218, null, 26, "", null, "team");
  ui.aceLogo = el("", ui.aceTeam, null, "img");
  ui.acePlayer = text("tung", ui.ace, 433, 268, 420, 53, "", null, "player");
  ui.aceLine = text("din", ui.ace, 433, 345, null, 26, "", null, "line3");
  el("mark", ui.ace);
  setText(text("tung", ui.ace, 865, 302, 202, 90, "c", null, "word"), "ACE");

  // Listen In.
  ui.listen = el("", stage); ui.listen.id = "listen";
  el("panel", ui.listen);
  var tag = el("tag", ui.listen);
  ui.listenTag = text("nar", tag, 0, 10, 159, 15, "c");
  ui.listenLogo = el("", ui.listenTag, null, "img");
  ui.listenTag.insertBefore(ui.listenLogo, ui.listenTag.i);
  ui.listenTag.i.textContent = "// LIVE COMMS";
  ui.tiles = [0, 1, 2, 3, 4].map(function (n) {
    var t = el("tile", ui.listen, { left: px(15 + n * 197) });
    var cam = el("scc-duo-cam", t), logo = el("scc-duo-logo", cam);
    var nm = text("din", t, 0, 0, null, null, "c", null, "nm");
    nm.style.top = "auto";
    return { el: t, cam: cam, logo: logo, name: nm, side: "left", slot: n + 1 };
  });

  if (BOARD_ONLY) [top, ui.planted, ui.banner, ui.maps, ui.event, ui.sponsor, ui.side.left, ui.side.right, ui.ace, ui.listen]
    .forEach(function (e) { e.classList.add("hidden"); });

  // ---------------------------------------------------------- sponsors
  var sponsor = { key: "", i: 0, timer: null, swap: null, looks: {} };
  // A logo with see-through parts is drawn white (as designed); a solid
  // picture (a JPG, say) keeps its colours rather than turning into a box.
  function sponsorLook(src, done) {
    if (sponsor.looks[src]) return done(sponsor.looks[src]);
    var im = new Image();
    im.onload = function () {
      var look = "white";
      try {
        var c = document.createElement("canvas"), w = c.width = Math.min(64, im.naturalWidth || 64), h = c.height = Math.min(64, im.naturalHeight || 64);
        var g = c.getContext("2d");
        g.drawImage(im, 0, 0, w, h);
        var d = g.getImageData(0, 0, w, h).data, clear = 0;
        for (var i = 3; i < d.length; i += 4) if (d[i] < 200) clear++;
        if (clear < (w * h) * 0.03) look = "colour";
      } catch (e) { look = "colour"; }
      sponsor.looks[src] = look;
      done(look);
    };
    im.onerror = function () { done("colour"); };
    im.src = src;
  }
  function showSponsor(src) {
    var logo = ui.sponsorLogo;
    sponsorLook(src, function (look) {
      logo.className = "logo " + look;
      logo.style.setProperty("--img", 'url("' + src + '")');
    });
  }
  function setSponsors(list, seconds) {
    var paths = (list || []).filter(Boolean).map(url);
    var key = JSON.stringify([paths, seconds]);
    if (key === sponsor.key) return;
    sponsor.key = key;
    sponsor.i = 0;
    clearInterval(sponsor.timer);
    clearTimeout(sponsor.swap);
    toggle(ui.sponsor, "hidden", !paths.length || BOARD_ONLY);
    if (!paths.length) return;
    function show() { showSponsor(paths[sponsor.i % paths.length]); sponsor.i++; }
    show();
    ui.sponsorLogo.style.opacity = "1";
    if (paths.length > 1) sponsor.timer = setInterval(function () {
      ui.sponsorLogo.style.opacity = "0";
      sponsor.swap = setTimeout(function () { show(); ui.sponsorLogo.style.opacity = "1"; }, 400);
    }, Math.max(1, Number(seconds) || 4) * 1000);
  }

  // ------------------------------------------------------------ phases
  // The buy-phase board shows in the buy phase (or when kept up from the
  // control panel); the player tabs slide away under it. Same rules as the
  // Default 2026 HUD (driver.js wantBoard).
  var boardTimes = { total: null, from: 0, until: 0 };
  function wantBoard(m, cfg) {
    if ((cfg.show || {}).scoreboard) return true;
    if (m.phase === "buy") return true;
    if (m.phase === "combat" || m.phase === "end") return false;
    var total = (m.score.left || 0) + (m.score.right || 0), now = Date.now();
    if (boardTimes.total !== null && total > boardTimes.total) { boardTimes.from = now + 6600; boardTimes.until = now + 34500; }
    boardTimes.total = total;
    return now >= boardTimes.from && now < boardTimes.until;
  }
  var boardOn = null, boardTimer = null, PANELS_MS = 450;
  function setBoard(on) {
    if (on === boardOn) return;
    var first = boardOn === null;
    boardOn = on;
    clearTimeout(boardTimer);
    var tabsAway = function (away) {
      toggle(ui.side.left, "away", away); toggle(ui.side.right, "away", away);
    };
    if (first) {
      ui.board.classList.add("away-quick");
      toggle(ui.board, "away", !on);
      tabsAway(on);
      void ui.board.offsetWidth;
      ui.board.classList.remove("away-quick");
      return;
    }
    if (on) {
      tabsAway(true);
      boardTimer = setTimeout(function () { toggle(ui.board, "away", false); }, PANELS_MS);
    } else {
      toggle(ui.board, "away", true);
      boardTimer = setTimeout(function () { tabsAway(false); }, PANELS_MS);
    }
  }

  // The maps and event strips (owen, 2026-11-18): out from behind the top
  // bar in the buy phase, back behind it 20 seconds into the round; out
  // between maps too (no round being played).
  var STRIPS_MS = 20000, combatAt = 0;
  function wantStrips(m, cfg) {
    if ((cfg.show || {}).scoreboard || m.phase === "buy") { combatAt = 0; return true; }
    if (m.phase === "combat") {
      // By the round clock (1:40 a round: out until 1:20); the spike down, in.
      if (m.spike && m.spike.state === "planted") return false;
      if (m.timer > 0 && m.timer <= 100) return 100 - m.timer < STRIPS_MS / 1000;
      if (!combatAt) combatAt = Date.now();   // (no clock read: from when the round was seen)
      return Date.now() - combatAt < STRIPS_MS;
    }
    combatAt = 0;
    return m.phase !== "end";
  }
  function setStrips(on) {
    toggle(ui.maps, "tucked", !on); toggle(ui.event, "tucked", !on);
  }

  var condensed = false;
  function wantCondensed(m, planted) {
    if (params.get("condensed")) return params.get("condensed") === "1";
    if (m.phase === "combat") condensed = planted || (m.timer > 0 && m.timer <= 100 ? 100 - m.timer >= COND_AT : condensed);
    else if (m.phase !== "end") condensed = false;   // (the round's end keeps it as it was)
    return condensed;
  }
  var COND_AT = 20.5;

  // -------------------------------------------------------------- top
  function setPips(box, need, won) {
    var key = need + ":" + won;
    if (box._key === key) return;
    box._key = key;
    box.innerHTML = "";
    for (var i = 0; i < need; i++) el(i < won ? "won" : "", box, null, "b");
  }
  function clock(sec) {
    sec = Math.max(0, Math.ceil(Number(sec) || 0));
    return Math.floor(sec / 60) + ":" + ("0" + sec % 60).slice(-2);
  }

  // -------------------------------------------------------------- maps
  function mapLabel(cfg, slot, shown, all, first) {
    var i = first + slot, map = slot < shown ? all[i] : null;
    if (!map || !map.name) return null;
    var name = upper(map.name), logo = function (side) { return side && cfg[side] && cfg[side].logo ? url(cfg[side].logo) : ""; };
    if (map.winner && map.score) return { pre: name, logo: logo(map.winner), post: map.score.left + " - " + map.score.right };
    if (map.winner) return { pre: name, logo: logo(map.winner), post: upper(cfg[map.winner].tricode) };
    if (i === (cfg.current_map || 0)) return { pre: "CURRENT:", logo: logo(map.picked_by), post: name };
    if (shown === 3 && i === all.length - 1 && all.length === Number(cfg.best_of || 3)) return { pre: "DECIDER:", logo: "", post: name };
    return { pre: "NEXT:", logo: logo(map.picked_by), post: name };
  }
  function setMaps(cfg) {
    var shown = (cfg.best_of || 3) == 1 ? 1 : 3;
    var all = (cfg.maps || []).slice(0, Math.max(1, cfg.best_of || 3));
    var first = shown === 3 ? Math.max(0, Math.min((cfg.current_map || 0) - 1, all.length - 3)) : 0;
    ui.mapSlots.forEach(function (box, slot) {
      var l = mapLabel(cfg, slot, shown, all, first), key = JSON.stringify(l);
      if (box._key === key) return;
      box._key = key;
      box.innerHTML = "";
      if (!l) return;
      el("", box, null, "i").textContent = l.pre;
      if (l.logo) { var im = el("", box, null, "img"); im.src = l.logo; }
      el("", box, null, "i").textContent = l.post;
    });
  }

  // ------------------------------------------------------------ tracker
  function setTracker(cfg, m) {
    var rounds = m.rounds || [], played = rounds.length, now = Math.max(1, m.round || played + 1);
    var cols = Math.max(now, played) <= 12 ? 12 : Math.max(24, Math.ceil(Math.max(now, played) / 2) * 2);
    var to = cfg.timeouts || {};
    var key = JSON.stringify([cols, now, rounds, to, cfg.left.tricode, cfg.right.tricode, cfg.left.logo, cfg.right.logo]);
    if (ui.tracker._key === key) return;
    ui.tracker._key = key;
    var T = ui.tracker;
    T.innerHTML = "";
    // Columns: 37 px apart, a 12 px gap after round 12 (and after 24: overtime).
    var xs = [], x = 163;
    for (var c = 0; c < cols; c++) {
      if (c === 12 || c === 24) x += 12;
      xs.push(x);
      x += 37;
    }
    var gridEnd = xs[cols - 1] + 32 + 9, width = gridEnd + 14;
    T.style.width = px(width);
    T.style.left = px(Math.round(960 - width / 2));
    SIDES.forEach(function (side, n) {
      var team = el("team", T, { top: px(14 + n * 50) });
      team.style.setProperty("--c", COL[side]);
      el("edge", team);
      var lg = el("", team, null, "img");
      img(lg, url(cfg[side].logo));
      setText(text("nar", team, 53, 16, 60, 14, "", null, "tri"), upper(cfg[side].tricode));
      var left = Math.max(0, Math.min(2, to[side] == null ? 2 : to[side]));
      [10, 26].forEach(function (y, k) { el("dot" + (k < left ? "" : " used"), team, { top: px(y) }); });
    });
    var grid = el("grid", T, { left: px(154), width: px(gridEnd - 154) });
    grid.style.left = px(154);
    xs.forEach(function (cx, c) {
      var r = rounds[c] || null;
      setText(text("din", T, cx, 21, 32, 8, "c", null, "num"), ("0" + (c + 1)).slice(-2));
      SIDES.forEach(function (side, n) {
        var cell = el("cell", T, { left: px(cx), top: px(36 + n * 36) });
        if (r && r.winner === side) {
          cell.classList.add("won");
          cell.style.setProperty("--c", COL[side]);
          var icon = WIN_ICON[r.win_type] ? r.win_type : "Elimination";
          cell.style.setProperty("--icon", 'url("assets/win-' + icon + '.png")');
        }
      });
      if (c + 1 === now) el("now", T, { left: px(cx - 3) });
    });
    [12, 24].forEach(function (c) { if (cols > c) el("half", T, { left: px(xs[c] - 9) }); });
  }

  // -------------------------------------------------------------- tabs
  function gun(p) {
    var w = p.weapon || "";
    if (!w || w === "Knife") return { side: "", main: "" };
    var src = "/hud/Resources/Armas/" + encodeURIComponent(w) + ".png";
    return SIDEARMS[w] ? { side: src, main: "" } : { side: "", main: src };
  }
  function shieldCode(p) { return p.regen_shield ? "R" : p.shield >= 50 ? "50" : p.shield > 0 ? "25" : ""; }
  function setTab(o, p, m, duo, top) {
    var t = o.el, dead = p.alive === false;
    if (o._top !== top) { o._top = top; t.style.top = px(top); }
    toggle(t, "dead", dead);
    var o2 = m.observed;
    toggle(t, "watched", !!o2 && o2.team === p.team && o2.slot === p.slot && !dead);
    // (no low-health tint: a tab keeps its colours whatever the damage, owen 2026-11-18)
    bg(o.agent, agentArt(p.agent));
    setText(o.name, p.name || "");
    setAbilities(o.abil, p);
    setUlt(o.ult, p.agent, p.ult_points, p.ult_max);
    setText(o.creds, money(p.credits));
    setText(o.dcreds, money(p.credits));
    var g = gun(p);
    bg(o.side_gun, g.side); bg(o.main_gun, g.main);
    var sc = shieldCode(p);
    toggle(o.shield, "hidden", !sc);
    setText(o.shield.num, sc === "R" ? "" : sc);
    setText(o.hp, Math.max(0, p.health || 0));
    setText(o.kda, [p.kills, p.deaths, p.assists].map(function (n) { return n || 0; }).join("/"));
    var hp = dead ? 100 : Math.max(0, Math.min(100, p.health || 0));
    var w = hp + "%";
    if (o.hpfill.style.width !== w) o.hpfill.style.width = w;
    // the spike carrier's badge, by the tab's top outer corner
    var carrier = m.spike && m.spike.state === "carried" && m.spike.carrier && m.phase !== "end" &&
      m.spike.carrier[0] === p.team && m.spike.carrier[1] === p.slot;
    toggle(o.badge, "on", !!carrier && !dead);
    o.badge.style.top = px(top - 6);
    o.badge.style[o.side === "left" ? "left" : "right"] = px(11);
  }
  function setRow(r, p, m) {
    var dead = p.alive === false && m.phase !== "buy";
    setText(r.creds, money(p.credits));
    setText(r.spent, p.spent > 0 ? "-" + money(p.spent) : "");
    setAbilities(r.abil, p);
    var sc = shieldCode(p);
    toggle(r.shieldImg, "heavy", sc === "50");
    toggle(r.shield, "hidden", !sc || sc === "50");
    setText(r.shield.num, sc === "R" ? "" : sc);
    var g = gun(p);
    bg(r.gun, g.main || g.side);
    setUlt(r.ult, p.agent, p.ult_points, p.ult_max);
    bg(r.agent, agentArt(p.agent));
    setText(r.name, p.name || "");
    setText(r.kda, [p.kills, p.deaths, p.assists].map(function (n) { return n || 0; }).join("/"));
    var o2 = m.observed;
    toggle(r.wbox, "watched", !!o2 && o2.team === p.team && o2.slot === p.slot);
    toggle(r.wbox, "dead", dead);
  }

  // ---------------------------------------------------------------- ace
  var ace = { shown: {}, until: 0, timer: null };
  // A player's headshot: the team's roster photos ([[in-game ID, path]]),
  // matched by in-game ID with any Riot tag and case aside.
  function playerPhoto(team, p) {
    var key = function (v) { return String(v || "").split("#")[0].trim().toLowerCase(); };
    var want = [key(p.name), key(p.riot_id)].filter(Boolean);
    var hit = ((team || {}).photos || []).filter(function (r) { return want.indexOf(key(r[0])) >= 0; })[0];
    return hit ? hit[1] : "";
  }
  function showAce(s, info) {
    var cfg = s.config, p = s.game.players.filter(function (q) { return q.team === info.team && q.slot === info.slot; })[0] || {};
    ui.ace.style.setProperty("--c", COL[info.team] || COL.left);
    // Their headshot from the GFX Engine's Teams tab (Control: Ace graphic
    // picture), else their agent.
    var photo = (cfg.ace_pictures || {})[info.team] === "agent" ? "" : playerPhoto(cfg[info.team], p);
    toggle(ui.aceWho, "photo", !!photo);
    bg(ui.aceWho, photo ? url(photo) : p.agent ? "/select/Resources/Agentes/" + encodeURIComponent(p.agent) + "/" + encodeURIComponent(p.agent) + ".png" : "");
    setText(ui.aceTeam, upper((cfg[info.team] || {}).name));
    if (!ui.aceLogo.parentNode || ui.aceLogo.parentNode !== ui.aceTeam) ui.aceTeam.appendChild(ui.aceLogo);
    img(ui.aceLogo, url((cfg[info.team] || {}).logo));
    setText(ui.acePlayer, upper(p.name || ""));
    setText(ui.aceLine, info.n ? ordinal(info.n) + " ACE OF THE MAP" : "ROUND " + (info.round || ""));
    ui.ace.classList.add("on");
    clearTimeout(ace.timer);
    ace.until = Date.now() + 7000;
    ace.timer = setTimeout(function () { ui.ace.classList.remove("on"); }, 7000);
  }
  function checkAce(s) {
    var a = s.game.match.ace, cfg = s.config, first = !ace.ready;
    ace.ready = true;
    if (!a) return;
    var key = [s.game.match.map, a.round, a.team, a.slot].join("|");
    if (ace.shown[key]) return;
    ace.shown[key] = true;
    // (one from before this page opened isn't played again)
    if (!first && (cfg.show || {}).ace !== false) showAce(s, a);
  }

  // ------------------------------------------------------------- banner
  var won = { key: "", until: 0 };
  function setBanner(s) {
    var cfg = s.config, m = s.game.match, txt = "", c = "#fff";
    if (cfg.tech_pause) txt = "TECHNICAL PAUSE";
    else if (cfg.timeout_call === "left" || cfg.timeout_call === "right") {
      txt = "TIMEOUT · " + upper(cfg[cfg.timeout_call].tricode || cfg[cfg.timeout_call].name);
      c = COL[cfg.timeout_call];
    }
    toggle(ui.banner, "on", !!txt && !BOARD_ONLY);
    if (txt) { setText(ui.bannerText, txt); ui.banner.style.setProperty("--c", c); }
  }

  // A round won (a score went up, not on the page's first look): the old
  // HUD's banner, opening from the middle, for 5 seconds.
  var rwin = { score: null, timer: null, inner: null };
  function checkRoundWin(s) {
    var m = s.game.match, cfg = s.config, now = [m.score.left || 0, m.score.right || 0], was = rwin.score;
    rwin.score = now;
    if (!was || BOARD_ONLY) return;
    var side = now[0] > was[0] ? "left" : now[1] > was[1] ? "right" : "";
    if (!side || now[0] + now[1] !== was[0] + was[1] + 1) return;   // (one round: not a map reset or a correction)
    ui.rwinSide.textContent = m.attackers === side ? "ATK" : "DEF";
    img(ui.rwinLogo, url(cfg[side].logo));
    ui.rwinTeam.textContent = upper(cfg[side].tricode || cfg[side].name);
    var R = ui.rwin;
    clearTimeout(rwin.timer); clearTimeout(rwin.inner);
    R.classList.remove("on", "text");
    void R.offsetWidth;
    R.classList.add("on");
    rwin.inner = setTimeout(function () { R.classList.add("text"); }, 100);
    rwin.timer = setTimeout(function () { R.classList.remove("on", "text"); }, 5100);
  }

  // ------------------------------------------------------------- listen
  var listenSide = "";
  function setListen(s) {
    var cfg = s.config, side = params.get("listen") || (cfg.show || {}).listen_in || "";
    if (side !== "left" && side !== "right") side = "";
    listenSide = side;
    toggle(ui.listen, "on", !!side && !BOARD_ONLY);
    if (!side) return;
    img(ui.listenLogo, url(cfg[side].logo));
    var duo = Number(cfg.team_size) === 2, n = duo ? 2 : 5;
    ui.tiles.forEach(function (t, i) {
      t.side = side;
      t.slot = i + 1;
      t.el.style.display = i < n ? "" : "none";
      t.el.style.left = px((1015 - n * 197 - 1) / 2 + i * 197);
      var p = s.game.players.filter(function (q) { return q.team === side && q.slot === i + 1; })[0] || {};
      setText(t.name, p.name || "");
    });
  }
  // web/cams.js puts each player's cam into these while Listen In is up.
  window.sccCamTiles = function () {
    if (!listenSide) return [];
    return ui.tiles.filter(function (t) { return t.el.style.display !== "none"; });
  };

  // -------------------------------------------------------------- apply
  var sent = {};
  // The team colours go with the sides (owen, 2026-11-18): the left team is
  // blue and the right red in the first half; they swap at round 13, and
  // every round in overtime, as the sides do.
  function sidesSwapped(round) {
    if (round <= 12) return false;
    if (round <= 24) return true;
    return (round - 25) % 2 === 1;
  }
  function applyState(s) {
    var g = s.game, m = g.match, cfg = s.config;
    var duo = Number(cfg.team_size) === 2;
    toggle(document.documentElement, "scc-2v2", duo);
    var round = Math.max(1, m.round || (m.rounds || []).length + 1);
    var swapped = !duo && (params.get("half") ? params.get("half") === "2" : sidesSwapped(round));
    if (sent.swapped !== swapped) {
      sent.swapped = swapped;
      var root = document.documentElement.style;
      root.setProperty("--left", swapped ? "var(--red)" : "var(--blue)");
      root.setProperty("--right", swapped ? "var(--blue)" : "var(--red)");
    }

    // Top bar.
    var T = ui.top;
    img(T.logoL, url(cfg.left.logo)); img(T.logoR, url(cfg.right.logo));
    setText(T.triL, upper(cfg.left.tricode)); setText(T.triR, upper(cfg.right.tricode));
    setText(T.subL, upper(cfg.left.name)); setText(T.subR, upper(cfg.right.name));
    setText(T.scoreL, m.score.left || 0); setText(T.scoreR, m.score.right || 0);
    var need = Math.max(1, Math.min(4, Math.ceil((cfg.best_of || 1) / 2)));
    setPips(T.pipsL, need, Math.min(need, cfg.left.wins || 0));
    setPips(T.pipsR, need, Math.min(need, cfg.right.wins || 0));
    setText(T.rnd, "ROUND " + Math.max(1, m.round || (m.score.left || 0) + (m.score.right || 0) + 1));
    var planted = m.spike && m.spike.state === "planted";
    setText(T.clock, g.connected || (s.app || {}).mode === "demo" ? clock(planted && m.spike.timer ? m.spike.timer : m.timer) : "");
    toggle(T.clock, "spike", planted);
    // Condensed (owen's "Condensed with Timer / Spike"): 20.5 seconds into
    // the round, or once the spike is down; the full bar again in the buy phase.
    var cond = !BOARD_ONLY && wantCondensed(m, planted);
    toggle(ui.topBox, "cond", cond);
    toggle(ui.topBox, "planted", planted);
    toggle(ui.planted, "on", planted && !cond && !BOARD_ONLY);
    setBanner(s);
    checkRoundWin(s);

    // Maps, event, sponsors.
    setMaps(cfg);
    var ev = cfg.event_text || [cfg.event, cfg.stage].filter(Boolean).join(" | ");
    setText(ui.eventText, upper(ev));
    toggle(ui.event, "hidden", !ev || BOARD_ONLY);
    setSponsors(cfg.sponsors, cfg.sponsor_seconds);
    toggle(ui.event, "solo", ui.sponsor.classList.contains("hidden"));   // (no sponsor box to run under)
    setStrips(wantStrips(m, cfg));

    // Players.
    g.players.forEach(function (p) {
      var side = p.team === "left" ? "left" : "right", i = (p.slot || 1) - 1;
      if (i < 0 || i > 4) return;
      var top = duo ? (i < 2 ? DUO_TOPS[i] : TAB_TOPS[i]) : TAB_TOPS[i];
      setTab(ui.tabs[side][i], p, m, duo, top);
      setRow(ui.rows[side][i], p, m);
    });
    img(ui.markL, url(cfg.left.logo)); img(ui.markR, url(cfg.right.logo));
    setTracker(cfg, m);

    // Listen In, Ace (they take the place of the board / the cam).
    setListen(s);
    checkAce(s);
    var aceOn = ui.ace.classList.contains("on");
    var board = !NO_BOARD && !listenSide && wantBoard(m, cfg);
    if (NO_BOARD && !BOARD_ONLY) {
      // (the board is its own source: the tabs still make way for it)
      var b2 = wantBoard(m, cfg);
      toggle(ui.board, "hidden", true);
      if (b2 !== sent.away) {
        sent.away = b2;
        toggle(ui.side.left, "away", b2); toggle(ui.side.right, "away", b2);
      }
    } else setBoard(board);

    // The spectated player's cam (web/cams.js), restyled by scc2027.css.
    if (typeof window.renderCams === "function" && !BOARD_ONLY) {
      window.renderCams(s, !!boardOn || !!listenSide || aceOn);
      var cam = document.getElementById("scc-cam");
      if (cam) {
        if (!cam._agent) cam._agent = el("s27-agent", cam.querySelector(".scc-frame") || cam);
        var o = m.observed, p = o && g.players.filter(function (q) { return q.team === o.team && q.slot === o.slot; })[0];
        if (p) {
          cam.style.setProperty("--side", COL[p.team === "left" ? "left" : "right"]);
          bg(cam._agent, agentArt(p.agent));
        }
        toggle(cam, "s27-off", !!listenSide || aceOn);
      }
    }
  }

  // Previews: ?ace=1 shows the Ace graphic for the spectated (or first) player.
  var previewed = false;
  function previews(s) {
    if (previewed) return;
    previewed = true;
    if (params.get("ace")) {
      var o = s.game.match.observed || { team: "left", slot: 1 };
      showAce(s, { team: o.team, slot: o.slot, n: 1, round: s.game.match.round });
      clearTimeout(ace.timer);
    }
  }

  function poll() {
    fetch("/api/state", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) { applyState(s); previews(s); })
      .catch(function (e) { if (window.console) console.warn(e); })
      .then(function () { setTimeout(poll, 250); });
  }

  if (params.get("fit") === "1") {
    var fitPage = function () {
      var k = Math.min(innerHeight / 1080, innerWidth / 1920), root = document.documentElement.style;
      root.transformOrigin = "0 0";
      root.transform = "translateX(" + (innerWidth - 1920 * k) / 2 + "px) scale(" + k + ")";
    };
    addEventListener("resize", fitPage);
    fitPage();
  }
  // (names fit again once the fonts are in: they change the widths)
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () {
    stage.querySelectorAll(".t").forEach(function (b) { b.fitted = false; if (b.i) fit(b); });
  });
  poll();
})();
