// The setup guide: after a design comes in (or from Game data > Setup guide), it
// goes through the game's data one piece at a time - "Which layer shows the left
// team's kills?" - and the layer clicked (on the canvas or in the Layers list) is
// linked to it. Skip what the design doesn't have; Back to redo one.
"use strict";

window.Guide = (function () {
  const GAMES = [["lol", "League of Legends"], ["valorant", "VALORANT"], ["cod", "Call of Duty"], ["rl", "Rocket League"],
    ["smash", "Smash Ultimate"], ["overwatch", "Overwatch 2"]];
  let box = null, steps = [], at = 0, done = {}, hudId = null;

  const words = s => String(s || "").toUpperCase().replace(/['’]S\b/g, "").replace(/[_\-./!{}]+/g, " ")
    .replace(/\bPLAYER\s*(\d+)\b/g, "P$1").replace(/\bTRI ?CODE\b|\bTAG\b|\bABBR\b/g, "SHORT").replace(/\b(BO\d|PIP|SERIES)\b/g, " ")
    .replace(/\bWIN\b/g, "WON").replace(/\bCOLOR\b/g, "COLOUR").replace(/\b(BLUE|HOME|T1|TEAM 1)\b/g, "LEFT").replace(/\b(RED|ORANGE|AWAY|T2|TEAM 2)\b/g, "RIGHT")
    .replace(/\b(THE|TEAM|A|OF|SHAPE|FILLED|WITH|IT|LAYER|TEXT|COPY)\b/g, " ").split(/\s+/).filter(Boolean);
  // The layer whose name looks most like this piece of data (or null).
  function suggest(f) {
    const hud = Editor.hud;
    if (!hud) return null;
    const want = [new Set(words(f.field)), new Set(words(f.label.replace(/\(.*\)/, "")))];
    let best = null, bestScore = 0;
    for (const l of hud.layers) {
      if (l.reference) continue;
      const have = new Set(words(l.name));
      if (!have.size) continue;
      const side = ["LEFT", "RIGHT"].find(s => want[0].has(s) || want[1].has(s));
      if (side && have.has(side === "LEFT" ? "RIGHT" : "LEFT")) continue;
      // ("TEAM LEFT": the team's panel, in its colour; "player 1": that player's name)
      const only = [...have].join(" ");
      if (f.kind === "color" && side && (only === side || only === side + " PANEL" || only === "PANEL " + side) && bestScore < 0.8) { bestScore = 0.8; best = l; }
      if (/NAME$/i.test(f.field) && want[0].has("NAME")) {
        const rest = [...want[0]].filter(x => x !== "NAME");
        if (rest.length && have.size === rest.length && rest.every(x => have.has(x)) && bestScore < 0.8) { bestScore = 0.8; best = l; }
      }
      for (const w of want) {
        if (!w.size) continue;
        const hits = [...w].filter(x => have.has(x)).length;
        const extra = [...have].filter(x => !w.has(x)).length;
        const score = hits / w.size - extra * 0.05;
        if (score > bestScore) { bestScore = score; best = l; }
      }
    }
    return bestScore >= 0.75 ? best : null;
  }

  function build() {
    steps = [];
    if ((Editor.hud.game || "other") === "other") steps.push({ game: true, section: "Game" });
    for (const g of Editor.catalog) for (const f of g.fields) if (f.guide) steps.push({ f, section: g.group });
  }
  const key = () => `hb-guide-${hudId}`;
  const save = () => { try { localStorage.setItem(key(), String(at)); } catch (e) { /* (private window) */ } };

  async function start(opts) {
    const hud = Editor.hud;
    if (!hud) return;
    hudId = hud.id;
    done = {};
    build();
    at = 0;
    if (!(opts && opts.fresh)) {
      try { at = Math.min(+localStorage.getItem(key()) || 0, steps.length); } catch (e) { at = 0; }
      if (at >= steps.length) at = 0;
    }
    if (!box) {
      box = h("div", { class: "guide", onmousedown: e => e.stopPropagation(), ondragover: e => e.stopPropagation() });
      $("#ed-canvas").appendChild(box);
    }
    box.hidden = false;
    show();
  }
  function close() {
    Editor.setPicker(null);
    if (box) box.hidden = true;
  }
  function go(n) { at = Math.max(0, Math.min(n, steps.length)); save(); show(); }
  const isPlayers = s => /player|crew/i.test(s || "");
  function skipSection(all) {
    const s = steps[at] && steps[at].section;
    let n = at;
    while (n < steps.length && (all ? isPlayers(steps[n].section) : steps[n].section === s)) n++;
    go(n);
  }

  const fill = (...kids) => box.replaceChildren(...kids.flat().filter(Boolean));
  function show() {
    if (!Editor.hud || Editor.hud.id !== hudId) return close();
    const total = steps.length;
    const bar = h("div", { class: "g-bar" }, h("i", { style: { width: `${total ? Math.round(at / total * 100) : 100}%` } }));
    if (at >= total) {
      Editor.setPicker(null);
      const linked = steps.filter(s => s.f && Editor.linkedTo(s.f.token).length).length;
      const asked = steps.filter(s => s.f).length;
      fill(h("div", { class: "g-top" }, h("span", {}, "Setup guide"), h("span", { class: "grow" }), h("span", {}, "Done")), bar,
        h("h4", {}, "That's everything"),
        h("p", {}, `${linked} of ${asked} pieces of game data are on the design. The rest are in Game data on the left: drag one onto a layer any time.`),
        h("p", { class: "muted small" }, "With the GFX Engine running and the game's HUD connected to it, the linked layers fill in live."),
        h("div", { class: "g-btns" }, h("button", { class: "primary", onclick: close }, "Close"), h("button", { onclick: () => go(0) }, "Start over")));
      return;
    }
    const step = steps[at];
    const top = h("div", { class: "g-top" }, h("span", {}, `Setup guide · ${step.section}`), h("span", { class: "grow" }),
      h("span", {}, `${at + 1} of ${total}`), h("button", { class: "small ghost", title: "Close (carry on later from Game data > Setup guide)", onclick: close }, "✕"));
    if (step.game) {
      Editor.setPicker(null);
      fill(top, bar, h("h4", {}, "Which game is this HUD for?"),
        h("p", { class: "muted" }, "Its game decides the data there is to link: kills, gold, round score..."),
        h("div", { class: "g-games" }, GAMES.map(([k, t]) => h("button", { onclick: async () => { await Editor.setGame(k); build(); at = 0; save(); show(); } }, t))),
        h("div", { class: "g-btns" }, h("button", { onclick: () => go(at + 1) }, "Another game (just the teams)")));
      return;
    }
    const f = step.f;
    const linked = Editor.linkedTo(f.token);
    const guess = linked.length ? null : suggest(f);
    const q = f.kind === "toggle" ? `Which layer should show only for the ${f.label.replace(/ \(.*\)$/, "")}?`
      : f.kind === "color" ? `Which layer takes the ${f.label.replace(/ \(.*\)$/, "")}?`
      : `Which layer is the ${f.label}?`;
    const how = { image: "It becomes that picture (a placeholder logo or icon works well).",
      color: "Pick the shape (or text) that should be in that colour.",
      toggle: "Pick the layer that should only be there while it's on.",
      text: "Pick the text that shows it. A picture of the text becomes live text in its place.",
      number: "Pick the text that shows it. A picture of the text becomes live text in its place." }[f.kind] || "";
    const pick = l => {
      const before = JSON.stringify(l);
      if (Editor.linkData(l, f, true)) {
        done[at] = { layer: l.id, before, name: l.name };
        toast(`${l.name}: ${Editor.short(f)}`);
        go(at + 1);
      }
    };
    Editor.setPicker(pick);
    const prev = done[at];
    fill(top, bar, h("h4", {}, q),
      h("p", { class: "muted" }, "Click it on the canvas or in the Layers list. " + how),
      linked.length ? h("p", { class: "g-done" }, `✓ Already linked: ${linked.map(l => l.name).join(", ")}`) : null,
      guess ? h("div", { class: "g-suggest" }, h("span", {}, "Looks like"), h("b", {}, guess.name),
        h("button", { class: "small", onmouseenter: () => Editor.focusLayer(guess.id), onclick: () => pick(guess) }, "Use it")) : null,
      h("div", { class: "g-btns" },
        h("button", { disabled: at === 0, onclick: () => go(at - 1) }, "Back"),
        h("button", { onclick: () => go(at + 1) }, linked.length ? "Next" : "Skip (not in my design)"),
        h("button", { class: "ghost", onclick: () => skipSection(false) }, `Skip ${step.section}`),
        isPlayers(step.section) ? h("button", { class: "ghost", onclick: () => skipSection(true) }, "Skip all players") : null,
        prev ? h("button", { class: "ghost", title: `Put ${prev.name} back as it was`, onclick: () => { Editor.unlink(prev.before); delete done[at]; show(); } }, "Undo link") : null));
  }

  return { start, close, refresh: () => box && !box.hidden && show() };
})();
