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
      renderUpdate(state.app.update);
      renderHuds();
      renderSettings();
    } catch (e) { toast(e.message, true); }
  }

  // --- pages ---------------------------------------------------------------------
  const HUD_PAGES = ["design", "control", "live"];
  function show(page) {
    if (HUD_PAGES.includes(page) && !current) page = "huds";
    if (!$(`.page[data-page="${page}"]`)) page = "huds";
    if (document.body.dataset.page === "design" && page !== "design") Editor.flush();
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
    const key = JSON.stringify([current, huds.map(s => [s.id, s.name, s.game, s.layers, s.vars])]);
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
      fitFrame(h("div", { class: "thumb checker" }, h("iframe", { src: `/hud/${s.id}?anim=0`, tabindex: -1, title: s.name, loading: "lazy" }))),
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
    $("#new-template").replaceChildren(...Object.entries(state.templates).map(([k, t]) => h("option", { value: k }, t)));
    dlg.returnValue = "";
    dlg.onclose = async () => {
      if (dlg.returnValue !== "ok") return;
      try {
        const r = await api("/api/huds", { name: $("#new-name").value, game: $("#new-game").value, template: $("#new-template").value });
        state = r.state;
        renderHuds();
        openHud(r.hud.id, "design");
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
      const r = await api("/api/import", await readFile(f), true);
      state = r.state;
      renderHuds();
      toast(`Imported ${r.hud.name}`);
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
    $("#set-network").checked = !!state.app.network;
    $("#set-lan").textContent = state.app.lan_url ? `Other PCs use ${state.app.lan_url}` : "";
    $("#set-dir").textContent = state.app.data_dir;
    if (document.body.dataset.page === "live") renderLive();
  }
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
