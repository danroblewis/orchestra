// The people relayed from one system as one group on the Machines page (orchestra/web/static/
// people-groups.js, over web/people.py's grouped answer): the cards are each machine not in a group
// and each group once, expanded on the map or not; every machine's id counts toward the colours;
// the search names people by name or id; the expanded groups are remembered and asked for.
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const P = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/people-groups.js"));
const group = (id, ids, extra = {}) => ({ id, name: `Jira people (${ids.length})`, people_group: { key: id, system: "jira", group: null, title: "Jira people", size: ids.length, active: 1, announced_only: 0, names: ids.slice(0, 3).map((x) => x.toUpperCase()), ids, expanded: false, ...extra } });

test("the cards: a group once, its people expanded on the map not cards of their own", () => {
  const g = group("people/jira", ["person.jira.a", "person.jira.b"]);
  const collapsed = { machines: [{ id: "triage" }, g], people_groups: [g] };
  assert.deepEqual(P.forCards(collapsed).map((m) => m.id), ["triage", "people/jira"]);
  const open = group("people/jira", ["person.jira.a", "person.jira.b"], { expanded: true });
  const expanded = { machines: [{ id: "triage" }, { id: "person.jira.a", in_people: "people/jira" }, { id: "person.jira.b", in_people: "people/jira" }], people_groups: [open] };
  assert.deepEqual(P.forCards(expanded).map((m) => m.id), ["triage", "people/jira"]);
  assert.deepEqual(P.allIds(expanded), ["person.jira.a", "person.jira.b", "triage"]);
  assert.deepEqual(P.allIds(collapsed), ["person.jira.a", "person.jira.b", "triage"]);
  assert.deepEqual(P.ids(g), ["person.jira.a", "person.jira.b"]);
  assert.deepEqual(P.ids({ id: "triage" }), ["triage"]);
});

test("search by name or id, any part, any case", () => {
  const ms = [{ id: "person.jira.u1", name: "Ada Lovelace" }, { id: "person.jira.u2", name: null }, { id: "person.jira.x3", name: "Grace" }];
  assert.deepEqual(P.search(ms, "LOVE").map((m) => m.id), ["person.jira.u1"]);
  assert.deepEqual(P.search(ms, "u2").map((m) => m.id), ["person.jira.u2"]);
  assert.equal(P.search(ms, "  ").length, 3);
});

test("the groups opened on the map are remembered and asked for", () => {
  const store = new Map(), S = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.equal(P.query(P.expanded(S)), "people=grouped");
  P.remember(new Set(["people/jira", "people/slack"]), S);
  assert.equal(P.query(P.expanded(S)), "people=grouped&expand=people%2Fjira%2Cpeople%2Fslack");
  S.setItem(P.KEY, "{not json");
  assert.equal(P.expanded(S).size, 0);
});

test("a group's summary says how many, how many active, and a few names", () => {
  assert.equal(P.summary(group("people/jira", ["a", "b", "c", "d"])), "4 people relayed from jira · 1 active · A, B, C and 1 more");
});
