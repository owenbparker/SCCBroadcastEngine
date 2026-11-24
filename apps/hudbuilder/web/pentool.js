// The pen tool, as in Figma and Photoshop: click for corner points, click and
// drag for curves (Alt while dragging breaks the handles apart), Shift keeps
// lines at 45°, click the first point to close the shape, Enter / Esc /
// double-click to finish an open line, Backspace takes off the last point.
// Editing a path's points: drag a point or a handle (Alt: just that handle),
// click a line to add a point there, Alt + click a point to make it a corner
// or a curve, Delete removes the picked point, Enter / Esc / click outside to finish.
//
// The same file is in the GFX Engine (Composer) and HUD Builder.
// Points: {x, y, ix, iy, ox, oy} (the handles in and out, where there are any).
"use strict";

(function () {
  const NS = "http://www.w3.org/2000/svg";
  const Pen = (window.PenTool = {});
  const near = (a, b, r) => Math.hypot(a[0] - b[0], a[1] - b[1]) <= r;
  const clone = pts => pts.map(p => Object.assign({}, p));

  // --- geometry -------------------------------------------------------------------
  const lerp = (a, b, t) => a + (b - a) * t;
  function cubic(a, b, t) {
    const p0 = [a.x, a.y], p1 = [a.ox ?? a.x, a.oy ?? a.y], p2 = [b.ix ?? b.x, b.iy ?? b.y], p3 = [b.x, b.y], u = 1 - t;
    return [0, 1].map(k => u * u * u * p0[k] + 3 * u * u * t * p1[k] + 3 * u * t * t * p2[k] + t * t * t * p3[k]);
  }
  function segments(pts, closed) {
    const out = [];
    for (let i = 1; i < pts.length; i++) out.push([i - 1, i]);
    if (closed && pts.length > 2) out.push([pts.length - 1, 0]);
    return out;
  }
  // The box the drawn line fills (curves sampled).
  Pen.bounds = function (pts, closed) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const add = ([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); };
    pts.forEach(p => add([p.x, p.y]));
    for (const [i, j] of segments(pts, closed)) for (let k = 1; k < 24; k++) add(cubic(pts[i], pts[j], k / 24));
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  };
  const mapPt = (p, f) => {
    const o = {};
    [["x", "y"], ["ix", "iy"], ["ox", "oy"]].forEach(([a, b]) => { if (p[a] != null) { const [x, y] = f(p[a], p[b]); o[a] = x; o[b] = y; } });
    return o;
  };
  const rot = (x, y, cx, cy, deg) => {
    if (!deg) return [x, y];
    const r = deg * Math.PI / 180, c = Math.cos(r), s = Math.sin(r), dx = x - cx, dy = y - cy;
    return [cx + dx * c - dy * s, cy + dx * s + dy * c];
  };
  // A path layer's points on the canvas (its size, place, turn and flips).
  Pen.layerPoints = function (l) {
    const sx = l.w / (+l.vw || l.w || 1), sy = l.h / (+l.vh || l.h || 1), cx = l.x + l.w / 2, cy = l.y + l.h / 2;
    return (l.points || []).map(p => mapPt(p, (x, y) => {
      let u = l.x + x * sx, v = l.y + y * sy;
      if (l.flipX) u = 2 * cx - u;
      if (l.flipY) v = 2 * cy - v;
      return rot(u, v, cx, cy, +l.rotation || 0);
    }));
  };
  // Canvas points back into the layer: its box made to fit them (keeping its turn).
  Pen.setLayerPoints = function (l, pts) {
    const deg = +l.rotation || 0, cx = l.x + l.w / 2, cy = l.y + l.h / 2;
    // (in the layer's own unturned, unflipped frame)
    const local = pts.map(p => mapPt(p, (x, y) => {
      let [u, v] = rot(x, y, cx, cy, -deg);
      if (l.flipX) u = 2 * cx - u;
      if (l.flipY) v = 2 * cy - v;
      return [u, v];
    }));
    // (whole pixels: the box is the drawing's, a little bigger)
    const fb = Pen.bounds(local, l.closed), b = { x: Math.floor(fb.x), y: Math.floor(fb.y) };
    const w = Math.max(1, Math.ceil(fb.x + fb.w) - b.x), hh = Math.max(1, Math.ceil(fb.y + fb.h) - b.y);
    // The new box's middle, turned as the layer is.
    const [ncx, ncy] = rot(b.x + w / 2, b.y + hh / 2, cx, cy, deg);
    const r = v => Math.round(v * 100) / 100;
    l.points = local.map(p => mapPt(p, (x, y) => {
      let u = x - b.x, v = y - b.y;
      if (l.flipX) u = w - u;
      if (l.flipY) v = hh - v;
      return [r(u), r(v)];
    }));
    Object.assign(l, { x: r(ncx - w / 2), y: r(ncy - hh / 2), w: r(w), h: r(hh), vw: r(w), vh: r(hh) });
    return l;
  };
  // A new path layer's shape from canvas points.
  Pen.newLayer = function (pts, closed) {
    const l = { x: 0, y: 0, w: 1, h: 1, rotation: 0, closed: !!closed };
    return Pen.setLayerPoints(l, pts);
  };

  // --- drawing on the overlay -----------------------------------------------------------
  function overlay(host) {
    let ov = host.querySelector(":scope > .pen-ov");
    if (!ov) {
      ov = document.createElementNS(NS, "svg");
      ov.setAttribute("class", "pen-ov");
      Object.assign(ov.style, { position: "absolute", inset: "0", width: "100%", height: "100%", pointerEvents: "none", zIndex: 50, overflow: "visible" });
      host.appendChild(ov);
    }
    return ov;
  }
  const svgEl = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  function paint(ov, scr, pts, closed, opts) {
    ov.replaceChildren();
    if (!pts.length) return;
    const s = pts.map(p => mapPt(p, scr));
    const d = window.GFX && GFX.pathD ? GFX.pathD(s, closed) : "";
    ov.appendChild(svgEl("path", { d, fill: closed ? "rgba(46,144,250,.12)" : "none", stroke: "#2e90fa", "stroke-width": 1.5 }));
    if (opts.rubber) ov.appendChild(svgEl("path", { d: opts.rubber, fill: "none", stroke: "#2e90fa", "stroke-width": 1, "stroke-dasharray": "4 3" }));
    s.forEach((p, i) => {
      const showH = opts.handlesFor == null || opts.handlesFor.includes(i);
      if (showH) for (const [a, b] of [["ix", "iy"], ["ox", "oy"]]) {
        if (p[a] == null) continue;
        ov.appendChild(svgEl("line", { x1: p.x, y1: p.y, x2: p[a], y2: p[b], stroke: "#2e90fa", "stroke-width": 1 }));
        ov.appendChild(svgEl("circle", { cx: p[a], cy: p[b], r: 3.5, fill: "#fff", stroke: "#2e90fa", "stroke-width": 1.2 }));
      }
      const on = opts.picked === i, first = i === 0 && opts.hoverFirst;
      ov.appendChild(svgEl("rect", { x: p.x - 4, y: p.y - 4, width: 8, height: 8, fill: on || first ? "#2e90fa" : "#fff", stroke: "#2e90fa", "stroke-width": 1.5 }));
    });
  }

  // --- drawing a new path -----------------------------------------------------------------
  // opts: {canvas, toGfx(clientX, clientY) -> [x, y], toScreen(x, y) -> [x, y], scale() -> n,
  //        done(points, closed), stopped()}
  Pen.draw = function (opts) {
    const ov = overlay(opts.canvas), pts = [];
    let hover = null, dragging = null, closed = false, live = true;
    const scr = (x, y) => opts.toScreen(x, y);
    const tol = () => 8 / opts.scale();
    function render() {
      let rubber = "";
      if (hover && pts.length && !dragging) {
        const a = pts[pts.length - 1], [x0, y0] = scr(a.x, a.y), [x1, y1] = scr(hover[0], hover[1]);
        rubber = a.ox != null ? (() => { const [hx, hy] = scr(a.ox, a.oy); return `M${x0} ${y0} Q${hx} ${hy} ${x1} ${y1}`; })() : `M${x0} ${y0} L${x1} ${y1}`;
      }
      paint(ov, scr, pts, false, { rubber, handlesFor: [pts.length - 1], hoverFirst: hover && pts.length > 2 && near(hover, [pts[0].x, pts[0].y], tol()) });
    }
    const angled = (x, y, from) => {
      if (!from) return [x, y];
      const dx = x - from.x, dy = y - from.y, a = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4), len = Math.hypot(dx, dy);
      return [from.x + Math.cos(a) * len, from.y + Math.sin(a) * len];
    };
    function finish() {
      if (!live) return;
      live = false;
      teardown();
      ov.remove();
      if (pts.length >= 2) opts.done(clone(pts), closed);
      else if (opts.stopped) opts.stopped();
    }
    const down = e => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopImmediatePropagation();
      let [x, y] = opts.toGfx(e.clientX, e.clientY);
      if (pts.length > 2 && near([x, y], [pts[0].x, pts[0].y], tol())) {
        closed = true;
        // (dragging from the first point bends the closing curve)
        dragging = { p: pts[0], start: [pts[0].x, pts[0].y], first: true };
        return;
      }
      if (e.shiftKey) [x, y] = angled(x, y, pts[pts.length - 1]);
      const p = { x, y };
      pts.push(p);
      dragging = { p, start: [x, y] };
      render();
    };
    const move = e => {
      let [x, y] = opts.toGfx(e.clientX, e.clientY);
      if (dragging) {
        const p = dragging.p, [sx, sy] = dragging.start;
        if (!dragging.bent && Math.hypot(x - sx, y - sy) < 3 / opts.scale()) return;
        dragging.bent = true;
        if (e.shiftKey) [x, y] = angled(x, y, p);
        // The handle out follows the mouse; the one in mirrors it (Alt: left where it was).
        p.ox = x; p.oy = y;
        if (!e.altKey || p.ix == null) { p.ix = 2 * p.x - x; p.iy = 2 * p.y - y; }
        hover = null;
        render();
        return;
      }
      hover = e.shiftKey ? angled(x, y, pts[pts.length - 1]) : [x, y];
      render();
    };
    const up = () => {
      if (!dragging) return;
      const wasFirst = dragging.first;
      dragging = null;
      if (wasFirst || closed) return finish();
      render();
    };
    const dbl = e => { e.preventDefault(); e.stopImmediatePropagation(); if (pts.length > 2) pts.pop(); finish(); };
    const key = e => {
      if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement && document.activeElement.tagName)) return;
      if (e.key === "Enter" || e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); finish(); }
      else if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); e.stopImmediatePropagation(); pts.pop(); render(); if (!pts.length) render(); }
      else if (e.key === "Shift") render();
    };
    const leave = () => { hover = null; render(); };
    function teardown() {
      opts.canvas.removeEventListener("mousedown", down, true);
      removeEventListener("mousemove", move, true);
      removeEventListener("mouseup", up, true);
      opts.canvas.removeEventListener("dblclick", dbl, true);
      removeEventListener("keydown", key, true);
      opts.canvas.removeEventListener("mouseleave", leave);
      opts.canvas.classList.remove("pen-on");
    }
    opts.canvas.addEventListener("mousedown", down, true);
    addEventListener("mousemove", move, true);
    addEventListener("mouseup", up, true);
    opts.canvas.addEventListener("dblclick", dbl, true);
    addEventListener("keydown", key, true);
    opts.canvas.addEventListener("mouseleave", leave);
    opts.canvas.classList.add("pen-on");
    render();
    return { stop: finish, get active() { return live; }, redraw: render };
  };

  // --- editing a path's points --------------------------------------------------------------
  // opts: {canvas, toGfx, toScreen, scale, points (canvas), closed,
  //        change(points, final), stopped()}
  Pen.edit = function (opts) {
    const ov = overlay(opts.canvas);
    let pts = clone(opts.points), picked = -1, live = true, drag = null;
    const scr = (x, y) => opts.toScreen(x, y);
    const render = () => paint(ov, scr, pts, opts.closed, { picked, handlesFor: null });
    const tol = () => 7 / opts.scale();
    function onPoint(x, y) {
      // A handle of the picked point (or any) first, then a point.
      for (let i = pts.length - 1; i >= 0; i--) {
        const p = pts[i];
        for (const [a, b] of [["ox", "oy"], ["ix", "iy"]]) if (p[a] != null && near([x, y], [p[a], p[b]], tol())) return { i, handle: a[0] };
      }
      for (let i = pts.length - 1; i >= 0; i--) if (near([x, y], [pts[i].x, pts[i].y], tol())) return { i };
      return null;
    }
    // Where a click on a line is: that segment and t.
    function onLine(x, y) {
      let best = null;
      for (const [i, j] of segments(pts, opts.closed)) for (let k = 1; k < 40; k++) {
        const t = k / 40, q = cubic(pts[i], pts[j], t), d = Math.hypot(q[0] - x, q[1] - y);
        if (d <= tol() && (!best || d < best.d)) best = { i, j, t, d };
      }
      return best;
    }
    // A point added on a line (the curve split so it doesn't change shape).
    function split(i, j, t) {
      const a = pts[i], b = pts[j];
      const P0 = [a.x, a.y], P1 = [a.ox ?? a.x, a.oy ?? a.y], P2 = [b.ix ?? b.x, b.iy ?? b.y], P3 = [b.x, b.y];
      const L = (u, v) => [lerp(u[0], v[0], t), lerp(u[1], v[1], t)];
      const A = L(P0, P1), B = L(P1, P2), C = L(P2, P3), D = L(A, B), E = L(B, C), F = L(D, E);
      const curved = a.ox != null || b.ix != null;
      const n = { x: F[0], y: F[1] };
      if (curved) { a.ox = A[0]; a.oy = A[1]; b.ix = C[0]; b.iy = C[1]; n.ix = D[0]; n.iy = D[1]; n.ox = E[0]; n.oy = E[1]; }
      pts.splice(j === 0 ? pts.length : j, 0, n);
      return j === 0 ? pts.length - 1 : j;
    }
    const send = final => opts.change(clone(pts), final);
    const down = e => {
      if (e.button !== 0) return;
      const [x, y] = opts.toGfx(e.clientX, e.clientY);
      let at = onPoint(x, y);
      if (!at) {
        const ln = onLine(x, y);
        if (!ln) return stop();          // (a click elsewhere: done; the editor takes the click)
        at = { i: split(ln.i, ln.j, ln.t) };
        send(false);
      }
      e.preventDefault(); e.stopImmediatePropagation();
      picked = at.i;
      const p = pts[at.i];
      if (!at.handle && e.altKey) {
        // Corner <-> curve.
        if (p.ix != null || p.ox != null) { delete p.ix; delete p.iy; delete p.ox; delete p.oy; }
        else {
          const prev = pts[(at.i - 1 + pts.length) % pts.length], next = pts[(at.i + 1) % pts.length];
          const dx = (next.x - prev.x) / 6, dy = (next.y - prev.y) / 6;
          Object.assign(p, { ix: p.x - dx, iy: p.y - dy, ox: p.x + dx, oy: p.y + dy });
        }
        render(); send(true);
        return;
      }
      drag = { at, start: [x, y], orig: Object.assign({}, p), alt: e.altKey, moved: false };
      render();
    };
    const move = e => {
      if (!drag) return;
      const [x, y] = opts.toGfx(e.clientX, e.clientY), p = pts[drag.at.i], o = drag.orig;
      const dx = x - drag.start[0], dy = y - drag.start[1];
      if (!drag.moved && Math.hypot(dx, dy) < 2 / opts.scale()) return;
      drag.moved = true;
      if (drag.at.handle) {
        const [a, b] = drag.at.handle === "o" ? ["ox", "oy"] : ["ix", "iy"], [c, d] = drag.at.handle === "o" ? ["ix", "iy"] : ["ox", "oy"];
        p[a] = o[a] + dx; p[b] = o[b] + dy;
        // (the other handle stays opposite, its own length, unless Alt)
        if (!drag.alt && !e.altKey && o[c] != null) {
          const len = Math.hypot(o[c] - o.x, o[d] - o.y), ang = Math.atan2(p[b] - p.y, p[a] - p.x) + Math.PI;
          p[c] = p.x + Math.cos(ang) * len; p[d] = p.y + Math.sin(ang) * len;
        }
      } else {
        for (const [a, b] of [["x", "y"], ["ix", "iy"], ["ox", "oy"]]) if (o[a] != null) { p[a] = o[a] + dx; p[b] = o[b] + dy; }
      }
      render(); send(false);
    };
    const up = () => { if (drag) { const moved = drag.moved; drag = null; if (moved) send(true); } };
    const key = e => {
      if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement && document.activeElement.tagName)) return;
      if (e.key === "Enter" || e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); stop(); }
      else if ((e.key === "Delete" || e.key === "Backspace") && picked >= 0 && pts.length > 2) {
        e.preventDefault(); e.stopImmediatePropagation();
        pts.splice(picked, 1); picked = -1; render(); send(true);
      } else if (e.key.startsWith("Arrow") && picked >= 0) {
        e.preventDefault(); e.stopImmediatePropagation();
        const n = e.shiftKey ? 10 : 1, d = { ArrowLeft: [-n, 0], ArrowRight: [n, 0], ArrowUp: [0, -n], ArrowDown: [0, n] }[e.key];
        const p = pts[picked];
        for (const [a, b] of [["x", "y"], ["ix", "iy"], ["ox", "oy"]]) if (p[a] != null) { p[a] += d[0]; p[b] += d[1]; }
        render(); send(true);
      }
    };
    const dbl = e => { e.preventDefault(); e.stopImmediatePropagation(); };
    function stop() {
      if (!live) return;
      live = false;
      opts.canvas.removeEventListener("mousedown", down, true);
      removeEventListener("mousemove", move, true);
      removeEventListener("mouseup", up, true);
      removeEventListener("keydown", key, true);
      opts.canvas.removeEventListener("dblclick", dbl, true);
      opts.canvas.classList.remove("pen-edit");
      ov.remove();
      if (opts.stopped) opts.stopped();
    }
    opts.canvas.addEventListener("mousedown", down, true);
    addEventListener("mousemove", move, true);
    addEventListener("mouseup", up, true);
    addEventListener("keydown", key, true);
    opts.canvas.addEventListener("dblclick", dbl, true);
    opts.canvas.classList.add("pen-edit");
    render();
    // (the view zoomed or panned: drawn again where the points are now)
    return { stop, redraw: render, get active() { return live; }, setPoints(p) { pts = clone(p); render(); } };
  };
})();
