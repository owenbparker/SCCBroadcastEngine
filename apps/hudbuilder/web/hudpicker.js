/* The HUD design list in a game HUD's control panel, with every HUD from
 * HUD Builder in it: the copies of its designs (Game HUDs > Duplicate) and
 * My HUDs for the game. Served by each game HUD app as /hudedit/picker.js.
 *
 *   const picker = HudPicker.attach(selectEl, {game: "valorant", base: v => design key of built-in option v});
 *   select.onchange: const v = await picker.pick(select.value)  -> the built-in design to use (null: a My HUD took /overlay)
 *   when the app sets the list:  select.value = picker.shown(builtInValue)
 *   after the app rebuilds the options:  picker.decorate()
 *
 * Picking a copy makes it live for its design (hudedit.py set_live) and picks
 * that design; picking a My HUD sends /overlay to it; picking a built-in design
 * goes back to the original.
 */
(function () {
  "use strict";
  if (window.HudPicker) return;

  function attach(sel, opts) {
    var live = null, lastBuiltin = null, timer = null;
    var base = opts.base || function () { return null; };

    function builtins() {
      return Array.prototype.filter.call(sel.options, function (o) { return !o.dataset.hudpick; });
    }
    function builtinFor(key) {
      var o = builtins().filter(function (x) { return base(x.value) === key; })[0];
      return o || null;
    }
    function decorate() {
      Array.prototype.slice.call(sel.querySelectorAll("optgroup[data-hudpick]")).forEach(function (g) { g.remove(); });
      if (!live) return;
      var copies = (live.copies || []).filter(function (c) { return builtinFor(c.base); });
      if (copies.length) {
        var g = document.createElement("optgroup");
        g.label = "Copies (HUD Builder)";
        g.dataset.hudpick = "1";
        copies.forEach(function (c) {
          var o = document.createElement("option");
          o.value = "copy:" + c.id;
          o.dataset.hudpick = "1";
          o.textContent = c.name + " (copy of " + builtinFor(c.base).textContent + ")";
          g.appendChild(o);
        });
        sel.appendChild(g);
      }
      var customs = live.customs || [];
      if (customs.length) {
        var g2 = document.createElement("optgroup");
        g2.label = "My HUDs (HUD Builder)";
        g2.dataset.hudpick = "1";
        customs.forEach(function (c) {
          var o = document.createElement("option");
          o.value = "custom:" + c.src + ":" + c.id;
          o.dataset.hudpick = "1";
          o.textContent = c.name + (c.src === "embed" ? " (Custom design)" : "");
          g2.appendChild(o);
        });
        sel.appendChild(g2);
      }
      if (lastBuiltin != null && document.activeElement !== sel) sel.value = shown(lastBuiltin);
    }
    function shown(builtin) {
      lastBuiltin = builtin;
      if (!live) return builtin;
      var cu = live.custom;
      if (cu && (live.customs || []).some(function (c) { return c.src === cu.src && c.id === cu.id; })) return "custom:" + cu.src + ":" + cu.id;
      var cid = (live.active || {})[base(builtin)];
      if (cid && (live.copies || []).some(function (c) { return c.id === cid; })) return "copy:" + cid;
      return builtin;
    }
    function post(body) {
      return fetch("/hudedit/copies", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({ action: "live" }, body)) })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (d.error) throw new Error(d.error); return d; });
    }
    function pick(value) {
      var m;
      var done = function () { return refresh(); };
      if ((m = /^copy:([a-f0-9]{8})$/.exec(value))) {
        var c = (live.copies || []).filter(function (x) { return x.id === m[1]; })[0];
        var o = c && builtinFor(c.base);
        if (!o) return Promise.resolve(null);
        return post({ base: c.base, id: c.id }).then(done).then(function () { return o.value; });
      }
      if ((m = /^custom:(builder|embed):([a-z0-9]+)$/.exec(value))) {
        var cu = (live.customs || []).filter(function (x) { return x.src === m[1] && x.id === m[2]; })[0];
        if (!cu) return Promise.resolve(null);
        return post({ custom: cu }).then(done).then(function () { return null; });
      }
      var key = base(value);
      var p = key ? post({ base: key, id: "" }) : post({ custom: null });
      return p.then(done, function () { /* an older HUD: just the design */ }).then(function () { return value; });
    }
    function refresh() {
      return fetch("/hudedit/live?game=" + encodeURIComponent(opts.game || ""), { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.error) return;
          var was = JSON.stringify(live);
          live = d;
          if (JSON.stringify(live) !== was) decorate();
        })
        .catch(function () { /* restarting */ });
    }
    refresh();
    timer = setInterval(refresh, 5000);
    sel.addEventListener("focus", refresh);
    return { pick: pick, shown: shown, decorate: decorate, refresh: refresh, stop: function () { clearInterval(timer); } };
  }

  window.HudPicker = { attach: attach };
})();
