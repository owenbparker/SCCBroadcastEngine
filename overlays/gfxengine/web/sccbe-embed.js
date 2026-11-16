// SCC Broadcast Engine: the GFX Engine's pages inside the app's window.
// (Opened on its own, the page is unchanged.)
(function () {
  "use strict";
  if (window.top === window) return;
  document.documentElement.classList.add("sccbe");

  // Control: drag the bar under Preview / Program to make them smaller (more
  // room for Graphics and Fields) or bigger. Double-click puts it back.
  const KEY = "sccbe-monitor-height";
  function setup() {
    const page = document.getElementById("page-control");
    if (!page || page.querySelector(".sccbe-split")) return;
    const mons = page.querySelector(".monitors"), bottom = page.querySelector(".control-bottom");
    if (!mons || !bottom) return;
    const split = document.createElement("div");
    split.className = "sccbe-split";
    split.title = "Drag to make Preview and Program smaller or bigger (double-click: back to normal)";
    split.innerHTML = "<span></span>";
    page.insertBefore(split, bottom);
    let height = 0;
    try { height = +localStorage.getItem(KEY) || 0; } catch (e) { /* private window */ }

    // Preview, the take bar and Program are three columns across the full
    // width; Graphics sits under Preview + the take bar and Fields under
    // Program, and they always keep the full width. Dragging only changes the
    // monitors' size (always 16:9): they stay against the take bar, so the
    // middle edges keep lining up with the panels below, and the panels just
    // get taller or shorter.
    const TAKE = 150, MIN = 140;
    function apply() {
      const boxes = mons.querySelectorAll(".mon-box");
      const takebar = mons.querySelector(".takebar");
      const head = mons.querySelector(".mon-head");
      const cs = getComputedStyle(page);
      const inner = page.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      const gap = parseFloat(getComputedStyle(mons).columnGap) || 10;
      const gapB = parseFloat(getComputedStyle(bottom).columnGap) || gap;
      const headH = head ? head.offsetHeight : 30;
      if (inner <= 0) return;
      // widest each monitor can be, and the tallest the page leaves room for
      const full = Math.max(160, (inner - TAKE - 2 * gap) / 2);
      const most = Math.max(110, page.clientHeight - 260 - headH);
      const want = height || full * 9 / 16;
      const h0 = Math.max(MIN, Math.min(want, most));
      const w = Math.min(full, h0 * 16 / 9), h = w * 9 / 16;
      mons.style.gridTemplateColumns = `${full}px ${TAKE}px ${full}px`;
      mons.style.justifyContent = "";
      bottom.style.gridTemplateColumns = `${full + gap + TAKE + (gap - gapB)}px ${full}px`;
      bottom.style.justifyContent = "";
      for (const m of mons.querySelectorAll(".monitor")) {
        m.style.width = `${w}px`;
        m.style.justifySelf = m.classList.contains("pvw") ? "end" : "start";
      }
      for (const b of boxes) b.style.cssText = `width:100%;height:${h}px;max-height:none;aspect-ratio:auto;flex:none`;
      // the take bar is no taller than the monitors: its transitions list scrolls
      const small = h < 300;
      mons.classList.toggle("sccbe-small", small);
      mons.classList.toggle("sccbe-tiny", h < 220);
      if (takebar) takebar.style.maxHeight = `${headH + h}px`;
    }
    let startY = 0, startH = 0;
    split.addEventListener("pointerdown", e => {
      const box = mons.querySelector(".mon-box");
      if (!box) return;
      startY = e.clientY;
      startH = box.getBoundingClientRect().height || mons.getBoundingClientRect().height - 60;
      split.setPointerCapture(e.pointerId);
      split.classList.add("drag");
      e.preventDefault();
    });
    split.addEventListener("pointermove", e => {
      if (!split.classList.contains("drag")) return;
      height = Math.max(MIN, startH + e.clientY - startY);
      apply();
    });
    const end = () => {
      if (!split.classList.contains("drag")) return;
      split.classList.remove("drag");
      try { localStorage.setItem(KEY, String(Math.round(height))); } catch (e) { /* private window */ }
    };
    split.addEventListener("pointerup", end);
    split.addEventListener("pointercancel", end);
    split.addEventListener("dblclick", () => {
      height = 0;
      try { localStorage.removeItem(KEY); } catch (e) { /* private window */ }
      apply();
    });
    new ResizeObserver(apply).observe(page);
    apply();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup);
  else setup();
})();
