/* TextInk: the box the letters of some text really cover on screen, like the
 * box Figma draws around a text layer, instead of the text's whole frame.
 *
 *   TextInk.rect(el)  ->  { left, top, right, bottom } in page (client) pixels, or null
 *
 * Each run of text is measured where the browser laid it out (its line boxes),
 * then trimmed to its glyphs with the font's own metrics (a canvas measureText):
 * from the top of the tallest letter to the bottom of the lowest one, and from
 * the first letter's ink to the last one's (trailing spaces and tracking left out).
 * Pictures inside the text (team logos) count too. It only measures: nothing on
 * the page is changed, so text draws exactly where it did.
 *
 * The same file is in apps/gfxengine/web and apps/hudbuilder/web, and the same
 * function is inside apps/hudbuilder/web/hudedit.js (tests check they match).
 */
(function () {
  "use strict";
  // --- text ink ---
  var inkCtx = null;
  function inkMeasure(cs, s) {
    if (!inkCtx) inkCtx = document.createElement("canvas").getContext("2d");
    if (!inkCtx) return null;
    inkCtx.font = [cs.fontStyle, cs.fontVariant === "small-caps" ? "small-caps" : "", cs.fontWeight, cs.fontSize, cs.fontFamily].join(" ");
    if ("letterSpacing" in inkCtx) inkCtx.letterSpacing = cs.letterSpacing && cs.letterSpacing !== "normal" ? cs.letterSpacing : "0px";
    var m = inkCtx.measureText(s);
    return m && m.fontBoundingBoxAscent != null && m.actualBoundingBoxAscent != null ? m : null;
  }
  function inkCase(s, t) {
    if (t === "uppercase") return s.toUpperCase();
    if (t === "lowercase") return s.toLowerCase();
    if (t === "capitalize") return s.replace(/(^|\s)(\S)/g, function (a, b, c) { return b + c.toUpperCase(); });
    return s;
  }
  function inkRect(el) {
    if (!el || !el.getBoundingClientRect) return null;
    var box = null;
    function add(l, t, r, b) {
      if (!(r > l) || !(b > t)) return;
      if (!box) box = { left: l, top: t, right: r, bottom: b };
      else { box.left = Math.min(box.left, l); box.top = Math.min(box.top, t); box.right = Math.max(box.right, r); box.bottom = Math.max(box.bottom, b); }
    }
    var walk = document.createTreeWalker(el, 5 /* elements + text */), n = el, range = document.createRange();
    for (; n; n = walk.nextNode()) {
      if (n.nodeType === 1) {
        if (/^(img|image|video|canvas|svg)$/i.test(n.localName) && n !== el && !(n.closest && n.closest("text"))) {
          var pr = n.getBoundingClientRect();
          if (pr.width > 0.5 && pr.height > 0.5 && getComputedStyle(n).visibility !== "hidden") add(pr.left, pr.top, pr.right, pr.bottom);
        }
        continue;
      }
      var text = n.nodeValue || "", p = n.parentElement;
      if (!p || !/\S/.test(text)) continue;
      var cs = getComputedStyle(p);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      var svg = typeof SVGElement !== "undefined" && p instanceof SVGElement;
      var rects = [];
      if (svg) {
        var sr = p.getBoundingClientRect();
        if (sr.width > 0.01 && sr.height > 0.01) rects.push(sr);
      } else {
        range.selectNodeContents(n);
        var list = range.getClientRects();
        for (var i = 0; i < list.length; i++) if (list[i].width > 0.01 && list[i].height > 0.01) rects.push(list[i]);
      }
      if (!rects.length) continue;
      var shown = inkCase(text, cs.textTransform);
      var all = inkMeasure(cs, shown.replace(/\s+/g, " "));
      if (!all) { rects.forEach(function (r) { add(r.left, r.top, r.right, r.bottom); }); continue; }
      var fa = all.fontBoundingBoxAscent, fd = all.fontBoundingBoxDescent;
      // (one line of measured text for each line box, when they pair up)
      var lines = svg && p.firstElementChild ? [] : shown.split("\n").filter(function (s) { return s.length; });
      var paired = lines.length === rects.length;
      for (var j = 0; j < rects.length; j++) {
        var r = rects[j];
        // (how big the page draws it: the box's height over the font's)
        var ky = r.height / Math.max(1e-6, fa + fd);
        var base = r.top + fa * ky;
        var top = base - all.actualBoundingBoxAscent * ky, bottom = base + all.actualBoundingBoxDescent * ky;
        var left = r.left, right = r.right;
        if (paired) {
          if (!/\S/.test(lines[j])) continue;
          var m = inkMeasure(cs, lines[j]);
          if (m && m.width > 0) {
            var kx = r.width / m.width;   // (squeezed text is narrower than the font)
            var ml = r.left - m.actualBoundingBoxLeft * kx, mr = r.left + m.actualBoundingBoxRight * kx;
            if (mr > ml) { left = ml; right = mr; }
            top = base - m.actualBoundingBoxAscent * ky; bottom = base + m.actualBoundingBoxDescent * ky;
          }
        }
        add(left, top, right, bottom);
      }
    }
    if (box) {
      // (text cut off by its box: only what's shown)
      var ecs = getComputedStyle(el);
      if (ecs.overflow !== "visible" && ecs.overflow !== "") {
        var er = el.getBoundingClientRect();
        box = { left: Math.max(box.left, er.left), top: Math.max(box.top, er.top), right: Math.min(box.right, er.right), bottom: Math.min(box.bottom, er.bottom) };
        if (box.right <= box.left || box.bottom <= box.top) return null;
      }
    }
    return box;
  }
  // --- end text ink ---
  window.TextInk = { rect: inkRect };
})();
