// HUD Builder's app: the sidebar pages (My HUDs, and for the open HUD its
// Design, Control panel and Go live), settings, and keeping the open HUD live.
"use strict";

window.App = (function () {
  let state = null;          // /api/state
  let current = null;        // the open HUD's id
  let hudLive = null;        // its latest payload (from the stream)
  let source = null;
  const renderUpdate = updateButton($("#update"), $("#version"));

  async function refresh() {
    try {
      state = await api("/api/state");
      if (state.embed) embedded();
      else renderUpdate(state.app.update);
      renderHuds();
      renderSettings();
    } catch (e) { toast(e.message, true); }
  }

  // Built into a game HUD app: its game only, its own data (no GFX Engine), its updates.
  function embedded() {
    document.body.classList.add("embedded");
    $("#update").hidden = true;
    $("#version").textContent = `In ${state.embed.title}`;
    $(".brand-sub") && ($(".brand-sub").textContent = state.embed.title);
    document.title = `Custom design · ${state.embed.title}`;
  }

  // --- pages ---------------------------------------------------------------------
  const HUD_PAGES = ["design", "control", "live"];
  function show(page) {
    if (HUD_PAGES.includes(page) && !current) page = "huds";
    if (!$(`.page[data-page="${page}"]`)) page = "huds";
    const leaving = document.body.dataset.page;
    if (leaving === "design" && page !== "design") Editor.flush();
    // (My HUDs' pictures are read once, so read them again after an edit)
    if (page === "huds" && leaving && leaving !== "huds") Promise.resolve(Editor.flush()).then(refresh);
    document.body.dataset.page = page;
    $$(".page").forEach(p => { p.hidden = p.dataset.page !== page; });
    $$("#side .nav").forEach(a => a.classList.toggle("on", a.dataset.page === page));
    if (page === "design") requestAnimationFrame(() => Editor.fit());
    if (page === "control") renderControl();
    if (page === "live") renderLive();
    if (page === "settings") pollLog();
  }
  function route() { show(location.hash.replace(/^#\/?/, "") || "huds"); }
  addEventListener("hashchange", route);
  const go = page => { if (location.hash === "#/" + page) route(); else location.hash = "#/" + page; };

  // --- My HUDs ---------------------------------------------------------------------
  let gridKey = "";
  function renderHuds() {
    const grid = $("#hud-grid");
    const huds = state.huds || [];
    // (only when something on the cards changed: the previews are live pages)
    const key = JSON.stringify([current, huds.map(s => [s.id, s.name, s.game, s.layers, s.vars, s.updated])]);
    if (key === gridKey) return;
    gridKey = key;
    if (!huds.length) {
      grid.replaceChildren(h("div", { class: "empty-state" },
        h("h3", {}, "Make your first HUD"),
        h("p", { class: "muted" }, "Draw shapes, drop in pictures and add variables you change during the show. Then add it to OBS or vMix as a browser source."),
        h("button", { class: "primary", onclick: newHud }, "New HUD")));
      return;
    }
    grid.replaceChildren(...huds.map(s => h("div", { class: "hud-card" + (s.id === current ? " open" : ""), onclick: () => openHud(s.id, "design") },
      fitFrame(h("div", { class: "thumb checker" }, h("iframe", { src: `/hud/${s.id}?anim=0&still=1`, tabindex: -1, title: s.name, loading: "lazy" }))),
      h("div", { class: "hud-meta" },
        h("b", {}, s.name),
        h("span", { class: "muted small" }, `${state.games[s.game] || "Other game"} · ${s.layers} layers · ${s.vars} variables`)),
      h("div", { class: "hud-btns", onclick: e => e.stopPropagation() },
        h("button", { class: "small", onclick: () => openHud(s.id, "design") }, "Design"),
        h("button", { class: "small", onclick: () => openHud(s.id, "control") }, "Control"),
        h("button", { class: "small ghost", title: "Make a copy", onclick: async () => { try { const r = await api(`/api/huds/${s.id}/duplicate`, {}); state = r.state; renderHuds(); toast("Copied"); } catch (e) { toast(e.message, true); } } }, "Copy"),
        h("button", { class: "small ghost danger", onclick: async () => {
          if (!confirm(`Delete ${s.name}? Its pictures go with it. This can't be undone (Export it first to keep a copy).`)) return;
          try { state = await api(`/api/huds/${s.id}/delete`, {}); if (current === s.id) closeHud(); renderHuds(); } catch (e) { toast(e.message, true); }
        } }, "Delete")))));
  }
  function newHud() {
    const dlg = $("#new-dlg");
    $("#new-name").value = "";
    $("#new-game").replaceChildren(...Object.entries(state.games).map(([k, t]) => h("option", { value: k }, t)));
    if (state.embed) $("#new-game").value = state.embed.game;
    $("#new-game").disabled = !!state.embed;
    $("#new-template").replaceChildren(...Object.entries(state.templates).map(([k, t]) => h("option", { value: k }, t)),
      h("option", { value: "file" }, "My own design (.psd, .fig, .sccgfx)…"));
    $("#new-file").value = "";
    const fileShown = () => { const on = $("#new-template").value === "file"; $("#new-file-row").hidden = !on; $("#new-file-hint").hidden = !on; $("#new-file").required = on; };
    $("#new-template").onchange = fileShown;
    fileShown();
    dlg.returnValue = "";
    dlg.onclose = async () => {
      if (dlg.returnValue !== "ok") return;
      try {
        const file = $("#new-template").value === "file" ? $("#new-file").files[0] : null;
        const r = await api("/api/huds", { name: $("#new-name").value, game: $("#new-game").value, template: file ? "blank" : $("#new-template").value });
        state = r.state;
        renderHuds();
        await openHud(r.hud.id, "design");
        if (file) await Editor.importDesign(file);
      } catch (e) { toast(e.message, true); }
    };
    dlg.showModal();
  }
  $("#new-btn").addEventListener("click", newHud);
  $("#import-btn").addEventListener("click", () => $("#import-file").click());
  $("#import-file").addEventListener("change", async e => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      const r = await api(`/api/import?name=${encodeURIComponent(f.name)}`, await readFile(f), true);
      state = r.state;
      renderHuds();
      let msg = `Imported ${r.hud.name}.`;
      if (r.notes && r.notes.length) msg += " " + r.notes.join(". ") + ".";
      if (r.fonts_missing && r.fonts_missing.length) msg += ` Fonts to add (Design > Text > Add font…): ${r.fonts_missing.join(", ")}.`;
      toast(msg, false, msg.length > 60 ? 9000 : 0);
      // A design (not a whole HUD): open it and walk through linking it to the game's data.
      if (!/\.scchud$/i.test(f.name)) { await openHud(r.hud.id, "design"); if (window.Guide) Guide.start({ fresh: true }); }
    } catch (err) { toast(err.message, true); }
  });

  // --- the open HUD ------------------------------------------------------------------
  async function openHud(id, page) {
    try {
      if (current && current !== id) await Editor.flush();
      const payload = await api(`/api/huds/${id}`);
      current = id;
      hudLive = payload;
      Editor.open(payload, state.games);
      $("#nav-hud").hidden = false;
      $("#nav-hud-name").textContent = payload.name;
      follow(id);
      renderHuds();
      go(page || "design");
    } catch (e) { toast(e.message, true); }
  }
  function closeHud() {
    current = null; hudLive = null;
    if (source) { source.close(); source = null; }
    Editor.close();
    $("#nav-hud").hidden = true;
    go("huds");
  }
  function follow(id) {
    if (source) source.close();
    source = new EventSource(`/api/huds/${id}/stream`);
    source.onmessage = e => {
      let p;
      try { p = JSON.parse(e.data); } catch (err) { return; }
      if (p.gone) return closeHud();
      if (p.id !== current) return;
      if (p.data_only) {
        // (the game moved on: just the data)
        if (hudLive) hudLive = Object.assign({}, hudLive, { tables: p.tables, engine: p.engine });
        return Editor.liveData(p);
      }
      hudLive = p;
      $("#nav-hud-name").textContent = p.name;
      Editor.liveUpdate(p);
      if (document.body.dataset.page === "control") renderControl();
    };
  }

  // --- control panel and Go live ------------------------------------------------------------
  function renderControl() {
    if (!hudLive) return;
    const a = document.activeElement;
    if (a && a.tagName === "INPUT" && a.type === "text" && $("#ctl-panel").contains(a)) return;   // (not while typing)
    Panel.render($("#ctl-panel"), hudLive, { onChange: p => { hudLive = p; renderControl(); } });
    const f = $("#ctl-frame"), src = `/hud/${hudLive.id}`;
    if (f.getAttribute("src") !== src) f.setAttribute("src", src);
  }
  $("#ctl-pop").addEventListener("click", () => current && window.open(`/control/${current}`, "_blank"));
  const baseUrl = () => `http://localhost:${state.app.port}`;
  function renderLive() {
    if (!current || !state) return;
    $("#live-url").textContent = `${baseUrl()}/hud/${current}`;
    const lan = state.app.lan_url;
    $("#live-lan-row").hidden = !lan;
    $("#live-lan-note").hidden = !!lan;
    if (lan) $("#live-lan").textContent = `${lan}/hud/${current}`;
    $("#live-ctl").textContent = `${lan || baseUrl()}/control/${current}`;
  }
  const copyBtn = (btn, el) => $(btn).addEventListener("click", async () => toast(await copyText($(el).textContent) ? "Copied" : "Couldn't copy: select it and press Ctrl+C", false));
  copyBtn("#live-copy", "#live-url");
  copyBtn("#live-lan-copy", "#live-lan");
  copyBtn("#live-ctl-copy", "#live-ctl");
  $("#live-export").addEventListener("click", async () => {
    if (!current) return;
    await Editor.flush();
    location.href = `/api/huds/${current}/export`;
  });

  // --- settings ------------------------------------------------------------------------------
  function renderSettings() {
    const eng = state.app.engine || {};
    const inp = $("#set-engine");
    if (document.activeElement !== inp) inp.value = eng.setting || "";
    const st = $("#set-engine-status");
    st.textContent = eng.connected ? `● Connected to ${eng.name || "the GFX Engine"} at ${eng.url}` + (Object.keys(eng.feeds || {}).length ? `. Game HUDs sending: ${Object.keys(eng.feeds).join(", ")}` : ". No game HUD is sending to it yet.")
      : (eng.error || "Not connected");
    st.className = "small " + (eng.connected ? "ok" : "muted");
    $("#set-network").checked = !!state.app.network;
    $("#set-lan").textContent = state.app.lan_url ? `Other PCs use ${state.app.lan_url}` : "";
    $("#set-dir").textContent = state.app.data_dir;
    if (document.body.dataset.page === "live") renderLive();
  }
  $("#set-engine-save").addEventListener("click", async () => {
    const b = $("#set-engine-save");
    b.disabled = true;
    try { state = await api("/api/engine", { url: $("#set-engine").value }); renderSettings(); } catch (err) { toast(err.message, true); }
    b.disabled = false;
  });
  setInterval(() => { if (document.body.dataset.page === "settings") refresh(); }, 4000);
  $("#set-network").addEventListener("change", async e => {
    try { state = await api("/api/network", { on: e.target.checked }); renderSettings(); } catch (err) { toast(err.message, true); }
  });
  let logAfter = 0, logTimer = null;
  async function pollLog() {
    clearTimeout(logTimer);
    try {
      const r = await api(`/api/log?after=${logAfter}`);
      const pre = $("#log");
      for (const l of r.lines) { pre.textContent += `[${l.time}] ${l.message}\n`; logAfter = l.id; }
      pre.scrollTop = pre.scrollHeight;
    } catch (e) { /* the app is restarting */ }
    if (document.body.dataset.page === "settings") logTimer = setTimeout(pollLog, 2000);
  }
  if (window.Appearance) Appearance.render($("#appearance-box"));
  fitFrame($(".mini-out"));

  // The editor tells us when the HUD's name changes.
  function renamed(id, name) {
    if (id === current) $("#nav-hud-name").textContent = name;
    const s = state && state.huds.find(x => x.id === id);
    if (s && s.name !== name) { s.name = name; renderHuds(); }
  }

  // Start: the HUD that was open last time, if it's still there.
  (async () => {
    await refresh();
    let last = null;
    try { last = localStorage.getItem("hb-open"); } catch (e) { /* */ }
    const page = location.hash.replace(/^#\/?/, "");
    if (last && state.huds.some(x => x.id === last)) await openHud(last, HUD_PAGES.includes(page) ? page : "huds");
    route();
    setInterval(refresh, 30000);
  })();
  addEventListener("beforeunload", () => { Editor.flush(); });
  const remember = () => { try { if (current) localStorage.setItem("hb-open", current); } catch (e) { /* */ } };
  setInterval(remember, 2000);

  return { renamed, refresh };
})();
