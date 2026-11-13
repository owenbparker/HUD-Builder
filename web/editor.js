// The HUD editor: the layers and variables on the left, the 1920x1080 canvas
// in the middle (drag to move, handles to resize, drop pictures and variables
// in), and the selected layer's properties on the right. Changes save as
// they're made. Layers are GFX Engine Composer layers, drawn by the same
// player (runtime.js), so a HUD made here plays the same everywhere.
"use strict";

window.Editor = (function () {
  let gd = { game: null, catalog: [], samples: {}, source: "" };   // the game's data (/api/gamedata)
  let engine = { connected: false, feeds: [] };
  let picker = null;           // the setup guide's "click the layer that…"
  let hud = null;              // {id, name, game, layers, vars}: our copy of the design
  let live = { tables: {}, assets: [] };
  let root = null;             // the HUD on the canvas
  const selected = new Set();  // selected layer ids
  let undo = [], redo = [];
  let scale = 0.5, offX = 0, offY = 0;
  let saveTimer = null, saving = false, dirty = false;
  let clip = null;             // copied layers
  let games = {};

  const canvas = $("#ed-canvas"), stage = $("#ed-stage"), selLayer = $("#ed-sel");
  const W = () => GFX.W, H = () => GFX.H;
  const uid = p => p + Math.random().toString(36).slice(2, 12);
  const layerById = id => hud && hud.layers.find(l => l.id === id);
  const sel = () => hud ? hud.layers.filter(l => selected.has(l.id)) : [];
  const vars = () => (hud && hud.vars) || [];
  const typing = () => { const a = document.activeElement; return a && (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable); };

  // --- opening, saving and undo ---------------------------------------------------
  function open(payload, gameList) {
    games = gameList || games;
    const same = hud && hud.id === payload.id;
    hud = { id: payload.id, name: payload.name, game: payload.game || "other",
      layers: JSON.parse(JSON.stringify(payload.layers || [])), vars: JSON.parse(JSON.stringify(payload.vars || [])) };
    if (!same) { selected.clear(); undo = []; redo = []; }
    takeLive(payload);
    GFX.base = "/huds/" + hud.id;
    $("#ed-name").value = hud.name;
    $("#ed-game").replaceChildren(...Object.entries(games).map(([k, t]) => h("option", { value: k, selected: k === hud.game }, t)));
    markSaved(true);
    draw();
    renderAll();
    requestAnimationFrame(fitStage);
    loadGameData();
  }
  function takeLive(payload) {
    live = { tables: payload.tables || {}, assets: payload.assets || [], values: payload.values || {} };
    if (payload.engine) engine = payload.engine;
    loadFonts();
    GFX.setData(dataTables());
  }
  // What the editor shows: the live data, and example values for what isn't live
  // (so a design reads "12" and "BLU" rather than empty while no game is on).
  const dataTables = () => Object.assign({}, gd.samples, live.tables);
  // Just the data changed (the game moved on).
  let dataTimer = null;
  function liveData(payload) {
    if (!hud || payload.id !== hud.id) return;
    live.tables = payload.tables || {};
    const was = JSON.stringify(engine);
    if (payload.engine) engine = payload.engine;
    if (JSON.stringify(engine) !== was) renderVars();
    if (dataTimer) return;
    dataTimer = setTimeout(() => { dataTimer = null; GFX.setData(dataTables()); redraw(); }, 100);
  }
  async function loadGameData() {
    if (!hud) return;
    const game = hud.game || "other";
    if (gd.game === game) return;
    try {
      const r = await api(`/api/gamedata/${game}`);
      if (!hud || (hud.game || "other") !== game) return;
      gd = Object.assign({ game }, r);
      GFX.setData(dataTables());
      redraw();
      renderVars();
    } catch (e) { toast(e.message, true); }
  }
  const allData = () => gd.catalog.flatMap(g => g.fields.map(f => Object.assign({ group: g.group }, f)));
  const dataOf = kinds => gd.catalog.map(g => [g, g.fields.filter(f => !kinds || kinds.includes(f.kind))]).filter(([, fs]) => fs.length);
  // From the app's live feed: the values (and pictures) as the control panel sets them.
  function liveUpdate(payload) {
    if (!hud || payload.id !== hud.id) return;
    const assetsChanged = JSON.stringify(payload.assets) !== JSON.stringify(live.assets);
    takeLive(payload);
    if (assetsChanged) renderProps();
    renderVars();
  }
  function loadFonts() {
    const list = live.assets.filter(a => /\.(ttf|otf|woff2?)$/i.test(a)).map(p => {
      const name = p.replace(/^assets\//, "").replace(/\.[^.]+$/, "");
      return { path: p, postscript: name, aliases: [name] };
    });
    GFX.loadFonts(list);
  }
  const design = () => JSON.stringify({ name: hud.name, game: hud.game, layers: hud.layers, vars: hud.vars });
  function snapshot() {
    if (!hud) return;
    undo.push(design());
    if (undo.length > 200) undo.shift();
    redo = [];
  }
  function restore(json) {
    const d = JSON.parse(json);
    Object.assign(hud, d);
    for (const id of [...selected]) if (!layerById(id)) selected.delete(id);
    $("#ed-name").value = hud.name;
    $("#ed-game").value = hud.game;
    changed();
  }
  function doUndo() { if (!undo.length) return; redo.push(design()); restore(undo.pop()); }
  function doRedo() { if (!redo.length) return; undo.push(design()); restore(redo.pop()); }

  // Something changed: drawn at once, saved shortly after.
  function changed(opts) {
    opts = opts || {};
    redraw();
    if (!opts.keepProps) renderProps();
    renderLayers();
    if (opts.vars) renderVars();
    dirty = true;
    markSaved(false);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 500);
  }
  async function save() {
    if (!hud || !dirty) return;
    if (saving) { saveTimer = setTimeout(save, 300); return; }
    saving = true; dirty = false;
    const id = hud.id;
    try {
      await api(`/api/huds/${id}/save`, JSON.parse(design()));
      if (hud && hud.id === id && !dirty) markSaved(true);
      window.App && App.renamed && App.renamed(id, hud.name);
      window.App && App.refresh && App.refresh();
    } catch (e) {
      dirty = true;
      toast("Couldn't save: " + e.message, true);
      markSaved(false, true);
    } finally { saving = false; }
  }
  function markSaved(ok, error) {
    const s = $("#ed-saved");
    s.textContent = error ? "Not saved" : ok ? "Saved" : "Saving…";
    s.classList.toggle("error", !!error);
  }
  const flush = () => { clearTimeout(saveTimer); return save(); };

  // --- the canvas -----------------------------------------------------------------
  function fitStage() {
    const r = canvas.getBoundingClientRect();
    if (!r.width) return;
    const pad = 28;
    scale = Math.max(0.05, Math.min((r.width - pad * 2) / W(), (r.height - pad * 2) / H()));
    offX = (r.width - W() * scale) / 2;
    offY = (r.height - H() * scale) / 2;
    stage.style.transform = `translate(${offX}px, ${offY}px) scale(${scale})`;
    stage.style.width = W() + "px"; stage.style.height = H() + "px";
    drawSelection();
  }
  new ResizeObserver(fitStage).observe(canvas);
  function setBg(v) { canvas.dataset.bg = v; try { localStorage.setItem("hb-canvas-bg", v); } catch (e) { /* */ } }
  try { const bg = localStorage.getItem("hb-canvas-bg"); if (bg) $("#ed-bg").value = bg; } catch (e) { /* */ }
  setBg($("#ed-bg").value);
  $("#ed-bg").addEventListener("change", e => setBg(e.target.value));

  const comp = () => ({ id: hud.id, layers: hud.layers });
  function draw() {
    if (root) { GFX.destroy(root); root.remove(); root = null; }
    if (!hud) return;
    root = GFX.buildComp(comp(), {}, { showHidden: true, muted: true });
    stage.appendChild(root);
    drawSelection();
  }
  function redraw() {
    if (!hud) return;
    if (!root) return draw();
    GFX.updateComp(root, comp(), {});
    $("#ed-empty").hidden = hud.layers.length > 0;
    drawSelection();
  }
  const toCanvas = (cx, cy) => { const r = canvas.getBoundingClientRect(); return [(cx - r.left - offX) / scale, (cy - r.top - offY) / scale]; };
  const toScreen = (x, y) => [offX + x * scale, offY + y * scale];
  function bounds(list) {
    const x0 = Math.min(...list.map(l => l.x)), y0 = Math.min(...list.map(l => l.y));
    const x1 = Math.max(...list.map(l => l.x + l.w)), y1 = Math.max(...list.map(l => l.y + l.h));
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
  function drawSelection(guides, marquee) {
    selLayer.replaceChildren();
    $("#ed-empty").hidden = !hud || hud.layers.length > 0;
    const list = sel();
    const pos = $("#ed-pos");
    if (marquee) {
      const [x, y] = toScreen(marquee.x, marquee.y);
      selLayer.appendChild(h("div", { class: "marquee", style: { left: x + "px", top: y + "px", width: marquee.w * scale + "px", height: marquee.h * scale + "px" } }));
    }
    if (!list.length) { pos.textContent = ""; return; }
    const outline = (l, cls) => {
      const [x, y] = toScreen(l.x, l.y);
      return h("div", { class: cls, style: { left: x + "px", top: y + "px", width: l.w * scale + "px", height: l.h * scale + "px",
        transform: l.rotation ? `rotate(${l.rotation}deg)` : "" } });
    };
    if (list.length === 1) {
      const l = list[0];
      const box = outline(l, "sel-box" + (l.locked ? " locked" : ""));
      if (!l.locked) for (const hd of HANDLES) {
        const hx = hd.includes("w") ? 0 : hd.includes("e") ? 100 : 50, hy = hd.includes("n") ? 0 : hd.includes("s") ? 100 : 50;
        box.appendChild(h("div", { class: "handle", dataset: { h: hd }, style: { left: hx + "%", top: hy + "%", cursor: hd + "-resize" } }));
      }
      selLayer.appendChild(box);
      pos.textContent = `${Math.round(l.x)}, ${Math.round(l.y)} · ${Math.round(l.w)} × ${Math.round(l.h)}`;
    } else {
      for (const l of list) selLayer.appendChild(outline(l, "sel-each"));
      const b = bounds(list);
      selLayer.appendChild(outline(b, "sel-box multi"));
      pos.textContent = `${list.length} layers · ${Math.round(b.x)}, ${Math.round(b.y)} · ${Math.round(b.w)} × ${Math.round(b.h)}`;
    }
    for (const g of guides || []) {
      if (g.x != null) { const [gx] = toScreen(g.x, 0); selLayer.appendChild(h("div", { class: "guide", style: { left: gx + "px", top: 0, bottom: 0, width: "1px" } })); }
      if (g.y != null) { const [, gy] = toScreen(0, g.y); selLayer.appendChild(h("div", { class: "guide", style: { top: gy + "px", left: 0, right: 0, height: "1px" } })); }
    }
  }

  // The layer under a point (top first; hidden and locked ones are skipped).
  function hit(px, py) {
    for (const l of [...hud.layers].reverse()) {
      if (l.visible === false || l.locked) continue;
      if (px >= l.x && px <= l.x + l.w && py >= l.y && py <= l.y + l.h) return l;
    }
    return null;
  }
  const groupOf = l => l.group ? hud.layers.filter(o => o.group === l.group) : [l];
  function pick(l, add, single) {
    const ids = (single ? [l] : groupOf(l)).map(o => o.id);
    if (add) {
      const all = ids.every(id => selected.has(id));
      ids.forEach(id => all ? selected.delete(id) : selected.add(id));
    } else {
      selected.clear();
      ids.forEach(id => selected.add(id));
    }
  }

  // Snapping the moving box's edges and middle to the canvas and the other layers.
  function snap(box, moving) {
    const tol = 6 / scale;
    const xs = [0, W() / 2, W()], ys = [0, H() / 2, H()];
    for (const o of hud.layers) {
      if (moving.has(o.id) || o.visible === false) continue;
      xs.push(o.x, o.x + o.w / 2, o.x + o.w);
      ys.push(o.y, o.y + o.h / 2, o.y + o.h);
    }
    const best = (cands, edges) => {
      let found = null;
      for (const [k, e] of edges.entries()) for (const c of cands) {
        const d = c - e;
        if (Math.abs(d) <= tol && (!found || Math.abs(d) < Math.abs(found.d))) found = { d, at: c, k };
      }
      return found;
    };
    const sx = best(xs, [box.x, box.x + box.w / 2, box.x + box.w]);
    const sy = best(ys, [box.y, box.y + box.h / 2, box.y + box.h]);
    return { dx: sx ? sx.d : 0, dy: sy ? sy.d : 0, guides: [sx ? { x: sx.at } : null, sy ? { y: sy.at } : null].filter(Boolean) };
  }

  canvas.addEventListener("mousedown", e => {
    if (!hud || e.button !== 0) return;
    canvas.focus({ preventScroll: true });
    const [px, py] = toCanvas(e.clientX, e.clientY);
    const handle = e.target.closest && e.target.closest(".handle");
    const list = sel();
    if (handle && list.length === 1) return startResize(e, list[0], handle.dataset.h);
    if (picker) {
      const l = hit(px, py);
      if (l) { selected.clear(); selected.add(l.id); renderAll(); picker(l); }
      return;
    }
    const add = e.shiftKey || e.ctrlKey || e.metaKey;
    // Clicking inside the selection keeps it (to drag it, even over another layer).
    const inSel = list.length && !add && list.some(l => !l.locked && px >= l.x && px <= l.x + l.w && py >= l.y && py <= l.y + l.h);
    if (!inSel) {
      const l = hit(px, py);
      if (!l) {
        if (!add) selected.clear();
        return startMarquee(e, px, py, add);
      }
      pick(l, add, e.altKey);
      renderAll();
      if (add) return;
    }
    startMove(e, px, py);
  });
  canvas.addEventListener("dblclick", e => {
    if (!hud) return;
    const [px, py] = toCanvas(e.clientX, e.clientY);
    const l = hit(px, py);
    if (!l) return;
    selected.clear(); selected.add(l.id);
    renderAll();
    if (l.type === "text") { const t = $("#ed-props textarea[data-k=text]"); if (t) { t.focus(); t.select(); } }
  });

  function drag(onMove, onUp) {
    const move = ev => onMove(ev);
    const up = ev => { removeEventListener("mousemove", move); removeEventListener("mouseup", up); onUp && onUp(ev); };
    addEventListener("mousemove", move);
    addEventListener("mouseup", up);
  }
  function startMove(e, px, py) {
    const list = sel().filter(l => !l.locked);
    if (!list.length) return;
    const start = list.map(l => [l, l.x, l.y]);
    const b0 = bounds(list), ids = new Set(list.map(l => l.id));
    let moved = false;
    drag(ev => {
      const [qx, qy] = toCanvas(ev.clientX, ev.clientY);
      let dx = qx - px, dy = qy - py;
      if (!moved && Math.abs(dx) * scale < 3 && Math.abs(dy) * scale < 3) return;
      if (!moved) { snapshot(); moved = true; }
      if (ev.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
      let guides = [];
      if (!ev.altKey) {
        const s = snap({ x: b0.x + dx, y: b0.y + dy, w: b0.w, h: b0.h }, ids);
        dx += s.dx; dy += s.dy; guides = s.guides;
      }
      for (const [l, x, y] of start) { l.x = Math.round(x + dx); l.y = Math.round(y + dy); }
      redraw();
      drawSelection(guides);
    }, () => { if (moved) changed(); });
  }
  function startResize(e, l, hd) {
    e.preventDefault();
    const s = { x: l.x, y: l.y, w: l.w, h: l.h };
    const [px, py] = toCanvas(e.clientX, e.clientY);
    const ratio = s.w / (s.h || 1);
    snapshot();
    let moved = false;
    drag(ev => {
      moved = true;
      const [qx, qy] = toCanvas(ev.clientX, ev.clientY);
      const dx = qx - px, dy = qy - py;
      let { x, y, w, h: hh } = s;
      if (hd.includes("e")) w = s.w + dx;
      if (hd.includes("s")) hh = s.h + dy;
      if (hd.includes("w")) { w = s.w - dx; x = s.x + dx; }
      if (hd.includes("n")) { hh = s.h - dy; y = s.y + dy; }
      if (ev.shiftKey && hd.length === 2) {
        // (keeps its shape)
        if (w / ratio > hh) hh = w / ratio; else w = hh * ratio;
        if (hd.includes("w")) x = s.x + s.w - w;
        if (hd.includes("n")) y = s.y + s.h - hh;
      }
      l.w = Math.max(2, Math.round(w)); l.h = Math.max(2, Math.round(hh));
      l.x = Math.round(Math.min(x, s.x + s.w - 2)); l.y = Math.round(Math.min(y, s.y + s.h - 2));
      redraw();
    }, () => { if (moved) changed(); else undo.pop(); });
  }
  function startMarquee(e, px, py, add) {
    const before = new Set(selected);
    let box = null;
    drag(ev => {
      const [qx, qy] = toCanvas(ev.clientX, ev.clientY);
      box = { x: Math.min(px, qx), y: Math.min(py, qy), w: Math.abs(qx - px), h: Math.abs(qy - py) };
      selected.clear();
      if (add) before.forEach(id => selected.add(id));
      for (const l of hud.layers) {
        if (l.visible === false || l.locked) continue;
        if (l.x < box.x + box.w && l.x + l.w > box.x && l.y < box.y + box.h && l.y + l.h > box.y) groupOf(l).forEach(o => selected.add(o.id));
      }
      drawSelection(null, box);
    }, () => renderAll());
  }

  // --- adding layers ------------------------------------------------------------------
  const ANIM_NONE = { type: "none", dur: 400, delay: 0 };
  function newLayer(type, extra) {
    const l = { id: uid("l"), name: type === "rect" ? "Shape" : type === "text" ? "Text" : type === "image" ? "Picture" : type === "video" ? "Video" : type === "lottie" ? "Animation" : "Layer",
      type, x: 760, y: 440, w: 400, h: 200, opacity: 1, rotation: 0, visible: true, blend: "normal", field: "",
      anim: { in: Object.assign({}, ANIM_NONE), out: Object.assign({}, ANIM_NONE) } };
    if (type === "text") Object.assign(l, { text: "Text", font: "Inter", size: 64, color: "#ffffff", align: "left", valign: "middle", tracking: 0,
      caps: false, lineHeight: 1.1, fit: "shrink", weight: 700, italic: false, scroll: 0, h: 90 });
    if (type === "rect") Object.assign(l, { fill: "#1f6feb", radius: 0, stroke: "#ffffff", strokeWidth: 0, shape: "rect" });
    if (["image", "video", "lottie"].includes(type)) Object.assign(l, { src: "", fit: "contain", loop: true });
    return Object.assign(l, extra || {});
  }
  function uniqueName(base) {
    const names = new Set(hud.layers.map(l => l.name));
    if (!names.has(base)) return base;
    let n = 2;
    while (names.has(`${base} ${n}`)) n++;
    return `${base} ${n}`;
  }
  function addLayers(list, at) {
    snapshot();
    for (const l of list) {
      l.name = uniqueName(l.name);
      if (at) { l.x = Math.round(at[0] - l.w / 2); l.y = Math.round(at[1] - l.h / 2); }
      hud.layers.push(l);
    }
    selected.clear();
    list.forEach(l => selected.add(l.id));
    changed({ vars: true });
  }
  const SHAPES = {
    rect: () => newLayer("rect", { name: "Rectangle", w: 480, h: 120 }),
    ellipse: () => newLayer("rect", { name: "Ellipse", shape: "ellipse", w: 200, h: 200 }),
    angled: () => newLayer("rect", { name: "Angled bar", shape: "angled", skew: 28, w: 520, h: 72, fill: "#111318", fill2: "#1f6feb", gradAngle: 90 }),
    line: () => newLayer("rect", { name: "Line", w: 600, h: 4, fill: "#ffffff" }),
    text: () => newLayer("text", { name: "Text", text: "TEXT", w: 600, h: 90 }),
  };
  $$("[data-add]").forEach(b => b.addEventListener("click", () => {
    if (!hud) return;
    const k = b.dataset.add;
    if (k === "image" || k === "reference") { $("#ed-file").dataset.reference = k === "reference" ? "1" : ""; $("#ed-file").click(); return; }
    addLayers([SHAPES[k]()]);
  }));
  $("#ed-file").addEventListener("change", async e => {
    const files = [...e.target.files];
    e.target.value = "";
    await addFiles(files, null, $("#ed-file").dataset.reference === "1");
  });

  async function upload(file) {
    const r = await api(`/api/huds/${hud.id}/asset?name=${encodeURIComponent(file.name)}`, await readFile(file), true);
    live.assets = r.assets;
    loadFonts();
    return r.path;
  }
  function naturalSize(path) {
    return new Promise(ok => {
      if (!/\.(png|jpe?g|webp|gif|svg)$/i.test(path)) return ok(null);
      const img = new Image();
      img.onload = () => ok([img.naturalWidth, img.naturalHeight]);
      img.onerror = () => ok(null);
      img.src = GFX.url(encodeURI(path));
    });
  }
  async function addFiles(files, at, reference) {
    const made = [];
    for (const f of files) {
      try {
        const path = await upload(f);
        const ext = path.split(".").pop().toLowerCase();
        if (["ttf", "otf", "woff", "woff2"].includes(ext)) { toast(`Font added: ${path.replace(/^assets\/|\.[^.]+$/g, "")}`); renderProps(); continue; }
        const type = ["webm", "mp4"].includes(ext) ? "video" : ext === "json" ? "lottie" : "image";
        const name = f.name.replace(/\.[^.]+$/, "") || "Picture";
        let w = 400, hh = 300;
        const size = await naturalSize(path);
        if (size) {
          const k = Math.min(1, (reference ? W() : W() * 0.6) / size[0], (reference ? H() : H() * 0.6) / size[1]);
          w = Math.round(size[0] * k); hh = Math.round(size[1] * k);
        }
        if (reference) made.push(newLayer("image", { name: "Game screenshot (not on air)", src: path, x: 0, y: 0, w: W(), h: H(), fit: "cover",
          reference: true, locked: true, opacity: 0.5 }));
        else made.push(newLayer(type, { name, src: path, w, h: hh, x: Math.round((W() - w) / 2), y: Math.round((H() - hh) / 2) }));
      } catch (err) { toast(err.message, true); }
    }
    if (!made.length) return;
    if (reference) {
      // (the screenshot goes under everything)
      snapshot();
      made.forEach(l => hud.layers.unshift(l));
      changed();
      toast("Screenshot added under your design. It's only here to line things up: it never goes on air.");
    } else addLayers(made, made.length === 1 ? at : null);
  }

  // A GFX Engine graphic or a Photoshop file: its layers (and a graphic's
  // fields, as variables) added to this HUD, as a group, in one undo step.
  const DESIGN = /\.(sccgfx|psd|psb|fig|zip)$/i;
  async function importDesign(file) {
    if (!hud) return toast("Open a HUD first", true);
    const b = $("#ed-import");
    b.disabled = true;
    const was = b.textContent;
    b.textContent = "Importing…";
    try {
      await flush();
      const r = await api(`/api/huds/${hud.id}/import-design?name=${encodeURIComponent(file.name)}`, await readFile(file), true);
      live.assets = r.assets;
      loadFonts();
      snapshot();
      const have = new Set(vars().map(v => v.name.toLowerCase()));
      const added = r.vars.filter(v => !have.has(v.name.toLowerCase()));
      hud.vars.push(...added);
      for (const l of r.layers) hud.layers.push(l);
      selected.clear();
      r.layers.forEach(l => selected.add(l.id));
      changed({ vars: true });
      const parts = [`Imported ${r.name}: ${r.layers.length} layer${r.layers.length === 1 ? "" : "s"}`];
      if (added.length) parts.push(`${added.length} new variable${added.length === 1 ? "" : "s"} for the control panel`);
      let msg = parts.join(", ") + ".";
      if (r.notes.length) msg += " " + r.notes.join(". ") + ".";
      if (r.fonts_missing.length) msg += ` Fonts to add (Text > Add font…): ${r.fonts_missing.join(", ")}.`;
      toast(msg, false, r.fonts_missing.length || r.notes.length ? 9000 : 0);
      // Then the walk through linking its layers to the game's data.
      if (window.Guide) { await loadGameData(); Guide.start({ fresh: true }); }
    } catch (e) { toast(e.message, true); }
    finally { b.disabled = false; b.textContent = was; }
  }
  $("#ed-import").addEventListener("click", () => hud && $("#ed-import-file").click());
  $("#ed-import-file").addEventListener("change", e => { const f = e.target.files[0]; e.target.value = ""; if (f) importDesign(f); });

  // Dropping files from the PC, or a variable from the list.
  canvas.addEventListener("dragover", e => { e.preventDefault(); canvas.classList.add("drop"); });
  canvas.addEventListener("dragleave", () => canvas.classList.remove("drop"));
  canvas.addEventListener("drop", async e => {
    e.preventDefault();
    canvas.classList.remove("drop");
    if (!hud) return;
    const at = toCanvas(e.clientX, e.clientY);
    const name = e.dataTransfer.getData("text/x-hud-var");
    const builtin = e.dataTransfer.getData("text/x-hud-token");
    const data = e.dataTransfer.getData("text/x-hud-data");
    if (data) {
      const f = allData().find(x => x.token === data);
      const target = hit(at[0], at[1]);
      if (f) return target ? linkData(target, f) : addLayers([layerFor(f)], at);
    }
    if (name || builtin) {
      const target = hit(at[0], at[1]);
      if (name) return dropVar(vars().find(v => v.name === name), target, at);
      return addLayers([newLayer("text", { name: builtin.replace(/[{}]/g, ""), text: builtin, w: 360, h: 80 })], at);
    }
    const files = [...(e.dataTransfer.files || [])];
    for (const f of files.filter(f => DESIGN.test(f.name))) await importDesign(f);
    const media = files.filter(f => !DESIGN.test(f.name));
    if (media.length) await addFiles(media, at, false);
  });

  // A variable dropped on a layer links it; on empty canvas it makes the layer that shows it.
  function dropVar(v, target, at) {
    if (!v) return;
    const t = token(v.name);
    if (target) {
      snapshot();
      if (v.kind === "toggle") { target.when = [{ value: t, op: "has" }]; toast(`${target.name} now shows only while ${v.name} is on`); }
      else if (target.type === "text") { target.text = t; toast(`${target.name} shows ${v.name}`); }
      else if (target.type === "rect" && v.kind === "color") { target.fill = t; toast(`${target.name}'s colour is ${v.name}`); }
      else if (target.type === "rect" && v.kind === "number") { target.meter = Object.assign({ max: v.max || "100", dir: "right" }, target.meter, { value: t }); toast(`${target.name} fills by ${v.name}`); }
      else if (["image", "video"].includes(target.type) && ["image", "text"].includes(v.kind)) { target.src = t; toast(`${target.name} shows ${v.name}`); }
      else { undo.pop(); return dropVar(v, null, at); }
      selected.clear(); selected.add(target.id);
      return changed();
    }
    let l;
    if (v.kind === "color") l = newLayer("rect", { name: v.name, fill: t, w: 400, h: 16 });
    else if (v.kind === "image") l = newLayer("image", { name: v.name, src: t, w: 240, h: 240 });
    else if (v.kind === "toggle") l = newLayer("text", { name: v.name, text: v.name.toUpperCase(), w: 400, h: 80, when: [{ value: t, op: "has" }] });
    else if (v.kind === "number") l = newLayer("text", { name: v.name, text: t, w: 160, h: 110, size: 88, align: "center", font: "Bebas Neue", weight: 400 });
    else l = newLayer("text", { name: v.name, text: t, w: 480, h: 80 });
    addLayers([l], at);
  }

  // --- the layer list ------------------------------------------------------------------
  function renderLayers() {
    const box = $("#ed-layer-list");
    if (!hud) return box.replaceChildren();
    const rows = [], done = new Set();
    const list = [...hud.layers].reverse();     // top first, as in Photoshop
    for (const l of list) {
      if (done.has(l.id)) continue;
      if (l.group) {
        const members = list.filter(o => o.group === l.group);
        members.forEach(o => done.add(o.id));
        const allSel = members.every(o => selected.has(o.id));
        const name = members.find(o => o.groupName) ? members.find(o => o.groupName).groupName : "Group";
        const hidden = members.every(o => o.visible === false);
        rows.push(h("div", { class: "lrow group" + (allSel ? " sel" : ""), draggable: true, dataset: { group: l.group },
          onclick: ev => { if (!(ev.ctrlKey || ev.metaKey || ev.shiftKey)) selected.clear(); members.forEach(o => selected.add(o.id)); renderAll(); } },
          eye(members, hidden), h("span", { class: "lic" }, "▾"),
          h("span", { class: "lname", title: "Double-click to rename", ondblclick: ev => { ev.stopPropagation(); rename(name, val => { snapshot(); members.forEach(o => { o.groupName = val; }); changed(); }); } }, name),
          h("span", { class: "lmeta" }, String(members.length))));
        members.forEach(o => rows.push(row(o, true)));
      } else rows.push(row(l, false));
      done.add(l.id);
    }
    if (!rows.length) rows.push(h("p", { class: "muted hint" }, "No layers yet."));
    box.replaceChildren(...rows);
  }
  const ICON = { rect: "▭", text: "T", image: "🖼", video: "▶", lottie: "✦", web: "◫" };
  function eye(layers, hidden) {
    return h("button", { class: "lbtn" + (hidden ? " off" : ""), title: hidden ? "Show" : "Hide", onclick: ev => {
      ev.stopPropagation(); snapshot(); layers.forEach(o => { o.visible = hidden; }); changed();
    } }, hidden ? "◌" : "●");
  }
  function row(l, inGroup) {
    const live = isLive(l);
    const r = h("div", { class: "lrow" + (selected.has(l.id) ? " sel" : "") + (inGroup ? " in" : "") + (l.reference ? " ref" : ""), draggable: true,
      dataset: { id: l.id },
      onclick: ev => { if (picker) { selected.clear(); selected.add(l.id); renderAll(); return picker(l); } pick(l, ev.ctrlKey || ev.metaKey || ev.shiftKey, true); renderAll(); } },
      eye([l], l.visible === false),
      h("span", { class: "lic" }, l.type === "rect" ? ({ ellipse: "◯", angled: "▱" }[l.shape] || "▭") : ICON[l.type] || "•"),
      h("span", { class: "lname", title: "Double-click to rename", ondblclick: ev => { ev.stopPropagation(); rename(l.name, val => { snapshot(); l.name = val; changed(); }); } }, l.name),
      live ? h("span", { class: "llive", title: "Follows a variable" }, "ƒ") : null,
      l.reference ? h("span", { class: "lmeta" }, "ref") : null,
      h("button", { class: "lbtn" + (l.locked ? " on" : " dim"), title: l.locked ? "Unlock" : "Lock (can't be clicked on the canvas)", onclick: ev => {
        ev.stopPropagation(); snapshot(); l.locked = !l.locked; if (!l.locked) delete l.locked; changed();
      } }, l.locked ? "🔒" : "🔓"));
    return r;
  }
  function rename(current, done) {
    const v = prompt("Name", current);
    if (v != null && v.trim() && v.trim() !== current) done(v.trim().slice(0, 80));
  }
  const isLive = l => [l.text, l.fill, l.src, l.color, l.fill2, l.stroke].some(v => /\{\{[^{}]+\}\}/.test(String(v || ""))) || !!l.meter || !!l.when;

  // Reordering by dragging rows: dropped on a row, the dragged layer (or group) goes just above it.
  let dragRow = null;
  $("#ed-layer-list").addEventListener("dragstart", e => {
    const r = e.target.closest(".lrow");
    if (!r) return;
    dragRow = r.dataset.group ? hud.layers.filter(l => l.group === r.dataset.group).map(l => l.id) : [r.dataset.id];
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/x-hud-layer", "1");
  });
  $("#ed-layer-list").addEventListener("dragover", e => { if (dragRow) { e.preventDefault(); } });
  $("#ed-layer-list").addEventListener("drop", e => {
    e.preventDefault();
    const r = e.target.closest(".lrow");
    const ids = dragRow;
    dragRow = null;
    if (!ids || !r) return;
    const targetIds = r.dataset.group ? hud.layers.filter(l => l.group === r.dataset.group).map(l => l.id) : [r.dataset.id];
    if (targetIds.some(id => ids.includes(id))) return;
    snapshot();
    const moving = hud.layers.filter(l => ids.includes(l.id));
    hud.layers = hud.layers.filter(l => !ids.includes(l.id));
    // ("above" in the list = later in the layers)
    const at = Math.max(...targetIds.map(id => hud.layers.findIndex(l => l.id === id))) + 1;
    const target = hud.layers.find(l => l.id === r.dataset.id);
    // (dropped on a layer inside a group: it joins that group)
    moving.forEach(l => { if (!r.dataset.group && target && target.group && !moving.some(m => m.group === target.group)) l.group = target.group; else if (!r.dataset.group && target && !target.group && l.group && ids.length === 1) delete l.group; });
    hud.layers.splice(at, 0, ...moving);
    changed();
  });

  // --- grouping, order and the clipboard ------------------------------------------------
  function group() {
    const list = sel();
    if (list.length < 2) return toast("Pick two or more layers to group (Ctrl+click)", true);
    snapshot();
    const g = uid("g");
    const top = Math.max(...list.map(l => hud.layers.indexOf(l)));
    const rest = hud.layers.filter(l => !selected.has(l.id));
    const at = rest.filter(l => hud.layers.indexOf(l) < top).length;
    list.forEach(l => { l.group = g; delete l.groupName; });
    rest.splice(at, 0, ...list);
    hud.layers = rest;
    changed();
    toast("Grouped: they move, hide and get picked together. Alt+click picks one inside.");
  }
  function ungroup() {
    const list = sel().filter(l => l.group);
    if (!list.length) return;
    snapshot();
    list.forEach(l => { delete l.group; delete l.groupName; });
    changed();
  }
  $("#ed-group").addEventListener("click", () => sel().some(l => l.group) && sel().every(l => l.group === sel()[0].group) ? ungroup() : group());
  function order(dir) {
    const ids = sel().map(l => l.id);
    if (!ids.length) return;
    snapshot();
    const moving = hud.layers.filter(l => ids.includes(l.id));
    let rest = hud.layers.filter(l => !ids.includes(l.id));
    const first = hud.layers.indexOf(moving[0]);
    const before = hud.layers.slice(0, first).filter(l => !ids.includes(l.id)).length;
    const at = dir === "top" ? rest.length : dir === "bottom" ? 0 : Math.max(0, Math.min(rest.length, before + (dir === "up" ? 1 : -1)));
    rest.splice(at, 0, ...moving);
    hud.layers = rest;
    changed();
  }
  function remove() {
    if (!selected.size) return;
    snapshot();
    hud.layers = hud.layers.filter(l => !selected.has(l.id));
    selected.clear();
    changed();
  }
  function copy() { const list = sel(); if (list.length) clip = JSON.stringify(list); }
  function paste(offset) {
    if (!clip) return;
    const list = JSON.parse(clip);
    const groups = {};
    for (const l of list) {
      l.id = uid("l");
      if (l.group) l.group = groups[l.group] = groups[l.group] || uid("g");
      l.x += offset; l.y += offset;
    }
    addLayers(list);
  }

  // --- keys ------------------------------------------------------------------------------
  addEventListener("keydown", e => {
    if (!hud || document.body.dataset.page !== "design" || typing() || $("dialog[open]")) return;
    const mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
    if (mod && k === "z" && !e.shiftKey) { e.preventDefault(); return doUndo(); }
    if (mod && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); return doRedo(); }
    if (mod && k === "s") { e.preventDefault(); flush(); return toast("Saved"); }
    if (mod && k === "a") { e.preventDefault(); hud.layers.forEach(l => { if (!l.locked) selected.add(l.id); }); return renderAll(); }
    if (mod && k === "c") { copy(); return; }
    if (mod && k === "x") { copy(); return remove(); }
    if (mod && k === "v") { e.preventDefault(); return paste(20); }
    if (mod && k === "d") { e.preventDefault(); copy(); return paste(20); }
    if (mod && k === "g") { e.preventDefault(); return e.shiftKey ? ungroup() : group(); }
    if (mod && k === "]") { e.preventDefault(); return order(e.shiftKey ? "top" : "up"); }
    if (mod && k === "[") { e.preventDefault(); return order(e.shiftKey ? "bottom" : "down"); }
    if (k === "delete" || k === "backspace") { e.preventDefault(); return remove(); }
    if (k === "escape") { selected.clear(); return renderAll(); }
    const arrows = { arrowleft: [-1, 0], arrowright: [1, 0], arrowup: [0, -1], arrowdown: [0, 1] };
    if (arrows[k] && selected.size) {
      e.preventDefault();
      const n = e.shiftKey ? 10 : 1;
      snapshot();
      sel().filter(l => !l.locked).forEach(l => { l.x += arrows[k][0] * n; l.y += arrows[k][1] * n; });
      changed({ keepProps: false });
    }
  });
  $("#ed-undo").addEventListener("click", doUndo);
  $("#ed-redo").addEventListener("click", doRedo);
  $("#ed-name").addEventListener("change", e => { snapshot(); hud.name = e.target.value.trim() || hud.name; e.target.value = hud.name; changed(); });
  $("#ed-game").addEventListener("change", e => { snapshot(); hud.game = e.target.value; changed(); loadGameData(); });
  $("#ed-play").addEventListener("click", async () => {
    if (!root) return;
    const b = $("#ed-play");
    b.disabled = true;
    GFX.finish(root);
    await GFX.play(root, "in");
    await new Promise(r => setTimeout(r, 900));
    await GFX.play(root, "out");
    await new Promise(r => setTimeout(r, 400));
    root.querySelectorAll(".gfx-A").forEach(a => a.getAnimations().forEach(x => x.cancel()));
    b.disabled = false;
  });

  // --- properties ----------------------------------------------------------------------
  // Each edit: an undo step when a field is first changed, drawn as you type.
  function bind(l, key, kind, extra) {
    extra = extra || {};
    let fresh = true;
    const set = v => {
      if (fresh) { snapshot(); fresh = false; }
      if (kind === "number") v = v === "" ? 0 : +v;
      if (v === "" && extra.removeEmpty) delete l[key]; else l[key] = v;
      extra.after && extra.after(v);
      changed({ keepProps: true });
    };
    let input;
    if (kind === "check") {
      input = h("input", { type: "checkbox", checked: !!l[key], onchange: e => { set(e.target.checked); renderProps(); } });
      return h("label", { class: "check" }, input, extra.label);
    }
    if (kind === "select") {
      input = h("select", { onchange: e => { set(e.target.value); if (extra.rerender) renderProps(); } },
        extra.options.map(([v, t]) => h("option", { value: v, selected: String(l[key] ?? extra.def ?? "") === String(v) }, t)));
    } else if (kind === "textarea") {
      input = h("textarea", { rows: 3, dataset: { k: key }, oninput: e => set(e.target.value) }, l[key] ?? "");
    } else {
      input = h("input", { type: kind === "number" ? "number" : "text", step: extra.step || 1, value: l[key] ?? extra.def ?? "",
        min: extra.min, max: extra.max, placeholder: extra.placeholder || "", oninput: e => set(e.target.value) });
    }
    input.addEventListener("focus", () => { fresh = true; });
    input.addEventListener("blur", () => renderLayers());
    return extra.label ? h("label", {}, extra.label, input) : input;
  }
  const lab = (text, ...kids) => h("label", {}, text, ...kids);
  const sect = (title, ...kids) => h("div", { class: "sect" }, title ? h("h4", {}, title) : null, ...kids);
  const grid = (...kids) => h("div", { class: "grid" + kids.filter(Boolean).length }, ...kids);
  const varsOf = kinds => vars().filter(v => !kinds || kinds.includes(v.kind));

  // A colour: picked, typed, or one of the HUD's colour variables.
  function colourField(l, key, label, opts) {
    opts = opts || {};
    const val = l[key] || "";
    const linked = tokenName(val);
    let fresh = true;
    const set = v => { if (fresh) { snapshot(); fresh = false; } if (v === "" && opts.removeEmpty) delete l[key]; else l[key] = v; changed({ keepProps: true }); };
    const shown = linked ? (GFX.resolve(val).trim() || "#888888") : val;
    const picker = h("input", { type: "color", value: /^#[0-9a-f]{6}$/i.test(shown) ? shown : "#ffffff", disabled: !!linked,
      oninput: e => { text.value = e.target.value; set(e.target.value); } });
    const text = h("input", { type: "text", value: linked ? "" : val, placeholder: linked ? "" : opts.placeholder || "#ffffff",
      hidden: !!linked, oninput: e => set(e.target.value.trim()), onblur: () => renderProps() });
    picker.addEventListener("focus", () => { fresh = true; });
    text.addEventListener("focus", () => { fresh = true; });
    const pickVar = h("select", { class: "var-pick", title: "Take the colour from a variable", onchange: e => {
      fresh = true;
      set(e.target.value ? token(e.target.value) : (opts.removeEmpty ? "" : "#ffffff"));
      renderProps();
    } }, h("option", { value: "" }, linked ? "Fixed colour" : "ƒ"), varsOf(["color"]).map(v => h("option", { value: v.name, selected: v.name === linked }, v.name)));
    return h("label", {}, label, h("div", { class: "colour-row" + (linked ? " linked" : "") }, picker, linked ? h("span", { class: "chip" }, "ƒ " + linked) : text, pickVar));
  }
  // A picture (video, animation): one of the HUD's files, a new one, or a picture variable.
  function sourceField(l) {
    const kind = l.type;
    const re = kind === "video" ? /\.(webm|mp4)$/i : kind === "lottie" ? /\.json$/i : /\.(png|jpe?g|webp|gif|svg)$/i;
    const list = live.assets.filter(a => re.test(a));
    const linked = tokenName(l.src);
    const file = h("input", { type: "file", hidden: true, accept: kind === "image" ? "image/*" : kind === "video" ? "video/webm,video/mp4" : ".json",
      onchange: async e => {
        const f = e.target.files[0];
        if (!f) return;
        try { const p = await upload(f); snapshot(); l.src = p; changed(); } catch (err) { toast(err.message, true); }
      } });
    return sect(kind === "image" ? "Picture" : kind === "video" ? "Video" : "Animation",
      h("div", { class: "row-gap" },
        h("select", { onchange: e => { snapshot(); l.src = e.target.value.startsWith("var:") ? token(e.target.value.slice(4)) : e.target.value; changed(); } },
          h("option", { value: "" }, "(none)"),
          h("optgroup", { label: "This HUD's files" }, list.map(a => h("option", { value: a, selected: a === l.src }, a.replace(/^assets\//, "")))),
          varsOf(["image", "text"]).length ? h("optgroup", { label: "From a variable" }, varsOf(["image", "text"]).map(v => h("option", { value: "var:" + v.name, selected: v.name === linked }, "ƒ " + v.name))) : null),
        h("button", { onclick: () => file.click() }, "Upload…"), file),
      grid(bind(l, "fit", "select", { label: "Fit", options: [["contain", "Fit inside"], ["cover", "Fill (crop)"], ["fill", "Stretch"]], def: "contain" }),
        kind === "image" ? bind(l, "position", "select", { label: "Sits", options: [["", "Middle"], ["top", "Top"], ["bottom", "Bottom"], ["left", "Left"], ["right", "Right"]], def: "" }) : null),
      kind !== "image" ? bind(l, "loop", "check", { label: "Loop" }) : null,
      grid(bind(l, "clip", "select", { label: "Cut to", options: [["", "Its box"], ["rounded", "Rounded box"], ["ellipse", "Circle / ellipse"], ["angled", "Angled"]], def: "", removeEmpty: true, rerender: true }),
        l.clip === "rounded" ? bind(l, "clipRadius", "number", { label: "Roundness", def: 16 }) : l.clip === "angled" ? bind(l, "skew", "number", { label: "Slant (px)", def: 24 }) : null));
  }

  function renderProps() {
    const box = $("#ed-props");
    if (!hud) return box.replaceChildren();
    const list = sel();
    if (!list.length) return box.replaceChildren(hudProps());
    if (list.length > 1) return box.replaceChildren(multiProps(list));
    const l = list[0];
    const kids = [
      h("div", { class: "props-head" }, h("h3", {}, l.name), h("span", { class: "muted" }, typeName(l))),
      sect(null, bind(l, "name", "text", { label: "Name", after: () => renderLayers() }),
        grid(bind(l, "x", "number", { label: "X" }), bind(l, "y", "number", { label: "Y" }), bind(l, "w", "number", { label: "Width", min: 1 }), bind(l, "h", "number", { label: "Height", min: 1 })),
        grid(bind(l, "rotation", "number", { label: "Rotate °" }), opacityField(l),
          bind(l, "blend", "select", { label: "Blend", options: [["normal", "Normal"], ["screen", "Screen"], ["multiply", "Multiply"], ["overlay", "Overlay"], ["lighten", "Lighten"], ["darken", "Darken"], ["color-dodge", "Colour dodge"]], def: "normal" })),
        alignRow(list)),
    ];
    if (l.type === "rect") kids.push(shapeProps(l));
    if (l.type === "text") kids.push(textProps(l));
    if (["image", "video", "lottie"].includes(l.type)) kids.push(sourceField(l));
    if (l.type !== "text") kids.push(glowProps(l));
    kids.push(liveProps([l]), animProps(l),
      sect(null, bind(l, "reference", "check", { label: "Only for lining up (never on air)" }),
        h("div", { class: "row-gap" },
          h("button", { class: "small", onclick: () => order("up"), title: "Ctrl+]" }, "Forward"), h("button", { class: "small", onclick: () => order("down"), title: "Ctrl+[" }, "Back"),
          h("button", { class: "small", onclick: () => { copy(); paste(20); } }, "Duplicate"), h("button", { class: "small danger", onclick: remove }, "Delete"))));
    box.replaceChildren(...kids);
  }
  const typeName = l => l.type === "rect" ? ({ ellipse: "Ellipse", angled: "Angled bar" }[l.shape] || "Rectangle") : { text: "Text", image: "Picture", video: "Video", lottie: "Lottie animation", web: "Web page" }[l.type] || l.type;
  function opacityField(l) {
    let fresh = true;
    const input = h("input", { type: "number", min: 0, max: 100, step: 5, value: Math.round((l.opacity == null ? 1 : l.opacity) * 100),
      onfocus: () => { fresh = true; }, oninput: e => { if (fresh) { snapshot(); fresh = false; } l.opacity = Math.max(0, Math.min(100, +e.target.value || 0)) / 100; changed({ keepProps: true }); } });
    return lab("Opacity %", input);
  }
  function alignRow(list) {
    const target = list.length > 1 ? bounds(list) : { x: 0, y: 0, w: W(), h: H() };
    const move = fn => () => { snapshot(); list.forEach(fn); changed({ keepProps: false }); };
    const b = (t, title, fn) => h("button", { class: "tool small", title, onclick: move(fn) }, t);
    return h("div", { class: "align-row", "aria-label": list.length > 1 ? "Line them up" : "Line up on the canvas" },
      h("span", { class: "muted small" }, list.length > 1 ? "Align" : "On canvas"),
      b("⇤", "Left", l => { l.x = target.x; }), b("↔", "Centre", l => { l.x = Math.round(target.x + (target.w - l.w) / 2); }), b("⇥", "Right", l => { l.x = target.x + target.w - l.w; }),
      b("⤒", "Top", l => { l.y = target.y; }), b("↕", "Middle", l => { l.y = Math.round(target.y + (target.h - l.h) / 2); }), b("⤓", "Bottom", l => { l.y = target.y + target.h - l.h; }));
  }
  function shapeProps(l) {
    const shape = l.shape || "rect";
    return sect("Shape",
      grid(bind(l, "shape", "select", { label: "Shape", options: [["rect", "Rectangle"], ["ellipse", "Ellipse"], ["angled", "Angled bar"]], def: "rect", rerender: true }),
        shape === "rect" ? bind(l, "radius", "number", { label: "Corners", min: 0 }) : shape === "angled" ? bind(l, "skew", "number", { label: "Slant (px, − leans left)", def: 24 }) : null),
      colourField(l, "fill", "Fill"),
      colourField(l, "fill2", "Fade to (a gradient)", { removeEmpty: true, placeholder: "none" }),
      l.fill2 ? bind(l, "gradAngle", "number", { label: "Gradient direction °", def: 90, step: 15 }) : null,
      grid(bind(l, "strokeWidth", "number", { label: "Outline", min: 0 }), +l.strokeWidth ? colourField(l, "stroke", "Outline colour") : null));
  }
  function glowProps(l) {
    const g = l.glow || {};
    let fresh = true;
    const set = (k, v) => { if (fresh) { snapshot(); fresh = false; } l.glow = Object.assign({ color: "#000000", blur: 0, x: 0, y: 0 }, l.glow, { [k]: v }); if (!+l.glow.blur && !+l.glow.x && !+l.glow.y) delete l.glow; changed({ keepProps: true }); };
    const num = (k, t) => lab(t, h("input", { type: "number", value: g[k] || 0, onfocus: () => { fresh = true; }, oninput: e => set(k, +e.target.value || 0) }));
    return sect("Shadow / glow", grid(num("blur", "Blur"), num("x", "Across"), num("y", "Down"),
      lab("Colour", h("input", { type: "color", value: /^#[0-9a-f]{6}$/i.test(g.color || "") ? g.color : "#000000", onfocus: () => { fresh = true; }, oninput: e => set("color", e.target.value) }))));
  }
  function textProps(l) {
    const fonts = [...GFX.builtinFonts, ...live.assets.filter(a => /\.(ttf|otf|woff2?)$/i.test(a)).map(a => a.replace(/^assets\//, "").replace(/\.[^.]+$/, ""))];
    if (l.font && !fonts.includes(l.font)) fonts.push(l.font);
    const ta = bind(l, "text", "textarea", { label: "Text" });
    const insert = h("select", { class: "var-pick", onchange: e => {
      const v = e.target.value;
      e.target.value = "";
      if (!v) return;
      const area = ta.querySelector("textarea");
      const t = v.startsWith("{{") ? v : token(v);
      const s = area.selectionStart ?? area.value.length, en = area.selectionEnd ?? area.value.length;
      snapshot();
      l.text = area.value.slice(0, s) + t + area.value.slice(en);
      changed();
    } }, h("option", { value: "" }, "ƒ Insert a variable…"), vars().map(v => h("option", { value: v.name }, v.name)),
      h("optgroup", { label: "Built in" }, BUILTINS.map(([t, n]) => h("option", { value: t }, n))),
      dataOf(["text", "number"]).map(([g, fs]) => h("optgroup", { label: "Game data: " + g.group }, fs.map(f => h("option", { value: f.token }, short(f))))));
    const file = h("input", { type: "file", hidden: true, accept: ".ttf,.otf,.woff,.woff2", onchange: async e => {
      const f = e.target.files[0];
      if (!f) return;
      try { const p = await upload(f); snapshot(); l.font = p.replace(/^assets\//, "").replace(/\.[^.]+$/, ""); changed(); } catch (err) { toast(err.message, true); }
    } });
    return sect("Text", ta, insert,
      h("div", { class: "row-gap" }, bind(l, "font", "select", { label: "Font", options: fonts.map(f => [f, f]), rerender: true }), h("button", { class: "small", title: "Add a font file (.ttf, .otf, .woff2)", onclick: () => file.click() }, "Add font…"), file),
      grid(bind(l, "size", "number", { label: "Size", min: 4 }),
        bind(l, "weight", "select", { label: "Weight", options: [[300, "Light"], [400, "Regular"], [500, "Medium"], [600, "Semibold"], [700, "Bold"], [800, "Extra bold"], [900, "Black"]], def: 700 }),
        bind(l, "tracking", "number", { label: "Spacing", step: 10 })),
      colourField(l, "color", "Colour"),
      grid(bind(l, "align", "select", { label: "Across", options: [["left", "Left"], ["center", "Centre"], ["right", "Right"]] }),
        bind(l, "valign", "select", { label: "Up / down", options: [["top", "Top"], ["middle", "Middle"], ["bottom", "Bottom"]], def: "top" }),
        bind(l, "fit", "select", { label: "Too long", options: [["shrink", "Shrink"], ["squeeze", "Squeeze"], ["none", "Leave it"]], def: "shrink" })),
      h("div", { class: "row-gap" }, bind(l, "caps", "check", { label: "All caps" }), bind(l, "italic", "check", { label: "Italic" }), bind(l, "shadow", "check", { label: "Shadow" })),
      grid(bind(l, "lineHeight", "number", { label: "Line height", step: 0.05, def: 1.15 }), bind(l, "scroll", "number", { label: "Ticker speed (0 = still)", min: 0, step: 10 })));
  }
  const BUILTINS = [["{{time}}", "Time (12 hour)"], ["{{time24}}", "Time (24 hour)"], ["{{date}}", "Date"]];

  // Show when / fill by.
  function liveProps(list) {
    const one = list.length === 1 ? list[0] : null;
    const each = fn => { snapshot(); list.forEach(fn); changed(); };
    const opts = (kinds, val, first) => {
      const data = dataOf(kinds);
      const known = varsOf(kinds).some(v => token(v.name) === val) || data.some(([, fs]) => fs.some(f => f.token === val));
      return [h("option", { value: "" }, first), val && !known ? h("option", { value: val, selected: true }, val) : null,
        varsOf(kinds).map(v => h("option", { value: token(v.name), selected: token(v.name) === val }, v.name)),
        data.map(([g, fs]) => h("optgroup", { label: "Game data: " + g.group }, fs.map(f => h("option", { value: f.token, selected: f.token === val }, short(f)))))];
    };
    const kids = [];
    if (one && (one.type === "rect" || one.type === "image")) {
      const m = one.meter;
      kids.push(lab("Fill by (a health or boost bar)", h("select", { onchange: e => each(l => { if (!e.target.value) delete l.meter; else l.meter = Object.assign({ max: "100", dir: "right" }, l.meter, { value: e.target.value }); }) },
        opts(["number", "text"], m ? m.value : "", "(always full)"))));
      if (m) {
        const setM = (k, v) => { snapshot(); one.meter[k] = v; changed(); };
        kids.push(grid(lab("Full at", h("input", { value: m.max ?? "100", onchange: e => setM("max", e.target.value) })),
          lab("Fills", h("select", { onchange: e => setM("dir", e.target.value) },
            [["right", "Left to right"], ["left", "Right to left"], ["up", "Bottom up"], ["down", "Top down"], ["ring", "Round (a dial)"]].map(([o, t]) => h("option", { value: o, selected: (m.dir || "right") === o }, t))))));
      }
    }
    const rules = one ? (Array.isArray(one.when) ? one.when : one.when ? [one.when] : []) : [];
    const setRules = r => each(l => { if (r.length) l.when = JSON.parse(JSON.stringify(r)); else delete l.when; });
    rules.forEach((r, i) => {
      const upd = (k, v) => { const c = rules.map(x => Object.assign({}, x)); c[i][k] = v; setRules(c); };
      kids.push(h("div", { class: "rule" },
        h("select", { onchange: e => { const c = rules.map(x => Object.assign({}, x)); if (e.target.value) c[i].value = e.target.value; else c.splice(i, 1); setRules(c); } },
          opts(null, r.value, "(remove)")),
        h("select", { onchange: e => upd("op", e.target.value) }, (GFX.RULE_OPS || [["has", "is on / has a value"], ["empty", "is off / empty"], ["is", "is"], ["not", "is not"]]).map(([o, t]) => h("option", { value: o, selected: (r.op || "has") === o }, t))),
        ["has", "empty"].includes(r.op || "has") ? null : h("input", { value: r.to ?? "", placeholder: "value", onchange: e => upd("to", e.target.value) })));
    });
    kids.push(lab(rules.length ? "And also when" : "Show only when", h("select", { onchange: e => { const v = e.target.value; if (!v) return; const f = allData().find(x => x.token === v); setRules([...rules, f && f.kind === "toggle" ? { value: v, op: "is", to: "1" } : { value: v, op: "has" }]); } },
      opts(null, "", rules.length ? "+ add another rule…" : "(always shown)"))));
    if (rules.length) kids.push(h("p", { class: "muted small" }, "The editor shows it either way. On air it plays its In and Out animations as the rule changes."));
    if (!one) kids.push(h("p", { class: "muted small" }, `${list.length} layers: their rules are set together.`));
    return sect("Live", ...kids);
  }
  function animProps(l) {
    l.anim = l.anim || { in: Object.assign({}, ANIM_NONE), out: Object.assign({}, ANIM_NONE) };
    const types = GFX.animTypes.map(t => [t, t === "none" ? "None" : t.replace(/-/g, " ").replace(/^./, c => c.toUpperCase())]);
    const part = (dir, title) => {
      const a = l.anim[dir] = l.anim[dir] || Object.assign({}, ANIM_NONE);
      return h("div", {}, h("span", { class: "muted small" }, title),
        grid(bind(a, "type", "select", { options: types }), bind(a, "dur", "number", { label: "ms", min: 0, step: 50 }), bind(a, "delay", "number", { label: "delay", min: 0, step: 50 })));
    };
    return sect("Animation", part("in", "When it comes on"), part("out", "When it goes off"));
  }
  function multiProps(list) {
    const allGroup = list.every(l => l.group && l.group === list[0].group);
    return h("div", {},
      h("div", { class: "props-head" }, h("h3", {}, allGroup ? "Group" : `${list.length} layers`), h("span", { class: "muted" }, "Drag to move them together")),
      sect(null, alignRow(list),
        h("div", { class: "row-gap" },
          allGroup ? h("button", { class: "small", onclick: ungroup }, "Ungroup") : h("button", { class: "small", onclick: group }, "Group (Ctrl+G)"),
          h("button", { class: "small", onclick: () => { copy(); paste(20); } }, "Duplicate"), h("button", { class: "small danger", onclick: remove }, "Delete"))),
      sect("Animation for all", h("div", { class: "row-gap" },
        h("select", { onchange: e => { const t = e.target.value; e.target.value = ""; if (!t) return; snapshot(); list.forEach(l => { l.anim = l.anim || {}; l.anim.in = Object.assign({}, ANIM_NONE, l.anim.in, { type: t }); l.anim.out = Object.assign({}, ANIM_NONE, l.anim.out, { type: t }); }); changed(); } },
          h("option", { value: "" }, "Set In and Out to…"), GFX.animTypes.map(t => h("option", { value: t }, t))))),
      liveProps(list));
  }
  function hudProps() {
    return h("div", {},
      h("div", { class: "props-head" }, h("h3", {}, hud.name), h("span", { class: "muted" }, games[hud.game] || "")),
      sect(null, h("p", { class: "muted" }, "Click a layer to change it. Shift or Ctrl+click picks more; drag on empty canvas to pick an area."),
        h("ul", { class: "keys muted small" },
          h("li", {}, "Drag pictures, videos, Lottie files, fonts, GFX Engine graphics (.sccgfx), Photoshop (.psd) and Figma (.fig) files in from your PC"),
          h("li", {}, "Arrow keys nudge (Shift: 10 px); Alt while dragging turns off snapping"),
          h("li", {}, "Ctrl+G groups, Ctrl+Shift+G ungroups; Alt+click picks one layer in a group"),
          h("li", {}, "Ctrl+D duplicates, Ctrl+] / Ctrl+[ bring forward / send back"),
          h("li", {}, "Ctrl+Z undo, Ctrl+Y redo"))),
      sect("Layers", h("p", { class: "muted small" }, `${hud.layers.length} layers, ${vars().length} variables.`)));
  }

  // --- variables -------------------------------------------------------------------------
  function renderVars() {
    const box = $("#ed-var-list");
    if (!hud) return box.replaceChildren();
    const values = live.values || {};
    const KIND = { text: "Aa", number: "#", toggle: "◐", color: "●", image: "🖼", choice: "≡" };
    box.replaceChildren(...(vars().length ? vars().map(v => {
      const val = values[v.name] != null ? values[v.name] : v.value;
      return h("div", { class: "vrow", draggable: true, title: "Drag onto the canvas or a layer. Click to change.",
        ondragstart: e => { e.dataTransfer.setData("text/x-hud-var", v.name); e.dataTransfer.effectAllowed = "copy"; },
        onclick: () => editVar(v) },
        h("span", { class: "vk", style: v.kind === "color" ? { color: val } : null }, KIND[v.kind] || "?"),
        h("span", { class: "vname" }, v.name), h("span", { class: "vval muted" }, v.kind === "toggle" ? (val ? "on" : "off") : String(val || "").replace(/^assets\//, "")));
    }) : [h("p", { class: "muted hint" }, "None yet. A variable is something you change during the show: a score, a team name, a colour, a picture.")]));
    $("#ed-builtins").replaceChildren(...BUILTINS.map(([t, n]) => h("div", { class: "vrow", draggable: true,
      ondragstart: e => { e.dataTransfer.setData("text/x-hud-token", t); e.dataTransfer.effectAllowed = "copy"; } },
      h("span", { class: "vk" }, "⏱"), h("span", { class: "vname" }, n))));
    renderGameData();
  }
  function editVar(v) {
    const dlg = $("#var-dlg");
    const isNew = !v;
    v = v || { name: "", kind: "text", value: "" };
    $("#var-title").textContent = isNew ? "New variable" : "Variable";
    $("#var-name").value = v.name;
    $("#var-kind").value = v.kind;
    $("#var-value").value = v.value || "";
    $("#var-step").value = v.step || 1;
    $("#var-min").value = v.min ?? "";
    $("#var-max").value = v.max ?? "";
    $("#var-options").value = (v.options || []).join("\n");
    $("#var-group").value = v.group || "";
    $("#var-delete").hidden = isNew;
    const kindShown = () => {
      const k = $("#var-kind").value;
      dlg.querySelector(".var-num").hidden = k !== "number";
      dlg.querySelector(".var-choice").hidden = k !== "choice";
      $("#var-value").placeholder = { number: "0", toggle: "1 = on, empty = off", color: "#ffffff", image: "assets/logo.png (or pick it in the control panel)" }[k] || "";
    };
    $("#var-kind").onchange = kindShown;
    kindShown();
    dlg.returnValue = "";
    dlg.onclose = () => {
      const how = dlg.returnValue;
      if (how === "delete") {
        if (!confirm(`Delete the variable ${v.name}? Layers that show it keep the link but show nothing.`)) return;
        snapshot();
        hud.vars = hud.vars.filter(x => x !== v);
        return changed({ vars: true });
      }
      if (how !== "ok") return;
      const name = $("#var-name").value.replace(/[{}!|]/g, "").trim();
      if (!name) return toast("A variable needs a name", true);
      if (hud.vars.some(x => x !== v && x.name.toLowerCase() === name.toLowerCase())) return toast(`There's already a variable called ${name}`, true);
      snapshot();
      const nv = { name, kind: $("#var-kind").value, value: $("#var-value").value };
      if (nv.kind === "number") { nv.step = +$("#var-step").value || 1; if ($("#var-min").value !== "") nv.min = $("#var-min").value; if ($("#var-max").value !== "") nv.max = $("#var-max").value; }
      if (nv.kind === "choice") nv.options = $("#var-options").value.split("\n").map(s => s.trim()).filter(Boolean);
      if ($("#var-group").value.trim()) nv.group = $("#var-group").value.trim();
      if (isNew) hud.vars.push(nv);
      else {
        // (renamed: the layers that show it follow)
        if (v.name !== name) renameToken(v.name, name);
        hud.vars[hud.vars.indexOf(v)] = nv;
      }
      changed({ vars: true });
    };
    dlg.showModal();
    setTimeout(() => $("#var-name").focus(), 30);
  }
  function renameToken(from, to) {
    const re = new RegExp(`\\{\\{\\s*HUD!${from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\}\\}`, "gi");
    const walk = o => {
      if (Array.isArray(o)) return o.map(walk);
      if (o && typeof o === "object") { for (const k of Object.keys(o)) o[k] = walk(o[k]); return o; }
      return typeof o === "string" ? o.replace(re, token(to)) : o;
    };
    hud.layers = walk(hud.layers);
  }
  $("#ed-var-add").addEventListener("click", () => hud && editVar(null));

  // --- game data (the GFX Engine: the teams, and what the game HUD sends) ----------------------
  const KIND_ICON = { text: "Aa", number: "#", toggle: "◐", color: "●", image: "🖼" };
  const strip = s => String(s || "").replace(/^(left|right) team's /, (m, side) => side[0].toUpperCase() + side.slice(1) + " ");
  const short = f => strip(f.label).replace(/^./, c => c.toUpperCase()).replace(/ \(.*\)$/, "");
  // A new layer showing it (dropped on empty canvas).
  function layerFor(f) {
    const name = short(f);
    if (f.kind === "color") return newLayer("rect", { name, fill: f.token, w: 400, h: 16 });
    if (f.kind === "image") return newLayer("image", { name, src: f.token, w: 160, h: 160 });
    if (f.kind === "toggle") return newLayer("rect", { name, fill: "#ffffff", w: 40, h: 40, when: [{ value: f.token, op: "is", to: "1" }] });
    if (f.kind === "number") return newLayer("text", { name, text: f.token, w: 160, h: 110, size: 88, align: "center", font: "Bebas Neue", weight: 400 });
    return newLayer("text", { name, text: f.token, w: 480, h: 80 });
  }
  // Link a layer to it: the text shows it, the picture is it, the shape's colour,
  // or (on / off data) the layer shows only while it's on. Returns what it did.
  function linkData(l, f, quiet) {
    snapshot();
    let did;
    if (f.kind === "toggle") {
      const rules = (Array.isArray(l.when) ? l.when : l.when ? [l.when] : []).filter(r => r.value !== f.token);
      l.when = [...rules, { value: f.token, op: "is", to: "1" }];
      did = `${l.name} shows only while ${short(f).toLowerCase()} is on`;
    } else if (f.kind === "image") {
      if (l.type !== "image" && l.type !== "video") {
        // (a placeholder shape or text becomes the picture, in the same box)
        for (const k of ["fill", "fill2", "text", "radius", "radii", "stroke", "strokeWidth", "shape", "font", "size"]) delete l[k];
        l.type = "image";
      }
      l.src = f.token;
      l.fit = l.fit && l.fit !== "fill" ? l.fit : "contain";
      did = `${l.name} shows the ${f.label}`;
    } else if (f.kind === "color") {
      if (l.type === "text") l.color = f.token;
      else if (l.type === "rect") l.fill = f.token;
      else { undo.pop(); if (!quiet) toast(`Pick a shape or text for the ${f.label}`, true); return null; }
      did = `${l.name} is coloured by the ${f.label}`;
    } else {
      if (l.type !== "text") {
        // (artwork of the text, flattened into a picture: it becomes live text in its place)
        for (const k of ["src", "fit", "loop", "fill", "fill2", "radius", "radii", "stroke", "strokeWidth", "shape", "meter"]) delete l[k];
        Object.assign(l, { type: "text", font: l.font || "Inter", size: Math.max(12, Math.round(l.h * 0.72)), color: l.color || "#ffffff",
          align: "center", valign: "middle", tracking: 0, caps: false, lineHeight: 1, fit: "shrink", weight: 700, italic: false, scroll: 0 });
      }
      l.text = f.token;
      did = `${l.name} shows the ${f.label}`;
    }
    selected.clear(); selected.add(l.id);
    changed();
    if (!quiet) toast(did);
    return did;
  }
  const linkedTo = token => hud ? hud.layers.filter(l => JSON.stringify(l).includes(token.replace(/"/g, '\\"'))) : [];
  let dataFilter = "";
  const openGroups = new Set(["Teams"]);
  function renderGameData() {
    const box = $("#ed-gamedata");
    if (!box) return;
    if (!hud) return box.replaceChildren();
    const status = document.body.classList.contains("embedded") ? `Live from ${engine.name || "this HUD"}` : engine.connected
      ? (engine.feeds.includes(gd.source) || !gd.source ? `Live from ${engine.name || "the GFX Engine"}` : `GFX Engine connected; ${gd.source} isn't sending yet (showing examples)`)
      : "No GFX Engine: showing examples (Settings > GFX Engine)";
    const q = dataFilter.trim().toLowerCase();
    const groups = gd.catalog.map(g => {
      const fields = g.fields.filter(f => !q || (f.label + " " + f.field + " " + g.group).toLowerCase().includes(q));
      if (!fields.length) return null;
      const det = h("details", { class: "dgroup", open: !!q || openGroups.has(g.group),
        ontoggle: e => { if (e.target.open) openGroups.add(g.group); else openGroups.delete(g.group); } },
        h("summary", {}, g.group, h("span", { class: "muted small" }, g.table === "Global" && !document.body.classList.contains("embedded") ? " · GFX Engine" : "")),
        fields.map(f => h("div", { class: "vrow", draggable: true, title: `${f.token}\nDrag onto the canvas or onto a layer, or pick a layer and click this.`,
          ondragstart: e => { e.dataTransfer.setData("text/x-hud-data", f.token); e.dataTransfer.effectAllowed = "copy"; },
          onclick: () => { const one = sel(); if (one.length === 1) linkData(one[0], f); else toast("Drag it onto the canvas, or pick a layer first and click it"); } },
          h("span", { class: "vk" }, KIND_ICON[f.kind] || "?"), h("span", { class: "vname" }, short(f)),
          linkedTo(f.token).length ? h("span", { class: "vval linked", title: "A layer shows this" }, "✓") : null)));
      return det;
    }).filter(Boolean);
    box.replaceChildren(
      h("p", { class: "hint muted" + (engine.connected ? " live" : "") }, status),
      h("div", { class: "row-gap data-tools" },
        h("input", { type: "search", placeholder: "Find…", value: dataFilter, oninput: e => { dataFilter = e.target.value; renderGameData(); const i = $("#ed-gamedata input[type=search]"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }),
        h("button", { class: "small", title: "Go through the design one piece of game data at a time", onclick: () => window.Guide && Guide.start() }, "Setup guide")),
      ...groups);
  }

  function renderAll() {
    renderLayers();
    renderProps();
    renderVars();
    drawSelection();
  }

  return {
    open, liveUpdate, liveData, flush, fit: fitStage, importDesign,
    get hud() { return hud; },
    get catalog() { return gd.catalog; },
    get engine() { return engine; },
    linkData, linkedTo, short,
    setGame(game) { if (!hud) return; snapshot(); hud.game = game; $("#ed-game").value = game; changed(); return loadGameData(); },
    setPicker(fn) { picker = fn; canvas.classList.toggle("picking", !!fn); },
    focusLayer(id) { selected.clear(); if (id) selected.add(id); renderAll(); },
    unlink(layerJson) { const old = JSON.parse(layerJson); const i = hud.layers.findIndex(l => l.id === old.id); if (i < 0) return; snapshot(); hud.layers[i] = old; changed(); },
    get id() { return hud && hud.id; },
    close() { flush(); if (root) { GFX.destroy(root); root.remove(); root = null; } hud = null; selected.clear(); renderAll(); },
  };
})();
