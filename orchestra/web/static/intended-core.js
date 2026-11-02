// Who the owner's requests reach (AGENTS.md rule 9): a request is published on the bus as
// orchestra.intent.requested, and acted on only by a machine that announced it listens for it. The
// pages name that machine, never one by assumption, and say so when none listens. Shared by the
// Machines page (intended-machines.js) and the Dynamics page (intended-dynamics.js, -panel, -drawers).
const IntendedCore = (() => {
  const REQ = "orchestra.intent.requested";
  const hears = (t) => t === REQ || t === "*" || t === "orchestra.*" || (t.endsWith(".*") && REQ.startsWith(t.slice(0, -1)));
  // the ids of the machines (as /api/machines lists them) that listen for a request; a placeholder a
  // plugin declared but the bus has not heard (unseen) is none: nothing on the bus listens yet
  const listenersOf = (machines) => (machines || []).filter((x) => !x.unseen && (x.subscribes || []).some(hears)).map((x) => x.id);
  const NONE = "no machine listens for requests";
  // ``ids``: the listeners, or null while the bus has not been read (then nobody is named)
  function asker(ids) {
    const known = Array.isArray(ids), some = known && ids.length > 0, who = some ? ids.join(" or ") : "";
    return {
      some, known, who,
      // "ask <machine> to link"; with no listener, that nothing will act on it
      ask: (what = "") => (some ? `ask ${who}${what ? " to " + what : ""}`
        : known ? `${NONE}${what ? " to " + what : ""}: nothing will act on this`
          : `ask the machine that listens for requests${what ? " to " + what : ""}`),
      // a control's title: what pressing it does
      title: (what) => (some ? `asks ${who} to ${what}` : known ? `publishes a request to ${what}; ${NONE}` : `asks the machine that listens for requests to ${what}`),
      // "asked <machine>" (the request was sent)
      asked: () => (some ? `asked ${who}` : "asked"),
      // a whole sentence: "To <what>, ask X."; with no listener, that <doing> needs one and nothing will act yet
      sentence: (what, doing) => (some ? `To ${what}, ask ${who}.`
        : known ? `${doing} needs a machine that listens for ${REQ}; none does, so nothing will act on it yet.`
          : `To ${what}, ask the machine that listens for requests.`),
    };
  }
  // the owner, as the provenance says: "you" for the owner's own click on a page; through a plugin
  // or the endpoint, author: owner is the caller's assertion backed by its quote, so the page says
  // who made it: "owner (quoted), per worker/1"
  function owner(p) {
    if (!p || p.via === "page" || !p.via) return "you";
    return `owner (quoted), per ${p.source || (p.via === "endpoint" ? "a caller of the endpoint" : "a plugin")}`;
  }
  // who put an element in the declared layer, from its provenance: "declared by you", "proposed by
  // integrator"; the source as the call named it
  function declaredBy(x) {
    const p = (x && x.provenance) || {}, who = p.author === "owner" ? owner(p) : (p.source || p.author || "");
    return who ? `${x.state === "proposed" ? "proposed" : "declared"} by ${who}` : "";
  }
  // who put a machine in the declared layer, by name: "you" (or the owner, quoted), "the workflows
  // plugin" when the author is a package a machine on the bus announced (``ms``: the machines; the
  // source after it when that says more and ``brief`` is not asked: "the workflows plugin (workflow
  // delivery_sail)"), else its source as the call named it
  function author(it, m, ms = null, brief = false) {
    const p = (it && it.provenance) || {}, a = (it && it.author) || p.author;
    if (a === "owner") return owner(p);
    const packages = new Set([m, ...(ms || [])].filter(Boolean).map((x) => x.package).filter(Boolean));
    if (a && packages.has(a)) return `the ${a} plugin${!brief && p.source && p.source !== a ? ` (${p.source})` : ""}`;
    const who = p.source || a;
    return who ? `the ${who.charAt(0).toUpperCase() + who.slice(1)}` : "a plugin";
  }
  // what a declared machine's tag and its line under it say: a tag only for what is not observed
  // ("proposed, never heard", "declared, never heard"), so no tag means heard, on every page; who said
  // what (proposed by, declared by, confirmed by) is the line under it, in the card and the side panel,
  // never "unconfirmed" (the owner, 2026-11-01: "What does confirmed or unconfirmed even mean here?").
  // ``ms``: the machines on the bus (whose packages name a plugin); ``brief``: without the source.
  // {text ("" when heard), cls, by}
  function machineWords(m, ms = null, brief = false) {
    const it = (m && m.intent) || {}, c = it.confirmed, by = author(it, m, ms, brief);
    if (it.state === "proposed") {
      const said = `${it.author === "owner" ? "added" : "proposed"} by ${by}`;
      return it.heard ? { text: "", cls: "", by: said } : { text: "proposed, never heard", cls: "im-t-ghost", by: said };
    }
    const who = c && c.by ? (c.by === "owner" ? owner(c) : c.by) : null;
    const said = who ? `proposed by ${by}, confirmed by ${who}` : `declared by ${by}`;
    return it.heard ? { text: "", cls: "", by: said } : { text: "declared, never heard", cls: "im-t-ghost", by: said };
  }
  // what confirming does, said on the control (rule 9: a request, changing nothing until acted on)
  const CONFIRMS = "adopt this proposal as a declaration; it changes nothing observed";
  return { REQ, NONE, hears, listenersOf, asker, declaredBy, owner, author, machineWords, CONFIRMS };
})();
