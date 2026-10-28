// Predictions (sd/predictions.py, sd/judge.py) as the Dynamics and Experiments pages show them:
// what a machine said its change would do, and the verdict once the horizon passed, with the
// evidence. Pure: each function returns HTML. ``names`` gives a stock's and a flow's name
// ({stock(id), flow(id)}); without it ids are shown in plain words.
const Predictions = (() => {
  const nice = (s) => (s || "outside").toLowerCase().replace(/_/g, " ");
  const n3 = (v) => (v == null ? "—" : Math.abs(v) >= 100 ? (+v).toFixed(0) : (+v).toFixed(2));
  const dur = (s) => (s >= 3600 ? `${+(s / 3600).toFixed(1)} h` : `${Math.round(s / 60)} min`);
  // the verdict's class (its colour), and its mark: never colour alone
  const CLASS = { "passed": "passed", "side effect": "side", "model wrong elsewhere": "wrong", "no effect": "none", "interrupted": "interrupted", "undecided": "undecided" };
  const MARK = { "passed": "✓", "side effect": "!", "model wrong elsewhere": "!", "no effect": "✗", "interrupted": "⏸", "undecided": "?" };
  const badge = (verdict, partial) => (verdict
    ? `<span class="verdict ${CLASS[partial || verdict] || ""}">${MARK[verdict] || ""} ${esc(verdict)}${partial ? ` (so far: ${esc(partial)})` : ""}</span>`
    : '<span class="verdict waiting">… waiting</span>');

  function expectText(e, names = {}) {
    const fl = (id) => (names.flow ? names.flow(id) : nice(id)), st = (id) => (names.stock ? names.stock(id) : nice(id));
    if (e.kind === "factor") return `${fl(e.flow)}${e.param ? "." + e.param : ""} ×${e.factor}`;
    if (e.kind === "unchanged") return `${fl(e.flow)} unchanged`;
    if (e.kind === "equation") return `${fl(e.flow)} = ${e.equation}`;
    if (e.kind === "level") return ["below", "above"].filter((w) => w in e).map((w) => `${st(e.stock)} ${w} ${e[w]}`).join(" and ");
    if (e.id == null) return `a new flow ${e.from ? st(e.from) : "outside"} → ${e.to ? st(e.to) : "outside"} ${e.kind}${e.equation ? ` = ${e.equation}` : ""}`;
    return `${e.part} ${e.part === "stock" ? st(e.id) : e.part === "flow" ? fl(e.id) : nice(e.id)} ${e.kind}`;
  }

  // the evidence lines of a judged prediction (an expected equation's ``params`` are its numbers, an
  // object; a factor's are the comparison's rows, a list)
  function evidence(v, names = {}) {
    const st = (id) => (names.stock ? names.stock(id) : nice(id)), ev = [];
    for (const s of v.expectations || []) {
      const nums = (Array.isArray(s.params) ? s.params : []).map((n) => `${esc(n.param)} ${n3(n.before)} → ${n3(n.after)} (z ${n.z ?? "∞"}${n.predicted != null ? `; predicted ${n3(n.predicted)}, z ${n.z_predicted ?? "∞"}` : ""})`).join("; ");
      const law = s.law ? `${s.kind === "equation" ? "its law" : "its form changed; the old law"} expects ${s.law.expected} events, ${s.law.events} counted (z ${s.law.z})` : "";
      ev.push(`${esc(expectText(s, names))}: <b>${esc(s.status)}</b>${nums ? " · " + nums : ""}${law ? " · " + law : ""}${s.level != null ? ` · mean level ${n3(s.level)}` : ""}`);
    }
    for (const u of v.unpredicted || []) ev.push(`<span class="unpred">not predicted: ${esc(u.part)} ${esc(nice(u.id))} ${esc(u.status)}${u.param ? ` (${esc(u.param)} ${n3(u.before)} → ${n3(u.after)}, z ${u.z ?? "∞"})` : ""}</span>`);
    const sk = v.stocks || {};
    if ((sk.rows || []).length) ev.push(`stocks against the ${sk.from === "prediction" ? "predicted" : "simulated"} run: ` + sk.rows.map((r) => `${esc(st(r.stock))} ${n3(r.level)} against ${n3(r.central)} (z ${r.z}${r.out ? ", out of its band" : ""})`).join("; "));
    else if (sk.reason) ev.push(`stocks not simulated (${esc(sk.reason)})`);
    const fc = v.false_change;
    if (fc) ev.push(`a number changed at |z| ≥ ${fc.z}; false changes ${(100 * fc.nominal).toFixed(2)}% a number nominally${fc.measured != null ? `, ${Math.round(100 * fc.measured)}% of ${fc.flows} flows between the previous era's halves` : ""}`);
    return ev;
  }

  // one prediction as a line with its evidence under it; ``link(p)``: HTML after its head (a link
  // to the experiment it came from)
  function one(p, { names = {}, link = () => "" } = {}) {
    if (p.status === "invalid") return `<div class="pred none">${esc(p.source || "?")}: an invalid prediction: ${esc(p.why)}${link(p)}</div>`;
    const what = (p.expect || []).length ? p.expect.map((e) => expectText(e, names)).map(esc).join(", ") : "nothing changes (the null test)";
    const head = `<b>${esc(p.source || "?")}</b> predicted: ${what}, judged ${dur(p.horizon_s)} after the change${link(p)}`;
    if (p.status !== "judged") return `<div class="pred">${head} · <span class="muted">${p.era ? "waiting for the horizon" : "waiting for its change to begin an era"}</span></div>`;
    const v = p.verdict;
    const verdict = v.verdict === "interrupted" ? `interrupted by era ${esc(v.interrupted_by)} (so far: ${esc(v.partial || "nothing")})` : esc(v.verdict);
    return `<div class="pred ${CLASS[v.partial || v.verdict] || ""}">${head} · <b>${verdict}</b>${v.late ? ' <span class="muted">(made after the change)</span>' : ""}${evidence(v, names).map((x) => `<div class="ev">${x}</div>`).join("")}</div>`;
  }
  return { one, evidence, expectText, badge, dur, CLASS };
})();
