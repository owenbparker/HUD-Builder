// Small helpers shared by HUD Builder's pages: making elements, talking to
// the app, and a toast for what happened.
"use strict";

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => [...(root || document).querySelectorAll(sel)];

// h("div", {class: "x", onclick: fn, style: {left: "4px"}}, child, "text", [more])
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k in e && typeof v !== "string") e[k] = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  const add = c => {
    if (c == null || c === false) return;
    if (Array.isArray(c)) c.forEach(add);
    else e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  };
  kids.forEach(add);
  return e;
}

async function api(path, body, raw) {
  const opts = body === undefined ? {} : raw
    ? { method: "POST", body, headers: { "Content-Type": "application/octet-stream" } }
    : { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } };
  const r = await fetch(path, Object.assign({ cache: "no-store" }, opts));
  let data;
  try { data = await r.json(); } catch (e) { throw new Error(`The app didn't answer (${r.status})`); }
  if (!r.ok || data.error) throw new Error(data.error || `Error ${r.status}`);
  return data;
}

let toastTimer = null;
function toast(text, error, ms) {
  let t = $("#toast");
  if (!t) { t = h("div", { id: "toast", role: "status" }); document.body.appendChild(t); }
  t.textContent = text;
  t.className = error ? "show error" : "show";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ""; }, ms || (error ? 6000 : Math.max(2200, text.length * 45)));
}

// A file from the user's PC as an ArrayBuffer.
const readFile = file => new Promise((ok, fail) => {
  const r = new FileReader();
  r.onload = () => ok(r.result);
  r.onerror = () => fail(r.error);
  r.readAsArrayBuffer(file);
});

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) {
    const t = h("textarea", { style: { position: "fixed", opacity: 0 } }, text);
    document.body.appendChild(t); t.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    t.remove();
    return ok;
  }
}

const token = name => `{{HUD!${name}}}`;
const tokenName = v => { const m = /^\s*\{\{\s*HUD!([^{}]+?)\s*\}\}\s*$/i.exec(String(v || "")); return m ? m[1] : null; };

// A 1920x1080 page (the HUD) shrunk to fit its box.
const frameFitter = new ResizeObserver(entries => {
  for (const e of entries) {
    const f = e.target.querySelector("iframe");
    if (f) f.style.transform = `scale(${e.contentRect.width / 1920})`;
  }
});
const fitFrame = box => { frameFitter.observe(box); return box; };
