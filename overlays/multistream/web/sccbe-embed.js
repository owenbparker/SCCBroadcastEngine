// SCC Broadcast Engine: a part's page inside the app's window.
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

    function apply() {
      const boxes = mons.querySelectorAll(".mon-box");
      for (const b of boxes) {
        if (!height) { b.style.cssText = ""; continue; }
        const most = Math.max(110, page.clientHeight - 260);
        const h = Math.max(90, Math.min(height, most));
        const w = Math.min(b.parentElement.clientWidth, h * 16 / 9);
        b.style.cssText = `width:${w}px;height:${w * 9 / 16}px;max-height:none;aspect-ratio:auto;align-self:center;flex:none`;
      }
      // (the take bar sits beside them: let it shrink too)
      mons.classList.toggle("sccbe-small", !!height && height < 260);
    }
    let startY = 0, startH = 0;
    split.addEventListener("pointerdown", e => {
      const box = mons.querySelector(".mon-box");
      if (!box) return;
      startY = e.clientY;
      startH = box.getBoundingClientRect().height;
      split.setPointerCapture(e.pointerId);
      split.classList.add("drag");
      e.preventDefault();
    });
    split.addEventListener("pointermove", e => {
      if (!split.classList.contains("drag")) return;
      height = Math.max(90, startH + e.clientY - startY);
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
