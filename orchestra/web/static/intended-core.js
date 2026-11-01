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
  // who made it: "the owner (quoted), per worker/1"
  function owner(p) {
    if (!p || p.via === "page" || !p.via) return "you";
    return `the owner (quoted), per ${p.source || (p.via === "endpoint" ? "a caller of the endpoint" : "a plugin")}`;
  }
  // who put an element in the declared layer, from its provenance: "declared by you", "proposed by
  // integrator"; the source as the call named it
  function declaredBy(x) {
    const p = (x && x.provenance) || {}, who = p.author === "owner" ? owner(p) : (p.source || p.author || "");
    return who ? `${x.state === "proposed" ? "proposed" : "declared"} by ${who}` : "";
  }
  return { REQ, hears, listenersOf, asker, declaredBy, owner };
})();
