// A PromQL editor: a textarea over a highlighted copy of its text, with completion of metric
// names and functions, label names inside {…} and by (…), and label values after = != =~ !~.
// Enter runs the query; Shift+Enter adds a line; Ctrl+Space asks for suggestions.
const PromEditor = (() => {
  const FUNCS = ["rate", "irate", "increase", "delta", "idelta", "sum", "avg", "min", "max", "count", "topk", "bottomk", "quantile",
    "stddev", "count_values", "histogram_quantile", "avg_over_time", "min_over_time", "max_over_time", "sum_over_time",
    "count_over_time", "last_over_time", "quantile_over_time", "abs", "ceil", "floor", "round", "clamp_min", "clamp_max",
    "label_replace", "label_join", "absent", "changes", "resets", "deriv", "predict_linear", "time", "vector", "scalar", "sort", "sort_desc"];
  const KEYWORDS = new Set(["by", "without", "on", "ignoring", "group_left", "group_right", "offset", "bool", "and", "or", "unless"]);
  const FUNCSET = new Set(FUNCS);
  const TOK = /(#[^\n]*)|("(?:[^"\\\n]|\\.)*"?|'(?:[^'\\\n]|\\.)*'?)|(\[[^\]\n]*\]?)|(\d+(?:\.\d+)?(?:e[+-]?\d+)?(?![\w]))|([a-zA-Z_:][\w:]*)|(=~|!~|!=|==|>=|<=|[-+*/%^=<>{}(),])|(\s+)|(.)/gy;

  // classify every token, tracking whether we are inside {…} or a by/without (…) list
  function tokens(text) {
    const out = [];
    let brace = 0, grp = 0, depth = 0, pendingGrp = false;
    TOK.lastIndex = 0;
    let m;
    while (TOK.lastIndex < text.length && (m = TOK.exec(text))) {
      const s = m[0];
      let c = "";
      if (m[1]) c = "cm";
      else if (m[2]) c = "str";
      else if (m[3]) c = "dur";
      else if (m[4]) c = "num";
      else if (m[5]) {
        const callsNext = /^\s*(\(|by\b|without\b)/.test(text.slice(TOK.lastIndex));
        if (brace || grp) c = "lbl";
        else if (KEYWORDS.has(s)) { c = "kw"; if (s === "by" || s === "without") pendingGrp = true; }
        else if (FUNCSET.has(s) && callsNext) c = "fn";
        else c = "met";
      } else if (m[6]) {
        c = "op";
        if (s === "{") brace++;
        else if (s === "}") brace = Math.max(0, brace - 1);
        else if (s === "(") { depth++; if (pendingGrp) { grp = depth; pendingGrp = false; } }
        else if (s === ")") { if (grp === depth) grp = 0; depth = Math.max(0, depth - 1); }
      }
      out.push([c, s]);
    }
    return out;
  }
  const escH = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const highlight = (text) => tokens(text).map(([c, s]) => (c ? `<span class="pq-${c}">${escH(s)}</span>` : escH(s))).join("") + "\n";

  // what to suggest at the caret
  function context(text, pos) {
    const before = text.slice(0, pos);
    // inside quotes? find the innermost unclosed { and ( outside strings
    let inStr = null, braceAt = -1, parens = [];
    for (let i = 0; i < before.length; i++) {
      const ch = before[i];
      if (inStr) { if (ch === "\\") i++; else if (ch === inStr) inStr = null; continue; }
      if (ch === '"' || ch === "'") inStr = ch;
      else if (ch === "{") braceAt = i;
      else if (ch === "}") braceAt = -1;
      else if (ch === "(") parens.push(i);
      else if (ch === ")") parens.pop();
    }
    if (braceAt >= 0) {
      const metric = (before.slice(0, braceAt).match(/([a-zA-Z_:][\w:]*)\s*$/) || [])[1] || null;
      const inner = before.slice(braceAt + 1);
      const seg = splitTop(inner).pop();
      const used = splitTop(inner).slice(0, -1).map((p) => (p.match(/^\s*(\w+)/) || [])[1]).filter(Boolean);
      let m = seg.match(/^\s*(\w+)\s*(=~|!~|!=|=)\s*(["']?)([^"']*)$/);
      if (m) return { kind: "value", metric, label: m[1], prefix: m[4], from: pos - m[3].length - m[4].length, quoted: !!m[3] };
      m = seg.match(/^\s*(\w*)$/);
      if (m) return { kind: "label", metric, used, prefix: m[1], from: pos - m[1].length };
      return null;
    }
    if (inStr) return null;
    if (parens.length) {
      const open = parens[parens.length - 1];
      if (/\b(by|without|on|ignoring|group_left|group_right)\s*$/.test(before.slice(0, open))) {
        const m = before.slice(open + 1).match(/(?:^|,)\s*(\w*)$/);
        if (m) return { kind: "label", metric: null, used: [], prefix: m[1], from: pos - m[1].length, all: text };
      }
    }
    if (/\[[^\]]*$/.test(before)) return null;
    const m = before.match(/([a-zA-Z_:][\w:]*)$/);
    if (m) return { kind: "name", prefix: m[1], from: pos - m[1].length };
    return null;
  }
  // where the value being replaced ends: the rest of a quoted value up to its closing quote, if
  // that quote comes before anything that can't be in a typed value; else the rest of a bare word
  function valueEnd(v, pos, quote) {
    if (quote) {
      const close = v.indexOf(quote, pos);
      const stop = v.slice(pos).search(/[\n,{}()\[\]]/);
      if (close >= 0 && (stop < 0 || close < pos + stop)) return close + 1;
    }
    let end = pos;
    while (end < v.length && /[\w:.>-]/.test(v[end])) end++;
    return end;
  }
  // is the { open before pos closed later, before the selector ends?
  function braceClosed(v, pos) {
    let q = null;
    for (let i = pos; i < v.length; i++) {
      const ch = v[i];
      if (q) { if (ch === "\\") i++; else if (ch === q) q = null; continue; }
      if (ch === '"' || ch === "'") q = ch;
      else if (ch === "}") return true;
      else if ("{[()\n".includes(ch)) return false;
    }
    return false;
  }
  // split "a=\"x,y\", b" on top-level commas
  function splitTop(s) {
    const parts = [""];
    let q = null;
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if (q) { if (ch === "\\") { parts[parts.length - 1] += ch + (s[i + 1] || ""); i++; continue; } if (ch === q) q = null; }
      else if (ch === '"' || ch === "'") q = ch;
      else if (ch === ",") { parts.push(""); continue; }
      parts[parts.length - 1] += ch;
    }
    return parts;
  }

  function create(host, { onRun, catalog, placeholder = "" }) {
    host.classList.add("pq");
    host.innerHTML = `<pre class="pq-hl" aria-hidden="true"></pre><textarea class="pq-in" spellcheck="false" autocomplete="off" autocapitalize="off" wrap="off" rows="3" placeholder="${escH(placeholder)}"></textarea><div class="pq-ac" role="listbox"></div>`;
    const ta = host.querySelector("textarea"), hl = host.querySelector("pre"), ac = host.querySelector(".pq-ac");
    let items = [], sel = 0, ctx = null;

    const metrics = () => (catalog() || {}).metrics || [];
    const labelsOf = (metric) => {
      const ms = metric ? metrics().filter((m) => m.name === metric) : metrics();
      const out = new Map();
      for (const m of ms) for (const [k, v] of Object.entries(m.labels)) if (k !== "project") {
        const cur = out.get(k) || new Set(); v.values.forEach((x) => cur.add(x)); out.set(k, cur);
      }
      return out;
    };
    const metricsIn = (text) => metrics().map((m) => m.name).filter((n) => new RegExp(`\\b${n}\\b`).test(text));

    function sync() {
      hl.innerHTML = highlight(ta.value);
      const lines = ta.value.split("\n").length;
      ta.rows = Math.max(3, Math.min(12, lines));
      hl.scrollTop = ta.scrollTop; hl.scrollLeft = ta.scrollLeft;
    }
    function suggest(force) {
      ctx = context(ta.value, ta.selectionStart);
      items = [];
      if (ctx && ctx.kind === "label") {
        let labs;
        if (ctx.all) { labs = new Map(); for (const n of metricsIn(ctx.all)) for (const [k, v] of labelsOf(n)) labs.set(k, v); if (!labs.size) labs = labelsOf(null); }
        else labs = labelsOf(ctx.metric);
        items = [...labs.entries()].filter(([k]) => !(ctx.used || []).includes(k) && k.startsWith(ctx.prefix))
          .map(([k, v]) => ({ text: k, insert: ctx.all ? k : k + "=", note: `${v.size} value${v.size === 1 ? "" : "s"}`, cls: "lbl", again: !ctx.all }));
      } else if (ctx && ctx.kind === "value") {
        const vals = [...(labelsOf(ctx.metric).get(ctx.label) || [])];
        const p = ctx.prefix.toLowerCase();
        items = vals.filter((v) => v.toLowerCase().includes(p)).sort((a, b) => (a.toLowerCase().startsWith(p) ? 0 : 1) - (b.toLowerCase().startsWith(p) ? 0 : 1) || a.localeCompare(b))
          .map((v) => ({ text: v, insert: `"${v}"`, cls: "str", value: true }));
      } else if (ctx && ctx.kind === "name" && (force || ctx.prefix.length >= 1)) {
        const p = ctx.prefix.toLowerCase();
        const ms = metrics().filter((m) => m.name.toLowerCase().includes(p)).map((m) => ({ text: m.name, insert: m.name, note: `${m.series} series`, cls: "met" }));
        const fs = FUNCS.filter((f) => f.startsWith(p)).map((f) => ({ text: f, insert: f + "(", note: "function", cls: "fn" }));
        items = [...ms, ...fs];
        if (items.length === 1 && items[0].text === ctx.prefix) items = [];
      }
      items = items.slice(0, 60);
      if (!items.length && ctx && ctx.kind === "label" && !ctx.prefix)
        items = [{ text: ctx.metric ? `no other labels on ${ctx.metric}` : "no labels known", cls: "note", info: true }];
      else if (!items.length && ctx && ctx.kind === "value" && !ctx.prefix)
        items = [{ text: `no known values for ${ctx.label}`, cls: "note", info: true }];
      sel = 0;
      render();
    }
    function render() {
      if (!items.length) { ac.style.display = "none"; return; }
      ac.innerHTML = items.map((it, i) => `<div class="pq-it ${i === sel ? "on" : ""}" data-i="${i}"><span class="pq-${it.cls}">${escH(it.text)}</span>${it.note ? `<span class="pq-note">${escH(it.note)}</span>` : ""}</div>`).join("");
      // place it under the caret: monospace, so line and column give the position
      const before = ta.value.slice(0, ctx.from), line = before.split("\n").length - 1, col = before.length - before.lastIndexOf("\n") - 1;
      const cs = getComputedStyle(ta), cw = charWidth(cs), lh = parseFloat(cs.lineHeight);
      const left = parseFloat(cs.paddingLeft) + col * cw - ta.scrollLeft, top = parseFloat(cs.paddingTop) + (line + 1) * lh - ta.scrollTop + 2;
      ac.style.display = "block";
      ac.style.left = Math.max(0, Math.min(host.clientWidth - ac.offsetWidth, left)) + "px";
      ac.style.top = top + "px";
      ac.querySelector(".on")?.scrollIntoView({ block: "nearest" });
    }
    let cwCache = null;
    function charWidth(cs) {
      if (cwCache) return cwCache;
      const c = document.createElement("canvas").getContext("2d"); c.font = `${cs.fontSize} ${cs.fontFamily}`;
      return (cwCache = c.measureText("0000000000").width / 10);
    }
    function accept(i) {
      const it = items[i];
      if (!it || it.info) return;
      const v = ta.value, pos = ta.selectionStart;
      let end = pos, insert = it.insert;
      if (it.value) {
        end = valueEnd(v, pos, ctx.quoted ? v[ctx.from] : null);
        // the matcher list was left open: close it, unless more matchers or a } follow
        if (!/^\s*[,}]/.test(v.slice(end)) && !braceClosed(v, end)) insert += "}";
      } else while (end < v.length && /[\w:]/.test(v[end])) end++;
      const caret = ctx.from + it.insert.length;
      edit(ctx.from, end, insert, caret);
      if (it.again) suggest(true); else { items = []; render(); }
      ta.focus();
    }
    const PAIRS = { "{": "}", "(": ")", "[": "]" };

    // undo and redo: the editor's own history, since its programmatic edits bypass the browser's
    const past = [], future = [];
    let lastKind = "", lastAt = 0;
    const snap = () => ({ v: ta.value, a: ta.selectionStart, b: ta.selectionEnd });
    function record(kind) {
      const now = Date.now();
      // a run of typing (or of deleting) with no pause over a second is one step
      if (kind && kind === lastKind && now - lastAt < 1000 && past.length) { lastAt = now; return; }
      past.push(snap());
      if (past.length > 200) past.shift();
      future.length = 0;
      lastKind = kind; lastAt = now;
    }
    function restore(from, to) {
      if (!from.length) return;
      to.push(snap());
      const s0 = from.pop();
      ta.value = s0.v; ta.setSelectionRange(s0.a, s0.b);
      lastKind = ""; items = []; render(); sync();
    }
    function edit(a, b, text, caret) {
      record("");
      ta.value = ta.value.slice(0, a) + text + ta.value.slice(b);
      ta.setSelectionRange(caret, caret);
      sync();
    }
    ta.addEventListener("beforeinput", (e) => {
      if (e.inputType === "historyUndo") { e.preventDefault(); restore(past, future); return; }
      if (e.inputType === "historyRedo") { e.preventDefault(); restore(future, past); return; }
      const typing = e.inputType === "insertText" || e.inputType === "insertLineBreak";
      record(typing ? "type" : e.inputType.startsWith("delete") ? "delete" : "");
    });
    ta.addEventListener("keydown", (e) => {
      const open = ac.style.display === "block" && items.length && !items[0].info;
      if (!open && items.length && items[0].info && (e.key === "Escape" || e.key === "Enter")) { items = []; render(); }
      if (open && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length; render(); return; }
      if (open && (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey))) { e.preventDefault(); accept(sel); return; }
      if (open && e.key === "Escape") { e.preventDefault(); items = []; render(); return; }
      const mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
      if (mod && k === "z" && !e.shiftKey) { e.preventDefault(); restore(past, future); return; }
      if (mod && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); restore(future, past); return; }
      if (e.key === " " && e.ctrlKey) { e.preventDefault(); suggest(true); return; }
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); items = []; render(); onRun(ta.value); return; }
      const s = ta.selectionStart, nxt = ta.value[s];
      if (PAIRS[e.key] && ta.selectionStart === ta.selectionEnd && (!nxt || !/[\w:"']/.test(nxt))) {
        e.preventDefault(); edit(s, s, e.key + PAIRS[e.key], s + 1); suggest(false); return;
      }
      if ((e.key === "}" || e.key === ")" || e.key === "]") && nxt === e.key) { e.preventDefault(); ta.setSelectionRange(s + 1, s + 1); items = []; render(); return; }
      if (e.key === "Backspace" && ta.selectionStart === ta.selectionEnd && PAIRS[ta.value[s - 1]] === nxt) {
        e.preventDefault(); edit(s - 1, s + 1, "", s - 1); suggest(false);
      }
    });
    ta.addEventListener("input", () => { sync(); suggest(false); });
    ta.addEventListener("scroll", () => { hl.scrollTop = ta.scrollTop; hl.scrollLeft = ta.scrollLeft; });
    // moving the caret into {…} or after label= offers what fits there, as typing would
    const recheck = () => { const c = context(ta.value, ta.selectionStart); if (c && c.kind !== "name") suggest(false); else { items = []; render(); } };
    ta.addEventListener("click", recheck);
    ta.addEventListener("keyup", (e) => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) recheck(); });
    ta.addEventListener("blur", () => setTimeout(() => { items = []; render(); }, 150));
    ac.addEventListener("mousedown", (e) => { const it = e.target.closest(".pq-it"); if (it) { e.preventDefault(); accept(+it.dataset.i); } });
    sync();
    return {
      get value() { return ta.value; },
      set value(v) { if (v !== ta.value) { record(""); ta.value = v; } sync(); },
      focus() { ta.focus(); },
    };
  }
  return { create, context, tokens };
})();
