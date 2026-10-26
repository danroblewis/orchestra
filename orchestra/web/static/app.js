// Shared helpers, nav, and drawers for the Orchestra UI.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const color = (s) => `var(--${s})`;
const ago = (sec) => (sec < 60 ? `${Math.round(sec)}s` : sec < 3600 ? `${Math.round(sec / 60)}m` : `${(sec / 3600).toFixed(1)}h`);
const fmtBytes = (b) => (b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(1)} GB` : `${Math.round(b / (1 << 20))} MB`);

// Machine cards a package draws for its own machines (orchestra/plugins.py). A machine belongs to
// a package when its announcement says so, or the package declares it (``m.package``). The
// package's every-page script registers, for its package name:
//   card(m, {compact})  -> the inside of the machine's card (HTML), or null for Orchestra's own;
//   open(m)             -> true when it opened the machine's dialog itself, else Orchestra opens its own.
// ``changed()`` asks the pages to draw the cards again (its data arrived). Any machine no package
// claims gets Orchestra's card and dialog.
window.Orchestra = window.Orchestra || {};
Orchestra.machineCards = (() => {
  const by = new Map();
  const changed = () => document.dispatchEvent(new Event("orchestra:machinecards"));
  return {
    register(pkg, spec) { by.set(pkg, spec); changed(); },
    of(m) { return (m && m.package && by.get(m.package)) || null; },
    card(m, opts = {}) { const s = this.of(m); try { return s && s.card ? s.card(m, opts) : null; } catch (e) { return null; } },
    open(m) {
      if (this.skip === m.id) { this.skip = null; return false; }       // "machine details": Orchestra's own dialog
      const s = this.of(m); try { return !!(s && s.open && s.open(m)); } catch (e) { return false; }
    },
    openDefault(id) { this.skip = id; if (typeof openMachine === "function") openMachine(id); else location.href = "/machines#" + encodeURIComponent(id); },
    changed,
  };
})();

// The nav links are static HTML; this fills in the project label on every page, and adds the
// installed plugins' pages (orchestra/plugins.py) after Orchestra's own.
fetch("/api/project").then((r) => r.json()).then((p) => { const el = $("proj"); if (el) el.textContent = p.key; }).catch(() => {});
fetch("/api/plugins").then((r) => r.json()).then((d) => {
  const nav = $("nav"), at = $("proj");
  if (!nav) return;
  for (const pg of d.pages || []) {
    const a = document.createElement("a");
    a.href = pg.path; a.textContent = pg.title;
    if (location.pathname === pg.path || location.pathname.startsWith(pg.path + "/")) a.className = "on";
    nav.insertBefore(a, at);
  }
  // scripts a plugin runs on every page, after Orchestra's own (a page that already has one keeps it)
  for (const src of d.scripts || []) {
    if ([...document.scripts].some((s) => s.src && new URL(s.src).pathname === src)) continue;
    const s = document.createElement("script"); s.src = src; document.body.appendChild(s);
  }
}).catch(() => {});

// Agent prose and human input are markdown. Render it sanitized, then highlight code
// blocks, guessing the language when the fence does not name one.
function md(text) {
  if (!text) return "";
  if (!(window.marked && window.DOMPurify)) return `<pre>${esc(text)}</pre>`;
  return `<div class="md">${DOMPurify.sanitize(marked.parse(text, { gfm: true, breaks: true }))}</div>`;
}
function highlightCode(root) {
  if (!window.hljs) return;
  root.querySelectorAll("pre code").forEach((el) => {
    if (el.dataset.highlighted) return;
    const named = [...el.classList].find((c) => c.startsWith("language-"));
    if (named && hljs.getLanguage(named.slice(9))) hljs.highlightElement(el);
    else {
      const r = hljs.highlightAuto(el.textContent);
      el.innerHTML = r.value; el.classList.add("hljs", `language-${r.language || "plaintext"}`);
      el.dataset.highlighted = "yes";
    }
  });
}
function openDrawer(html) { $("drawer").innerHTML = html; highlightCode($("drawer")); $("overlay").classList.add("open"); }
function closeDrawer() { $("overlay").classList.remove("open"); }


// ---- log highlighting -------------------------------------------------------
// Logs have no grammar, so this is lexical: each pattern below is tried at the
// current position, first match wins, and everything else passes through escaped.
const LOG_RULES = [
  [/\x1b\[[0-9;]*m/y, null],                                                    // ANSI escapes: dropped
  [/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/y, "ts"],
  [/\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b/y, "ts"],
  [/\b(?:ERROR|CRITICAL|FATAL|Traceback|Exception|FAILED|failed|error)\b/y, "err"],
  [/\b(?:WARN(?:ING)?|warning|deprecated)\b/y, "warn"],
  [/\b(?:INFO|DEBUG|TRACE|healthy|passed|ok|OK|200|201|204)\b/y, "ok"],
  [/\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b/y, "method"],
  [/\b[45]\d{2}\b/y, "err"],
  [/\b3\d{2}\b/y, "warn"],
  [/https?:\/\/[^\s"'<>)\]]+/y, "url"],
  [/\[[^\]\n]{1,40}\]/y, "tag"],
  [/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/y, "str"],
  [/(?:~|\.{1,2})?\/[\w.\-~+@%]+(?:\/[\w.\-~+@%]*)+/y, "path"],
  [/\b[A-Za-z_][\w.-]*(?==[^=\s])/y, "key"],
  [/\b\d+(?:\.\d+)?(?:ms|s|m|h|%|[kMG]i?B)?\b/y, "num"],
];

function highlightLog(text) {
  let out = "", i = 0;
  while (i < text.length) {
    let matched = false;
    for (const [re, cls] of LOG_RULES) {
      re.lastIndex = i;
      const m = re.exec(text);
      if (m && m.index === i && m[0].length) {
        out += cls ? `<span class="lg-${cls}">${esc(m[0])}</span>` : "";
        i += m[0].length; matched = true; break;
      }
    }
    if (!matched) {
      // Advance to the next candidate start cheaply: copy a run of plain word/space chars.
      const run = /[^\x1b\d"'\[/~.A-Za-z]+|[A-Za-z]+|./y; run.lastIndex = i;
      const m = run.exec(text); const chunk = m ? m[0] : text[i];
      out += esc(chunk); i += chunk.length;
    }
  }
  return out;
}
