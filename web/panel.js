// A HUD's control panel, made from its variables: a box for each text, - / +
// for numbers, a switch for each toggle, colour and picture pickers, and Show /
// Hide for the whole HUD. Used in the app and on /control/<id> (any PC).
"use strict";

window.Panel = (function () {
  function render(box, hud, opts) {
    opts = opts || {};
    const values = hud.values || {};
    const valueOf = v => (values[v.name] != null ? values[v.name] : v.value) || "";
    const set = async (name, value) => {
      try { opts.onChange && opts.onChange(await api(`/api/huds/${hud.id}/values`, { values: { [name]: value } })); }
      catch (e) { toast(e.message, true); }
    };
    const head = h("div", { class: "panel-top" },
      h("div", { class: "onair " + (hud.shown === false ? "off" : "on") }, hud.shown === false ? "Off air" : "On air"),
      h("button", { class: hud.shown === false ? "primary" : "", onclick: async () => {
        try { opts.onChange && opts.onChange(await api(`/api/huds/${hud.id}/shown`, { shown: hud.shown === false })); } catch (e) { toast(e.message, true); }
      } }, hud.shown === false ? "Show HUD" : "Hide HUD"),
      h("span", { class: "grow" }),
      h("button", { class: "ghost", title: "Every variable back to its starting value", onclick: async () => {
        if (!confirm("Put every variable back to its starting value?")) return;
        try { opts.onChange && opts.onChange(await api(`/api/huds/${hud.id}/reset`, {})); } catch (e) { toast(e.message, true); }
      } }, "Reset values"));
    const vars = hud.vars || [];
    if (!vars.length) {
      box.replaceChildren(head, h("p", { class: "muted empty" },
        "This HUD has no variables yet. Add them in the editor's Data panel (the + next to Variables), and they appear here to run the HUD."));
      return;
    }
    const groups = new Map();
    for (const v of vars) {
      const g = v.group || "Variables";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(v);
    }
    const cards = [];
    for (const [g, list] of groups) {
      cards.push(h("div", { class: "pcard" }, h("h3", {}, g), list.map(v => row(v, valueOf(v), set, hud, opts))));
    }
    box.replaceChildren(head, h("div", { class: "pcards" }, cards));
  }

  function row(v, value, set, hud, opts) {
    const label = h("label", { class: "pname" }, v.name);
    let ctl;
    if (v.kind === "number") {
      const step = +v.step || 1;
      const clamp = n => { if (v.min !== undefined && v.min !== "" && n < +v.min) n = +v.min; if (v.max !== undefined && v.max !== "" && n > +v.max) n = +v.max; return n; };
      const input = h("input", { type: "number", value, step, onchange: e => set(v.name, e.target.value) });
      const bump = d => () => { const n = clamp((parseFloat(input.value) || 0) + d * step); input.value = String(+n.toFixed(4)); set(v.name, input.value); };
      ctl = h("div", { class: "num" }, h("button", { class: "big", onclick: bump(-1), "aria-label": "Less" }, "−"), input,
        h("button", { class: "big", onclick: bump(1), "aria-label": "More" }, "+"));
    } else if (v.kind === "toggle") {
      const on = ["1", "true", "yes", "on"].includes(String(value).toLowerCase());
      ctl = h("button", { class: "switch" + (on ? " on" : ""), role: "switch", "aria-checked": String(on), onclick: () => set(v.name, on ? "" : "1") },
        h("span", {}), on ? "On" : "Off");
    } else if (v.kind === "color") {
      ctl = h("div", { class: "colour" }, h("input", { type: "color", value: /^#[0-9a-f]{6}$/i.test(value) ? value : "#ffffff",
        onchange: e => set(v.name, e.target.value) }), h("code", {}, value));
    } else if (v.kind === "choice") {
      ctl = h("select", { onchange: e => set(v.name, e.target.value) },
        (v.options || []).map(o => h("option", { value: o, selected: o === value }, o)),
        value && !(v.options || []).includes(value) ? h("option", { value, selected: true }, value) : null);
    } else if (v.kind === "image") {
      const assets = (hud.assets || []).filter(a => /\.(png|jpe?g|webp|gif|svg)$/i.test(a));
      const file = h("input", { type: "file", accept: "image/*", hidden: true, onchange: async e => {
        const f = e.target.files[0];
        if (!f) return;
        try {
          const r = await api(`/api/huds/${hud.id}/asset?name=${encodeURIComponent(f.name)}`, await readFile(f), true);
          set(v.name, r.path);
        } catch (err) { toast(err.message, true); }
      } });
      ctl = h("div", { class: "pic" },
        value ? h("img", { src: `/huds/${hud.id}/${encodeURI(value)}`, alt: "" }) : h("span", { class: "nopic" }),
        h("select", { onchange: e => set(v.name, e.target.value) }, h("option", { value: "" }, "(none)"),
          assets.map(a => h("option", { value: a, selected: a === value }, a.replace(/^assets\//, ""))),
          value && !assets.includes(value) ? h("option", { value, selected: true }, value) : null),
        opts.local === false ? null : h("button", { onclick: () => file.click() }, "Upload…"), file);
    } else {
      const input = h("input", { type: "text", value, onkeydown: e => { if (e.key === "Enter") e.target.blur(); } });
      input.addEventListener("change", () => set(v.name, input.value));
      ctl = input;
    }
    return h("div", { class: "prow k-" + v.kind }, label, ctl);
  }

  return { render };
})();
