// The control panel's Appearance: four Apple-inspired looks and a highlight
// colour. Shared verbatim by GFX Engine, every SCC HUD and the HUD Manager.
// Load it in <head> (after appearance.css) so the look is on before the page
// draws; the choice is saved by the app (GET/POST /api/appearance).
(function () {
  "use strict";
  const LOOKS = [
    { id: "studio", name: "Studio Black", note: "Pure black, big titles, gold on key buttons. Calmest in a dark room.", accent: "#f5c518" },
    { id: "graphite", name: "Graphite", note: "Mac pro-app greys and blue, with glowing Preview and Program.", accent: "#0a84ff" },
    { id: "daylight", name: "Daylight", note: "Light, with white cards. Best in a bright room.", accent: "#0071e3" },
    { id: "glass", name: "Liquid Glass", note: "Frosted glass over Saints green and gold.", accent: "#f5c518" },
  ];
  const SWATCHES = ["#f5c518", "#0a84ff", "#30d158", "#ff9f0a", "#ff375f", "#bf5af2", "#64d2ff", "#ffffff"];
  const root = document.documentElement;
  const KEY = "scc-appearance";
  let state = { look: "studio", accent: "" };
  const boxes = new Set();

  // Dark or light text on a highlight colour, whichever reads better.
  function onColor(hex) {
    const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    const L = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    return (L + 0.05) / 0.05 > 1.05 / (L + 0.05) ? "#111111" : "#ffffff";
  }
  function apply(a) {
    state = { look: LOOKS.some(l => l.id === a.look) ? a.look : "studio", accent: /^#[0-9a-f]{6}$/i.test(a.accent || "") ? a.accent.toLowerCase() : "" };
    root.dataset.look = state.look;
    if (state.accent) {
      root.style.setProperty("--x-accent", state.accent);
      root.style.setProperty("--x-on-accent", onColor(state.accent));
    } else {
      root.style.removeProperty("--x-accent");
      root.style.removeProperty("--x-on-accent");
    }
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* no storage */ }
    boxes.forEach(draw);
  }
  function save(change) {
    apply(Object.assign({}, state, change));
    fetch("/api/appearance", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(change) })
      .then(r => r.json()).then(a => { if (a && !a.error) apply(a); }).catch(() => {});
  }

  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  function draw(box) {
    const look = LOOKS.find(l => l.id === state.look);
    const accent = state.accent || look.accent;
    box.innerHTML = `<div class="ap">
      <div><h4>Look</h4><div class="ap-looks" role="radiogroup" aria-label="Look">${LOOKS.map(l => `
        <button type="button" class="ap-look" role="radio" aria-checked="${l.id === state.look}" data-look="${l.id}">
          <span class="ap-mini" data-mini="${l.id}"><span></span><em></em><u></u></span>
          <b>${esc(l.name)}${l.id === "studio" ? " <i>Default</i>" : ""}</b><small>${esc(l.note)}</small></button>`).join("")}</div></div>
      <div><h4><label for="ap-accent-${boxes.size}">Highlight colour</label></h4>
        <div class="ap-accent-row">
          <input type="color" id="ap-accent-${boxes.size}" value="${accent}" aria-label="Highlight colour">
          <div class="ap-swatches">${SWATCHES.map(c => `<button type="button" class="ap-swatch" style="--sw:${c}" data-c="${c}" aria-label="${c}" aria-pressed="${c === accent}"></button>`).join("")}</div>
          <button type="button" class="small ap-reset"${state.accent ? "" : " disabled"}>Use ${esc(look.name)}'s colour</button>
        </div>
        <p class="ap-note" style="margin-top:8px">Used for key buttons, selected items and icons. Preview, Program and the team colours don't change.</p></div>
      <p class="ap-note">Saved on this PC for this app.</p></div>`;
    box.querySelectorAll(".ap-look").forEach(b => b.addEventListener("click", () => save({ look: b.dataset.look })));
    box.querySelectorAll(".ap-swatch").forEach(b => b.addEventListener("click", () => save({ accent: b.dataset.c })));
    const input = box.querySelector("input[type=color]");
    input.addEventListener("change", () => save({ accent: input.value }));
    box.querySelector(".ap-reset").addEventListener("click", () => save({ accent: "" }));
  }

  // The last choice first (no flash), then what the app has saved.
  try { const cached = JSON.parse(localStorage.getItem(KEY) || "null"); if (cached) apply(cached); } catch (e) { /* none */ }
  if (!root.dataset.look) root.dataset.look = "studio";
  fetch("/api/appearance", { cache: "no-store" }).then(r => r.json()).then(a => { if (a && !a.error) apply(a); }).catch(() => {});

  window.Appearance = {
    looks: LOOKS,
    render(box) { if (box && !boxes.has(box)) { boxes.add(box); draw(box); } },
  };
})();
