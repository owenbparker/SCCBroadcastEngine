// The Tournament page's Past results: the matches the Recent results graphic
// lists (Global "results", kept with the open tournament). Typed in, added
// from the match on Global, or imported from a spreadsheet.
"use strict";

(function pastResults() {
  let rs = null;            // as edited here
  let pending = false;
  let last = "";
  const pic = p => !p ? "" : /^https?:/.test(p) ? p : "/" + encodeURI(p);
  const logoOf = name => { const t = (App.state.teams || []).find(x => x.name.toLowerCase() === String(name || "").trim().toLowerCase()); return t && t.logo; };
  const save = debounce(() => { pending = false; api("/api/global", { global: { results: rs } }); }, 400);
  const changed = () => { pending = true; save(); };
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const newId = () => Math.random().toString(16).slice(2, 10);
  const box = $("#rs-rows");

  function won(r) {
    const a = parseFloat(r.score1), b = parseFloat(r.score2);
    return isNaN(a) || isNaN(b) || a === b ? "" : a > b ? " won-1" : " won-2";
  }
  function row(r) {
    const el = h("div", { class: "rs-row" + won(r) });
    const input = (k, attrs) => h("input", Object.assign({ value: r[k] || "", oninput: e => {
      r[k] = e.target.value; changed();
      if (k.startsWith("score")) el.className = "rs-row" + won(r);
      if (k.startsWith("team")) { const lg = el.querySelector(`[data-logo="${k}"]`); const l = logoOf(r[k]); lg.style.backgroundImage = l ? `url("${pic(l)}")` : ""; }
    } }, attrs || {}));
    const team = k => { const l = logoOf(r[k]);
      return h("div", { class: "rs-team" }, h("span", { class: "rs-logo", "data-logo": k, style: { backgroundImage: l ? `url("${pic(l)}")` : "" } }),
        input(k, { list: "team-names", placeholder: k === "team1" ? "Team 1" : "Team 2" })); };
    el.append(input("date", { type: "date" }), input("label", { placeholder: "e.g. Week 1 - Game 1" }), team("team1"),
      input("score1", { class: "rs-score", "data-n": "1", inputmode: "numeric", placeholder: "–" }),
      input("score2", { class: "rs-score", "data-n": "2", inputmode: "numeric", placeholder: "–" }), team("team2"),
      h("button", { class: "ghost small", title: "Remove this result", onclick: () => { rs.splice(rs.indexOf(r), 1); changed(); render(); } }, "✕"));
    return el;
  }
  function render() {
    const heads = h("div", { class: "rs-heads" }, ...["Date", "Label", "Team 1", "Score", "Score", "Team 2", ""].map(t => h("span", {}, t)));
    box.replaceChildren(...(rs.length ? [heads, ...rs.map(row)]
      : [h("div", { class: "rs-empty muted small" }, "No past results yet: + Add result, + This match, or Import a spreadsheet.")]));
    $("#rs-count").textContent = rs.length ? `${rs.length} match${rs.length === 1 ? "" : "es"}` : "";
  }
  // Newest first (by date) when it's loaded; new ones go at the top.
  const byDate = list => list.map((r, i) => [r, i]).sort((a, b) => (b[0].date || "").localeCompare(a[0].date || "") || b[1] - a[1]).map(x => x[0]);
  function load() {
    rs = byDate(JSON.parse(JSON.stringify(App.state.global.results || [])));
    render();
  }
  function addFirst(r) {
    rs.unshift(Object.assign({ id: newId(), label: "", date: today(), team1: "", score1: "", team2: "", score2: "" }, r));
    changed();
    render();
    const first = box.querySelector(".rs-row input:nth-child(2)");
    if (first) first.focus();
  }
  $("#rs-add").addEventListener("click", () => addFirst({}));
  $("#rs-current").addEventListener("click", () => {
    const g = App.state.global;
    if (!g.left.name || !g.right.name) { toast("Set both teams on Global first", true); return; }
    addFirst({ label: g.stage || "", team1: g.left.name, score1: String(g.left.score), team2: g.right.name, score2: String(g.right.score) });
    toast(`Added ${g.left.name} ${g.left.score}-${g.right.score} ${g.right.name}`);
  });
  const file = h("input", { type: "file", hidden: true, accept: ".csv,.tsv,.txt,.xlsx,.xlsm,.json",
    onchange: async e => {
      const f = e.target.files[0]; e.target.value = "";
      if (!f) return;
      const replace = rs.length && confirm(`Replace the ${rs.length} result${rs.length === 1 ? "" : "s"} here with the file's?\n\nOK replaces them; Cancel adds the file's to them (a match already here is updated).`);
      try {
        if (pending) { pending = false; await api("/api/global", { global: { results: rs } }); }
        const r = await postFile(`/api/results/import?mode=${replace ? "replace" : "add"}`, f);
        App.state.global = r.global;
        load();
        toast(`Imported ${r.added} result${r.added === 1 ? "" : "s"}`);
      } catch (err) { /* (postFile said why) */ }
    } });
  $("#rs-import").after(file);
  $("#rs-import").addEventListener("click", () => file.click());

  App.on(s => {
    const sig = JSON.stringify(s.global.results || []);
    if (App.tab === "tournament" && sig !== last) {
      last = sig;
      if (!rs || (!pending && !box.contains(document.activeElement))) load();
    }
  });
  const shown = pages.tournament && pages.tournament.shown;
  pages.tournament = { shown() { if (shown) shown(); if (App.state) { last = JSON.stringify(App.state.global.results || []); load(); } } };
})();
