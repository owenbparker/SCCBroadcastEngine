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
    // the shield outline (light 25 / heavy 50), or the game's round regen
    // shield icon: a ring around a disc with an arrow cut out of it
    wrap.innerHTML = '<svg class="sh" width="21" height="21" viewBox="-1 -1 22.7 22.7"><path d="M10.33 0L0 5.17 2.58 15.5 10.33 20.67 18.08 15.5 20.66 5.17Z"' +
      ' fill="none" stroke="#fff" stroke-width="1.1" stroke-linejoin="round"/></svg>' +
      '<svg class="rg" width="21" height="21" viewBox="0 0 21 21"><defs><mask id="scc-regen-cut"><rect width="21" height="21" fill="#fff"/>' +
      '<path d="M8.1 13.2V11.1L10.5 8.7 12.9 11.1V13.2L10.5 10.8Z" fill="#000"/></mask></defs>' +
      '<circle cx="10.5" cy="10.5" r="9.3" fill="none" stroke="#fff" stroke-width="1.5"/>' +
      '<circle cx="10.5" cy="10.5" r="7" fill="none" stroke="#fff" stroke-width=".8" stroke-dasharray="7.5 3.5" transform="rotate(-62 10.5 10.5)"/>' +
      '<circle cx="10.5" cy="10.5" r="4.9" fill="#fff" mask="url(#scc-regen-cut)"/></svg>';
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
      // Full ult: one solid white ring (owen's "Full Ult" treatment).
      if (points >= max) out = '<circle cx="' + c + '" cy="' + c + '" r="' + r + '" fill="none" stroke="#fff" stroke-width="4"/>';
      else for (var i = 0; i < max; i++) {
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
  // owen's "Main with Hole" / "Condensed with Hole" figs: two halves with a
  // hole in the middle (890..1030) where the game's own timer shows; screen
  // coordinates throughout.
  el("ol t", top); el("ol b", top);   // (the outline carries on over the hole, owen)
  ["l", "r"].forEach(function (k) { var h = el("half " + k, top); el("fill", h); el("edge", h); });
  el("div l", top); el("div r", top);
  ui.top = {
    logoL: el("logo l", top, null, "img"), logoR: el("logo r", top, null, "img"),
    triL: text("tung", top, 714, 18, 100, 22, "c", null, "tri"), subL: text("nar", top, 709, 45, 110, 10, "c", null, "sub"),
    triR: text("tung", top, 1100, 18, 100, 22, "c", null, "tri"), subR: text("nar", top, 1095, 45, 110, 10, "c", null, "sub"),
    scoreL: text("nar", top, 860, 18, 60, 36, "c", null, "score"), scoreR: text("nar", top, 998, 18, 60, 36, "c", null, "score"),
    rnd: text("nar", top, 910, 11, 100, 10, "c", null, "rnd"),
    pipsL: el("pips v l", top), pipsR: el("pips v r", top)
  };
  ui.top.logoL.alt = ui.top.logoR.alt = "";
  ui.top.pipsL.style.setProperty("--c", COL.left);
  ui.top.pipsR.style.setProperty("--c", COL.right);
  // The planted spike: the Default 2026 HUD's spike icon, slid up into the
  // bar's hole (over the game's own) and flashing faster as it runs down.
  ui.bomb = el("", stage); ui.bomb.id = "bomb";
  ui.bombIcon = el("icon", ui.bomb);
  // The round win graphic: owen's "Round Win Graphic SCC" fig (1573 x 467),
  // a #F9C229 flash, then the panel; the winning team in the yellow bar as
  // (team, side, how they won; owen 2026-11-19).
  // (#rwin is the HUD's own, which HUD Builder copies restyle; #rwbug is
  // the one picked in Control > Round win bug, owen 2026-11-25, built the
  // same way so a copy's edits to #rwin never reach it.)
  function buildRwin(id) {
    var box = el("", stage); box.id = id;
    var o = { box: box };
    el("bg", box); o.flash = el("flash", box);
    // the crest: the round winner's logo (owen, 2026-11-19), the SCC crest
    // when the team has none
    o.crest = el("crest", box);
    o.word = text("nar", box, 329, 192, 916, 138, "c", null, "word");
    setText(o.word, "ROUND WIN");
    el("bar", box);
    var who = el("who", box);
    // the yellow bar: who, their side and how they won (no logo: it's up top)
    o.team = el("team", who, null, "span"); o.side = el("side", who, null, "span");
    o.how = el("how", who, null, "span");
    return o;
  }
  ui.rwinOwn = buildRwin("rwin");
  ui.rwinBug = buildRwin("rwbug");
  // Timeout and technical pause (owen's designs, 2026-11-25): built like the
  // round win bug, the calling team's logo in the crest (the St. Clair
  // Saints crest when they have none), TIMEOUT / TECH PAUSE, and the info in
  // the bar: blue for the defenders' timeout, red for the attackers', grey
  // for a technical pause.
  ui.tob = buildRwin("tobug");
  ui.tob.box.className = "";
  ui.banner = el("", stage); ui.banner.id = "banner";
  el("bar", ui.banner);
  ui.bannerText = text("nar", ui.banner, 8, 0, null, null, "c", null, "txt");
  ui.bannerText.style.right = "0"; ui.bannerText.style.bottom = "0";

  // Event strip, sponsor box. (The series' maps are on the buy-phase board
  // now, owen 2026-11-19: no maps strip along the top.)
  ui.event = el("phase", stage); ui.event.id = "event";
  ui.eventText = text("nar", ui.event, 0, 8, 394, 8, "c");   // (centred on 1492, as in the fig)
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
  ui.markL = el("mark", ui.board, { left: "651px" }, "img");
  ui.markR = el("mark", ui.board, { left: "1095px" }, "img");
  var ROW = 785, PITCH = 56;
  // (owen, 2026-11-25: the name boxes wider for longer names; the credits,
  // ability and gun boxes gave up the room)
  var BOXES = { left: { creds: [16, 160], abil: [185, 130], gun: [324, 188], who: [521, 435] },
                right: { creds: [1745, 160], abil: [1606, 130], gun: [1409, 188], who: [965, 435] } };
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
      r.abil = abilities(r.abox, [10, 50, 90], 7, inner);
      r.gbox = box("gun");
      r.shieldImg = place(el("shieldimg", r.gbox), 11, 13, inner);
      r.shield = shieldSvg(r.gbox); place(r.shield, 13, 15, inner);
      r.gun = place(el("gun", r.gbox), 44, 11, inner);
      r.ult = ultRing(r.gbox); place(r.ult, 138, 4.5, inner);
      r.wbox = box("who");
      r.wbox.classList.add("who");
      r.agent = el("agent", r.wbox);
      r.name = text("din", r.wbox, 85, 18, 240, 14, inner === "R" ? "r" : "", inner, "name");
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

  if (BOARD_ONLY) [top, ui.bomb, ui.banner, ui.tob.box, ui.event, ui.sponsor, ui.side.left, ui.side.right, ui.ace, ui.listen]
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
  // The buy phase, held (owen, 2026-11-20: the board flickered out before
  // the round whenever something crossed the BUY PHASE banner and a read
  // missed it). Once the buy phase is seen the board stays until the buy
  // timer's run out (0:00, by the last read of it), whatever the phase
  // reads say meanwhile; with no timer read, until the round has read as
  // under way for a few seconds running.
  // (owen, 2026-11-25: the board stayed up into the round, the phase still
  // reading "buy" at 1:28. Once the round's own clock (over 1:00) has been
  // read the round's under way: "buy" readings count again only from the
  // next round, by the score, on.)
  var buy = { on: false, endAt: 0, timer: null, otherSince: 0, running: null };
  function trackBuy(m, now) {
    var t = Number(m.timer) || 0, fresh = t !== buy.timer;
    var rounds = (m.score.left || 0) + (m.score.right || 0);
    buy.timer = t;
    if (buy.running !== null && buy.running !== rounds) buy.running = null;   // (a new round)
    if (fresh && t > 60 && m.phase !== "end") buy.running = rounds;
    if (m.phase === "buy" && buy.running === null) {
      if (!buy.on) { buy.on = true; buy.endAt = 0; }
      buy.otherSince = 0;
      // (a read of the buy timer: 0:30 down to 0:00; the board goes at 0:00)
      if (fresh && t > 0 && t <= 60) buy.endAt = now + t * 1000 + 900;
      return;
    }
    if (!buy.on) return;
    if (!buy.otherSince) buy.otherSince = now;
    var clockOn = fresh && t > 60;   // (the round's own 1:40 read: under way)
    if (buy.endAt ? now >= buy.endAt || clockOn : now - buy.otherSince >= SET("board.hold_without_timer", 3) * 1000) {
      buy.on = false; buy.endAt = 0;
    }
  }
  function wantBoard(m, cfg) {
    if ((cfg.show || {}).scoreboard) return true;
    if (buy.on) return !!SET("board.buy_phase", true);
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
      boardTimer = setTimeout(function () { toggle(ui.board, "away", false); }, SET("board.swap", PANELS_MS / 1000) * 1000);
    } else {
      toggle(ui.board, "away", true);
      boardTimer = setTimeout(function () { tabsAway(false); }, SET("board.swap", PANELS_MS / 1000) * 1000);
    }
  }

  // The round, as the top bar goes by it (owen, 2026-11-19: the bar kept
  // coming in and out). A read of the phase only counts once it's held for
  // HOLD_MS (one missed or stray BUY PHASE banner read changes nothing), the
  // round's clock runs from when it was first seen under way (not from the
  // timer read, which goes stale while the spike's down), and once a round
  // has condensed the bar it stays condensed until the next buy phase.
  //  - maps/event strips: out in the buy phase, tucked STRIPS_S into the
  //    round or at the plant;
  //  - condensed bar: COND_S into the round or at the plant; full again in
  //    the buy phase.
  var STRIPS_S = 20, COND_S = 20.5, HOLD_MS = 1200;

  // HUD Builder > Game HUDs (owen, 2026-11-19): these timings are settings
  // there (saved live, no code change), and the editor's Show buttons put
  // the HUD in any of its states to see and change every part.
  var HE = window.HudEdit || null;
  function SET(k, d) { return HE && HE.get ? HE.get(k, d) : d; }
  function EDIT_STATE() { return HE && HE.state ? HE.state() : ""; }
  var AUTO = [["auto", "By the round (normal)"], ["full", "Always full"], ["condensed", "Always small"]];
  if (HE && HE.settings) HE.settings([
    { group: "Top bar", key: "top.mode", label: "Top bar", type: "choice", def: "auto", options: AUTO, help: "Full in the buy phase, small once the round is under way." },
    { group: "Top bar", key: "top.condense_at", label: "Goes small this long into the round", type: "num", def: COND_S, unit: "s", min: 0, step: 0.5 },
    { group: "Top bar", key: "top.condense_on_plant", label: "Goes small when the spike is planted", type: "bool", def: true },
    { group: "Top bar", key: "round.settle", label: "A new phase counts once it's held for", type: "num", def: HOLD_MS / 1000, unit: "s", min: 0, step: 0.1, help: "Stops the bar going in and out on a stray read." },
    { group: "Event strip", key: "strips.mode", label: "Event strip", type: "choice", def: "auto", options: [["auto", "By the round (normal)"], ["shown", "Always out"], ["hidden", "Always tucked away"]] },
    { group: "Event strip", key: "strips.tuck_at", label: "Tuck away this long into the round", type: "num", def: STRIPS_S, unit: "s", min: 0, step: 0.5 },
    { group: "Event strip", key: "strips.tuck_on_plant", label: "Tuck away when the spike is planted", type: "bool", def: true },
    { group: "Scoreboard", key: "board.buy_phase", label: "Scoreboard up in the buy phase", type: "bool", def: true },
    { group: "Scoreboard", key: "board.hold_without_timer", label: "With no buy timer read, it goes once the round's read as under way for", type: "num", def: 3, unit: "s", min: 0, step: 0.5, help: "With the timer read, it stays until 0:00." },
    { group: "Scoreboard", key: "board.swap", label: "Player tabs and scoreboard swap over in", type: "num", def: 0.45, unit: "s", min: 0, step: 0.05 },
    { group: "Round win and Ace", key: "rwin.on", label: "Show the round win banner", type: "bool", def: true },
    { group: "Round win and Ace", key: "rwin.seconds", label: "Round win stays up for", type: "num", def: 4.7, unit: "s", min: 1, step: 0.1 },
    { group: "Round win and Ace", key: "ace.seconds", label: "Ace stays up for", type: "num", def: 7, unit: "s", min: 1, step: 0.5 }
  ]);
  if (HE && HE.states) HE.states([
    { id: "everything", label: "Everything", help: "Every part at once: scoreboard, player tabs, strips, spike, round win, Ace" },
    { id: "round", label: "Round in play", help: "Full top bar, strips out, player tabs" },
    { id: "condensed", label: "Top bar small", help: "The bar 20 s into a round" },
    { id: "planted", label: "Spike planted" },
    { id: "buy", label: "Buy phase", help: "The scoreboard up" },
    { id: "rwin", label: "Round win" },
    { id: "ace", label: "Ace" }
  ]);
  var rd = { phase: "", raw: "", rawAt: 0, startAt: 0, cond: false, strips: true };
  function trackRound(m, now) {
    var raw = m.phase === "buy" ? "buy" : m.phase === "combat" || m.phase === "end" ? "combat" : "";
    if (raw !== rd.raw) { rd.raw = raw; rd.rawAt = now; }
    var was = rd.phase;
    if (raw && raw !== rd.phase && (now - rd.rawAt >= SET("round.settle", HOLD_MS / 1000) * 1000 || !rd.phase)) rd.phase = raw;
    if (rd.phase === "combat" && was !== "combat") {
      // Under way from when it was first read so; joined mid-round (nothing
      // before it), by the round's clock if it reads 1:40 or under.
      rd.startAt = was === "buy" ? rd.rawAt : m.timer > 0 && m.timer <= 100 ? now - (100 - m.timer) * 1000 : now;
    }
    if (rd.phase === "buy" || !rd.phase) { rd.cond = false; rd.strips = true; rd.startAt = 0; }
    else {
      var t = (now - rd.startAt) / 1000;
      if ((bomb.on && SET("top.condense_on_plant", true)) || t >= SET("top.condense_at", COND_S)) rd.cond = true;
      if ((bomb.on && SET("strips.tuck_on_plant", true)) || t >= SET("strips.tuck_at", STRIPS_S)) rd.strips = false;
    }
  }
  function wantStrips(m, cfg) {
    if ((cfg.show || {}).scoreboard) return true;
    var mode = SET("strips.mode", "auto");
    if (mode === "shown" || mode === "hidden") return mode === "shown";
    return rd.strips;
  }
  function setStrips(on) {
    toggle(ui.event, "tucked", !on);
  }
  function wantCondensed() {
    if (params.get("condensed")) return params.get("condensed") === "1";
    var mode = SET("top.mode", "auto");
    if (mode === "full" || mode === "condensed") return mode === "condensed";
    return rd.cond;
  }

  // The spike (owen, 2026-11-19): up as soon as it's read planted, and kept
  // up through every flicker of that read (the game's icon flashes) until
  // the round's over and the game's own 6/7 second timer is back in the hole
  // (or the buy phase, or 10 seconds after the round's score has gone up).
  var bomb = { on: false, at: 0, timer: null, score: "", scoredAt: 0, backAt: 0, flash: null, lit: -1 };
  function trackBomb(m, now) {
    var seen = m.spike && m.spike.state === "planted";
    var score = (m.score.left || 0) + ":" + (m.score.right || 0);
    if (rd.phase === "buy" || !rd.phase) { bomb.on = false; return; }
    if (seen && !bomb.on) {
      bomb.on = true; bomb.at = now; bomb.timer = m.timer; bomb.score = score; bomb.scoredAt = 0; bomb.backAt = 0;
      return;
    }
    if (!bomb.on) return;
    if (seen) { bomb.timer = m.timer; bomb.backAt = 0; }
    if (score !== bomb.score && !bomb.scoredAt) bomb.scoredAt = now;
    // the game's own timer read again, a fresh 0:0x (not the one left from before the plant)
    var back = !seen && m.timer > 0 && m.timer <= 9 && m.timer !== bomb.timer;
    bomb.backAt = back ? bomb.backAt || now : 0;
    if ((bomb.backAt && now - bomb.backAt >= 400) || (bomb.scoredAt && now - bomb.scoredAt >= 10000)) bomb.on = false;
  }
  function setBomb(on) {
    if (on === ui.bomb.classList.contains("on")) return;
    toggle(ui.bomb, "on", on);
    clearInterval(bomb.flash); bomb.flash = null; bomb.lit = -1;
    ui.bombIcon.classList.remove("dim");
    if (!on) return;
    // the Default 2026 flashing: every second for 20 s, every half second
    // for 18 s, then three times a second (the spike's 45 seconds)
    bomb.flash = setInterval(function () {
      var e = (Date.now() - bomb.at) / 1000;
      var n = e < 20 ? Math.floor(e) : e < 38 ? 20 + Math.floor((e - 20) / .5) : 56 + Math.floor(Math.min(e - 38, 7) / (1 / 3));
      if (n === bomb.lit) return;
      bomb.lit = n;
      toggle(ui.bombIcon, "dim", n % 2 === 1);
    }, 50);
  }

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
  // The series' maps as cards at the end of the round tracker (owen's "SCC
  // Round with MAPS" / "MAP WINS" figs), from Map Bans: the map's picture,
  // the picker's logo, the map and CURRENT / NEXT; once played the winner's
  // logo, the map's score and "<TEAM> WIN"; the last map of the series not
  // yet reached, DECIDER.
  function mapCards(cfg) {
    var bo = Math.max(1, Number(cfg.best_of) || 3), shown = bo === 1 ? 1 : 3;
    var all = (cfg.maps || []).slice(0, bo), cur = cfg.current_map || 0;
    var first = shown === 3 ? Math.max(0, Math.min(cur - 1, all.length - 3)) : 0;
    var logo = function (side) { return side && cfg[side] && cfg[side].logo ? url(cfg[side].logo) : ""; };
    var out = [];
    for (var slot = 0; slot < shown; slot++) {
      var i = first + slot, map = all[i];
      if (!map || !map.name) continue;
      var art = "/map-art/" + encodeURIComponent(map.name), name = upper(map.name);
      if (map.winner) {
        var sc = map.score && map.score.left != null ? map.score.left + " - " + map.score.right : name;
        out.push({ art: art, logo: logo(map.winner), big: sc, small: upper(cfg[map.winner].tricode || cfg[map.winner].name) + " WIN" });
      } else if (i === cur) out.push({ art: art, logo: logo(map.picked_by), big: name, small: "CURRENT" });
      else if (bo > 1 && i === bo - 1) out.push({ art: art, logo: "", big: "DECIDER", small: "", decider: true });
      else out.push({ art: art, logo: logo(map.picked_by), big: name, small: "NEXT" });
    }
    return out;
  }

  // ------------------------------------------------------------ tracker
  function setTracker(cfg, m) {
    var rounds = m.rounds || [], played = rounds.length, now = Math.max(1, m.round || played + 1);
    // The full 24-round schedule from round 1 (owen); a 2v2 keeps 12 until it
    // goes past them. Overtime adds pairs of rounds after 24.
    var last = Math.max(now, played), duo = Number(cfg.team_size) === 2;
    var cols = duo && last <= 12 ? 12 : Math.max(24, Math.ceil(last / 2) * 2);
    var to = cfg.timeouts || {};
    var cards = mapCards(cfg);
    var key = JSON.stringify([cols, now, rounds, to, cfg.left.tricode, cfg.right.tricode, cfg.left.logo, cfg.right.logo, cards]);
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
    // (the map cards after the last round, 153 px apart, inside the grid's outline)
    var cardsAt = xs[cols - 1] + 32 + 9, gridEnd = cardsAt + cards.length * 153, width = gridEnd + 14;
    T.style.width = px(width);
    toggle(T, "wide", cols > 12);   // (the 24-round look: owen's Buy Phase file)
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
    cards.forEach(function (cd, n) {
      var card = el("map" + (cd.decider ? " decider" : ""), T, { left: px(cardsAt + n * 153) });
      card.style.backgroundImage = 'url("' + cd.art + '")';
      if (cd.logo) { var lg = el("logo", card, null, "img"); lg.alt = ""; lg.src = cd.logo; }
      if (cd.decider) { setText(text("din", card, 0, 35, 144, 14, "c", null, "big"), cd.big); return; }
      setText(text("din", card, 0, 42, 144, 14, "c", null, "big"), cd.big);
      setText(text("rubl", card, 0, 63, 144, 8, "c", null, "small"), cd.small);
    });
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
    toggle(o.shield, "regen", sc === "R");
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
    toggle(r.shield, "regen", sc === "R");
    setText(r.shield.num, sc === "R" ? "" : sc);
    var g = gun(p);
    bg(r.gun, g.main || g.side);
    setUlt(r.ult, p.agent, p.ult_points, p.ult_max);
    bg(r.agent, agentArt(p.agent));
    setText(r.name, p.name || "");
    setText(r.kda, [p.kills, p.deaths, p.assists].map(function (n) { return n || 0; }).join("/"));
    // (no spectated-player outline on the buy-phase board: the observer is
    // often not on a POV there, owen)
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
    var aceMs = SET("ace.seconds", 7) * 1000;
    ace.until = Date.now() + aceMs;
    ace.timer = setTimeout(function () { ui.ace.classList.remove("on"); }, aceMs);
  }
  // The round win and the Ace held up while HUD Builder shows them.
  var shownByEditor = { rwin: false, ace: false };
  function editorShows(s, st) {
    var wantR = st === "rwin" || st === "everything", wantA = st === "ace" || st === "everything";
    if (wantR && !shownByEditor.rwin) showRoundWin(s, "left", true);
    if (!wantR && shownByEditor.rwin) hideRoundWin();
    shownByEditor.rwin = wantR;
    if (wantA && !shownByEditor.ace) {
      var o = s.game.match.observed || { team: "left", slot: 1 };
      showAce(s, { team: o.team || "left", slot: o.slot || 1, n: 1, round: s.game.match.round });
      clearTimeout(ace.timer);
    }
    if (!wantA && shownByEditor.ace) ui.ace.classList.remove("on");
    shownByEditor.ace = wantA;
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
  // The timeout / technical pause banner (#tobug): up while Control's (or
  // the screen reader's) timeout or technical pause is on.
  var tob = { key: "", timer: null, secs: null, secsAt: 0 };
  function setBanner(s) {
    var cfg = s.config, m = s.game.match, kind = "", team = "";
    if (cfg.tech_pause) kind = "tech";
    else if (cfg.timeout_call === "left" || cfg.timeout_call === "right") {
      team = cfg.timeout_call;
      kind = m.attackers === team ? "attack" : "defend";
    }
    if (BOARD_ONLY) kind = "";
    toggle(ui.banner, "on", false);   // (the old strip: replaced by the banner)
    var o = ui.tob, B = o.box;
    var live = m.timeout || {};
    var key = kind + "|" + team;
    if (kind) {
      // the bar: who called it and their side
      o.team.textContent = team ? upper(cfg[team].tricode || cfg[team].name) : "PLEASE STAND BY";
      o.side.textContent = team ? (kind === "attack" ? "ATTACK" : "DEFENSE") : "";
      // ...and the timeout's countdown, from the reader's readings of the
      // game's bar (owen, 2026-11-25: in place of the timeouts left),
      // ticking down between reads
      var clock = "";
      if (team && live.team === team) {
        if (live.seconds != null) {
          if (live.seconds !== tob.secs) { tob.secs = live.seconds; tob.secsAt = Date.now(); }
          var t = Math.max(0, Math.ceil(tob.secs - (Date.now() - tob.secsAt) / 1000));
          clock = Math.floor(t / 60) + ":" + ("0" + (t % 60)).slice(-2);
        } else if (live.state === "starting") clock = "STARTING";
      } else tob.secs = null;
      if (o.how.textContent !== clock) o.how.textContent = clock;
      toggle(o.side, "hidden", !team);
      toggle(o.how, "hidden", !clock);
    }
    if (key === tob.key) return;
    tob.key = key;
    clearTimeout(tob.timer);
    if (!kind) {   // down: the banner's colour wipes over it and closes up
      if (B.classList.contains("on")) {
        B.classList.add("wipe", "out");
        tob.timer = setTimeout(function () { B.className = ""; }, 800);
      }
      return;
    }
    setText(o.word, kind === "tech" ? "TECH PAUSE" : "TIMEOUT");
    var logo = team && cfg[team].logo ? url(cfg[team].logo) : "";
    o.crest.style.backgroundImage = logo ? 'url("' + logo + '")' : "";
    B.className = kind;
    void B.offsetWidth;
    B.classList.add("on");
    tob.timer = setTimeout(function () { B.classList.add("text"); }, 750);
  }

  // A round won (a score went up, not on the page's first look): the round
  // win graphic for 5 seconds.
  var rwin = { score: null, timer: null, inner: null, out: null };
  var WIN_WORDS = { Deactivation: "DEFUSAL", Time: "TIME", Elimination: "KILLS", Detonation: "SPIKE DETONATION" };
  function checkRoundWin(s) {
    var m = s.game.match, now = [m.score.left || 0, m.score.right || 0], was = rwin.score;
    rwin.score = now;
    if (!was || BOARD_ONLY) return;
    var side = now[0] > was[0] ? "left" : now[1] > was[1] ? "right" : "";
    if (!side || now[0] + now[1] !== was[0] + was[1] + 1) return;   // (one round: not a map reset or a correction)
    if (!SET("rwin.on", true)) return;
    showRoundWin(s, side, false);
  }
  // The round win bugs to pick from (Control > Round win bug): "own" is the
  // HUD's own (SCC 2027, or a HUD Builder copy's restyled one), the others
  // are drawn in #rwbug. in / out: the colour wipe at the start and the end
  // ("" = none: the graphic just fades out, as it always has).
  var BUGS = {
    own: { cls: "", in: "", out: "" },
    scc2027: { cls: "scc", in: "", out: "" },
    cen: { cls: "cen", in: "#FC003B", out: "#FC003B" }
  };
  function hexOk(v) { return /^#?[0-9a-f]{6}$/i.test(v || "") ? (v.charAt(0) === "#" ? v : "#" + v) : ""; }
  function rwinLook(cfg) {
    var rw = cfg.round_win || {}, bug = BUGS[rw.bug] ? rw.bug : "own", b = BUGS[bug];
    if (params.get("bug") && BUGS[params.get("bug")]) { bug = params.get("bug"); b = BUGS[bug]; }
    return { bug: bug, cls: b.cls, in: hexOk(rw.intro) || b.in, out: hexOk(rw.outro) || b.out };
  }
  function wipe(c) {
    return "linear-gradient(90deg, transparent, " + c + " 20%, " + c + " 79.8%, transparent)";
  }
  function hideRoundWin() {
    clearTimeout(rwin.timer); clearTimeout(rwin.inner); clearTimeout(rwin.out);
    [ui.rwinOwn, ui.rwinBug].forEach(function (o) { o.box.classList.remove("on", "text", "out", "wipe"); });
  }
  function showRoundWin(s, side, hold) {
    var m = s.game.match, cfg = s.config, look = rwinLook(cfg);
    hideRoundWin();
    var o = look.bug === "own" ? ui.rwinOwn : ui.rwinBug;
    if (o === ui.rwinBug) o.box.className = look.cls;
    o.side.textContent = m.attackers === side ? "ATTACK" : "DEFENSE";
    var logo = cfg[side].logo ? url(cfg[side].logo) : "";
    o.crest.style.backgroundImage = logo ? 'url("' + logo + '")' : "";
    o.team.textContent = upper(cfg[side].tricode || cfg[side].name);
    // how: this round's entry in the round history (or the last round won)
    var rounds = m.rounds || [], last = rounds[rounds.length - 1];
    var how = m.win_type || (last && last.winner === side ? last.win_type : "");
    o.how.textContent = WIN_WORDS[how] || "";
    toggle(o.how, "hidden", !WIN_WORDS[how]);
    // the intro colour (inline and important: over a copy's own edits too)
    if (look.in) o.flash.style.setProperty("background-image", wipe(look.in), "important");
    else o.flash.style.removeProperty("background-image");
    var R = o.box;
    void R.offsetWidth;
    R.classList.add("on");
    rwin.inner = setTimeout(function () { R.classList.add("text"); }, 750);
    if (hold) return;
    var rwMs = SET("rwin.seconds", 4.7) * 1000;
    rwin.out = setTimeout(function () {
      // the outro: a colour wipe over the graphic that then closes up, or
      // (no outro colour) a fade
      if (look.out) {
        o.flash.style.setProperty("background-image", wipe(look.out), "important");
        R.classList.add("wipe");
      }
      R.classList.add("out");
    }, rwMs);
    rwin.timer = setTimeout(hideRoundWin, rwMs + (look.out ? 800 : 400));
  }
  // Control's "Test" button: plays the picked bug once (left team).
  var rwTest = null;
  function checkRwinTest(s) {
    var t = (s.config.round_win || {}).test || 0;
    if (rwTest !== null && t !== rwTest && !BOARD_ONLY) showRoundWin(s, "left", false);
    rwTest = t;
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
    // (no clock: the game's own timer shows through the bar's hole)
    var now = Date.now();
    trackRound(m, now);
    trackBuy(m, now);
    trackBomb(m, now);
    // Condensed (owen's "Condensed with Hole"): 20.5 seconds into
    // the round, or once the spike is down; the full bar again in the buy phase.
    var st = EDIT_STATE();   // (HUD Builder's Show buttons, only while editing)
    var cond = !BOARD_ONLY && (st ? st === "condensed" || st === "planted" : wantCondensed());
    var bombShown = st ? st === "planted" || st === "everything" : bomb.on;
    toggle(ui.topBox, "cond", cond);
    toggle(ui.topBox, "planted", bombShown);
    setBomb(bombShown && !BOARD_ONLY);
    setBanner(s);
    checkRoundWin(s);
    checkRwinTest(s);

    // Maps, event, sponsors.
    var ev = cfg.event_text || [cfg.event, cfg.stage].filter(Boolean).join(" | ");
    setText(ui.eventText, upper(ev));
    toggle(ui.event, "hidden", !ev || BOARD_ONLY);
    setSponsors(cfg.sponsors, cfg.sponsor_seconds);
    toggle(ui.event, "solo", ui.sponsor.classList.contains("hidden"));   // (no sponsor box to run under)
    setStrips(st ? st === "everything" || st === "round" || st === "buy" : wantStrips(m, cfg));

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
    editorShows(s, st);
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
    } else if (st === "everything") {   // (the board and the player tabs both out, to see and change them)
      boardOn = "editor"; clearTimeout(boardTimer);
      toggle(ui.board, "away", false); toggle(ui.side.left, "away", false); toggle(ui.side.right, "away", false);
    } else setBoard(st ? st === "buy" : board);

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
    if (params.get("rwin")) showRoundWin(s, params.get("rwin") === "right" ? "right" : "left", true);
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
