// Hundreds of people as machines on the Machines page (web/people.py, people-groups.js; the owner,
// 2026-11-04: "way too many people names sometimes, and it's breaking various things"): 600 people
// relayed from Jira and a few programs, from the answers web/people.py makes of a synthetic bus
// (tests/unit/people_fixture.py). The page asks for the grouped form: the Jira people are one card
// and one node on the map, "Jira people (600)", with the group's edges summed; the card opens into
// a list with search, fetched on demand; the node opens into the people one by one, and they fold
// back into one; the owner-mapped person stays a card of its own; the map is laid out quickly; the
// page is no wider than the screen at desktop and phone width.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(import.meta.dirname, "../..");
const STATIC = path.join(ROOT, "orchestra/web/static");
const HOME = os.homedir();
const SHOTS = process.env.SHOTS || null;      // a directory to keep the screenshots in, when given

function find() {
  const npx = path.join(HOME, ".npm/_npx");
  const pcs = fs.existsSync(npx) ? fs.readdirSync(npx).map((d) => path.join(npx, d, "node_modules/puppeteer-core")).filter((d) => fs.existsSync(d)) : [];
  const PC = process.env.PC || pcs.sort((a, b) => require(b + "/package.json").version.localeCompare(require(a + "/package.json").version, undefined, { numeric: true }))[0];
  const base = path.join(HOME, ".cache/puppeteer/chrome");
  const v = fs.existsSync(base) ? fs.readdirSync(base).sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).pop() : null;
  const CH = process.env.CH || (v && path.join(base, v, "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"));
  return PC && CH && fs.existsSync(CH) ? { PC, CH } : null;
}

// the answers, as web/people.py makes them of the synthetic bus
function answers() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "machines-people-"));
  execFileSync("uv", ["run", "python", path.join(ROOT, "tests/unit/people_fixture.py"), dir], { cwd: ROOT, stdio: ["ignore", "ignore", "inherit"] });
  const out = Object.fromEntries(["full", "grouped", "expanded", "members"].map((k) => [k, fs.readFileSync(path.join(dir, `${k}.json`), "utf8")]));
  fs.rmSync(dir, { recursive: true, force: true });
  return out;
}

const TYPES = { ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json" };
function serve(A, asked) {
  const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(typeof body === "string" ? body : JSON.stringify(body)); };
  const server = http.createServer((req, res) => {
    const u = new URL(req.url, "http://x"), p = u.pathname;
    if (p === "/") { res.writeHead(200, { "content-type": "text/html" }); return res.end(fs.readFileSync(path.join(STATIC, "index.html"), "utf8").replaceAll("{{v}}", "1")); }
    if (p === "/machines") { res.writeHead(200, { "content-type": "text/html" }); return res.end(fs.readFileSync(path.join(STATIC, "machines.html"), "utf8").replaceAll("{{v}}", "1")); }
    if (p.startsWith("/static/")) {
      const f = path.join(STATIC, p.slice(8));
      if (!f.startsWith(STATIC + path.sep) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "content-type": TYPES[path.extname(f)] || "application/octet-stream" }); return res.end(fs.readFileSync(f));
    }
    if (p === "/api/machines") {
      asked.push(u.search);
      if (u.searchParams.get("people") !== "grouped") return json(res, A.full);
      return json(res, (u.searchParams.get("expand") || "").split(",").includes("people/jira") ? A.expanded : A.grouped);
    }
    if (p === "/api/machines/people") { asked.push("members:" + u.searchParams.get("group")); return json(res, A.members); }
    if (p === "/api/project") return json(res, { key: "people" });
    if (p === "/api/plugins") return json(res, { pages: [], scripts: [] });
    return json(res, { ok: false, error: "not in this test" }, 404);
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r(server)));
}

const tools = find();
const A = tools ? answers() : null;
// how long the map takes to show, from the page's load: its drawing is hidden until laid out (netgraph.js)
async function drawn(page, t0) {
  await page.waitForFunction(() => { const s = document.querySelector("#evsvg-host svg"); return s && s.style.visibility !== "hidden"; }, { timeout: 30000 });
  return Date.now() - t0;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// a click on what the selector finds now (the page redraws a card when what it says changed)
const click = (page, sel) => page.waitForFunction((s) => { const e = document.querySelector(s); if (e) e.click(); return !!e; }, { timeout: 5000 }, sel);

// MEASURE=1: how long the page takes with the full answer and the grouped one, printed
test("measure", { skip: (!tools || !process.env.MEASURE) && "MEASURE=1 to measure", timeout: 180000 }, async () => {
  const puppeteer = require(tools.PC);
  for (const form of ["full", "grouped", "expanded"]) {
    const asked = [], server = await serve(form === "full" ? { ...A, grouped: A.full, expanded: A.full } : form === "expanded" ? { ...A, grouped: A.expanded } : A, asked), port = server.address().port;
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), "machines-people-"));
    const b = await puppeteer.launch({ executablePath: tools.CH, headless: true, userDataDir: profile, args: ["--no-first-run", "--hide-scrollbars"] });
    try {
      const page = await b.newPage();
      await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
      const t0 = Date.now();
      await page.goto(`http://127.0.0.1:${port}/machines`);
      const ms = await drawn(page, t0), busy = await page.metrics();
      const render = await page.evaluate(() => { const t = performance.now(); render(); return performance.now() - t; });
      if (process.env.MEASURE === "profile" && form === "expanded") {
        const cdp = await page.target().createCDPSession(); await cdp.send("Profiler.enable"); await cdp.send("Profiler.setSamplingInterval", { interval: 100 }); await cdp.send("Profiler.start");
        await page.evaluate(() => { for (let i = 0; i < 3; i++) render(); });
        const { profile } = await cdp.send("Profiler.stop"); const self = new Map(), dt = profile.timeDeltas, byId = new Map(profile.nodes.map((n) => [n.id, n]));
        profile.samples.forEach((id, i) => { const n = byId.get(id), k = `${n.callFrame.functionName || "(anon)"} ${n.callFrame.url.split("/").pop()}:${n.callFrame.lineNumber + 1}`; self.set(k, (self.get(k) || 0) + (dt[i] || 0)); });
        console.log([...self].sort((a, b) => b[1] - a[1]).slice(0, 15).map(([k, v]) => `${(v / 1000).toFixed(0)}ms ${k}`).join("\n"));
      }
      if (process.env.MEASURE === "parts") console.log(await page.evaluate(() => { const T = (f) => { const t = performance.now(); f(); return Math.round(performance.now() - t); };
        const r0 = GRAPH.render; let gr = 0; GRAPH.render = (...a) => { const t = performance.now(); r0(...a); gr += performance.now() - t; };
        const out = { map: T(() => eventMap(DATA)), graphRender: Math.round(gr), cards: T(cards), phone: T(() => phoneList(MachineFold.forMap(DATA, EV_SHOW_FOLDED))), intended: T(() => IntendedMachines.draw(DATA)) };
        GRAPH.render = r0; return JSON.stringify(out); }));
      const n = await page.evaluate(() => ({ cards: document.querySelectorAll("#cards .panel").length, nodes: document.querySelectorAll("#evsvg-host g.ng-node").length }));
      console.log(`${form}: map shown after ${ms} ms (${Math.round(busy.TaskDuration * 1000)} ms of the main thread's), a refresh's render ${render.toFixed(0)} ms, ${n.cards} cards, ${n.nodes} nodes`);
    } finally { await b.close(); server.close(); fs.rmSync(profile, { recursive: true, force: true }); }
  }
});

for (const width of [1280, 390]) {
  test(`600 people are one card and one node, open into a list and into the map's nodes, at ${width} px`, { skip: !tools && "no puppeteer-core or Chrome for Testing", timeout: 120000 }, async () => {
    const puppeteer = require(tools.PC);
    const asked = [], server = await serve(A, asked), port = server.address().port;
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), "machines-people-"));
    const b = await puppeteer.launch({ executablePath: tools.CH, headless: true, userDataDir: profile, args: ["--no-first-run", "--hide-scrollbars"] });
    try {
      const page = await b.newPage();
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      const t0 = Date.now();
      await page.goto(`http://127.0.0.1:${port}/machines`, { waitUntil: "networkidle0" });
      await page.waitForSelector("#cards .panel");
      if (width < 760) await page.click("#show-map");
      const ms = await drawn(page, t0), busy = (await page.metrics()).TaskDuration * 1000;
      assert.ok(busy < 1500, `the page's main thread was busy ${Math.round(busy)} ms before the map showed (2.9 s one by one)`);
      assert.ok(ms < 8000, `the map showed after ${ms} ms`);
      assert.match(asked[0], /people=grouped/);
      // one card for the 600, the owner-mapped person and the programs each their own; counted as machines
      const cards = await page.$$eval("#cards .panel", (es) => es.map((e) => e.dataset.id));
      assert.ok(cards.includes("people/jira") && cards.includes("person.alice") && cards.includes("triage"), cards.join(" "));
      assert.ok(!cards.some((id) => id.startsWith("person.jira.")), "a relayed person is a card of its own");
      assert.equal(await page.$eval("#nm", (e) => e.textContent), "605");
      assert.match(await page.$eval('#cards .panel[data-id="people/jira"]', (e) => e.textContent), /Jira people \(600\)[\s\S]*600 people relayed from jira/);
      // one node on the map, its lines summed: the people hand the issues to triage, 600 times
      const nodes = () => page.$$eval("#evsvg-host g.ng-node", (es) => es.map((e) => e.dataset.id));
      let ns = await nodes();
      assert.ok(ns.includes("m:people/jira") && ns.includes("m:person.alice") && !ns.some((id) => id.startsWith("m:person.jira.")), ns.join(" "));
      assert.ok(await page.evaluate(() => DATA.handoffs.some((h) => h.from === "people/jira" && h.to === "triage" && h.count === 600)));
      const W = () => page.evaluate(() => document.documentElement.scrollWidth);
      assert.equal(await W(), width, "no wider than the screen");
      if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `machines-people-${width}.png`), fullPage: false });

      // the card opens into its people, fetched then, with search
      await click(page, '#cards .panel[data-id="people/jira"] .people-acts button');
      await page.waitForSelector('#cards .people-list .pl-person');
      assert.ok(asked.includes("members:people/jira"));
      assert.equal((await page.$$("#cards .pl-person")).length, 100, "a hundred at a time");
      assert.match(await page.$eval("#cards .pl-rows", (e) => e.textContent), /500 more: narrow the search/);
      await page.evaluate(() => { const i = document.querySelector("#cards .people-list input"); i.value = "person 42"; i.dispatchEvent(new Event("input", { bubbles: true })); });
      await sleep(200);
      const found = await page.$$eval("#cards .pl-person b", (es) => es.map((e) => e.textContent));
      assert.deepEqual(found.sort(), ["Person 42", ...Array.from({ length: 10 }, (_, i) => `Person 42${i}`)].sort());
      assert.equal(await W(), width, "the open list fits");
      if (SHOTS) await (await page.$('#cards .panel[data-id="people/jira"]')).screenshot({ path: path.join(SHOTS, `machines-people-list-${width}.png`) });
      // a person in the list: the group is shown one by one on the map, and that person opened
      await click(page, '#cards .pl-person[data-id="person.jira.u0420"]');
      await page.waitForFunction(() => DATA.machines.some((m) => m.id === "person.jira.u0420"));
      assert.match(asked[asked.length - 1], /expand=people%2Fjira/);
      await page.waitForFunction(() => document.querySelector("#im-side") && document.querySelector("#im-side").textContent.includes("Person 420"), { timeout: 5000 });
      // still one card, its people not cards of their own
      const after = await page.$$eval("#cards .panel", (es) => es.map((e) => e.dataset.id));
      assert.ok(after.includes("people/jira") && !after.some((id) => id.startsWith("person.jira.")));
      await page.waitForFunction(() => document.querySelectorAll("#evsvg-host g.ng-node").length > 600, { timeout: 15000 });
      ns = await nodes();
      assert.ok(!ns.includes("m:people/jira") && ns.includes("m:person.jira.u0420"));
      // the map's bar draws them as one again
      await page.evaluate(() => IntendedMachines.close());
      await click(page, "#ev-people button");
      await page.waitForFunction(() => DATA.machines.some((m) => m.id === "people/jira"));
      assert.doesNotMatch(asked[asked.length - 1], /expand/);
      await page.waitForFunction(() => document.querySelector('#evsvg-host g.ng-node[data-id="m:people/jira"]'), { timeout: 15000 });
      // the group's node opens into its people
      await page.evaluate(() => document.querySelector('#evsvg-host g.ng-node[data-id="m:people/jira"]').dispatchEvent(new MouseEvent("click", { bubbles: true })));
      await page.waitForFunction(() => document.querySelectorAll("#evsvg-host g.ng-node").length > 600, { timeout: 15000 });
      assert.match(asked[asked.length - 1], /expand=people%2Fjira/);
      assert.equal(await W(), width, "600 nodes drawn, still no wider than the screen");
    } finally {
      await b.close();
      server.close();
      fs.rmSync(profile, { recursive: true, force: true });
    }
  });
}

for (const width of [1280, 390]) {
  test(`the Dashboard counts the 600 people as many and shows them in one line, at ${width} px`, { skip: !tools && "no puppeteer-core or Chrome for Testing", timeout: 60000 }, async () => {
    const puppeteer = require(tools.PC);
    const asked = [], server = await serve(A, asked), port = server.address().port;
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), "machines-people-"));
    const b = await puppeteer.launch({ executablePath: tools.CH, headless: true, userDataDir: profile, args: ["--no-first-run", "--hide-scrollbars"] });
    try {
      const page = await b.newPage();
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle0" });
      await page.waitForFunction(() => /machines:/.test((document.querySelector('[gs-id="machines"] .sub, .dpanel .sub') || {}).textContent || [...document.querySelectorAll(".sub")].map((e) => e.textContent).join(" ")), { timeout: 15000 });
      assert.ok(asked.some((q) => /people=grouped/.test(q)), asked.join(" "));
      const sub = await page.evaluate(() => [...document.querySelectorAll(".sub")].map((e) => e.textContent).find((t) => /machines:/.test(t)));
      assert.match(sub, /^605 machines: /, sub);
      const text = await page.evaluate(() => document.body.textContent);
      assert.ok(!/Person 1\b/.test(text), "no person listed one by one");
      assert.match(text, /601 people quiet \(on the Machines page\)/, "the 600 and the owner-mapped person, in one line");
      if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `dashboard-people-${width}.png`), fullPage: false });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width, "no wider than the screen");
    } finally {
      await b.close();
      server.close();
      fs.rmSync(profile, { recursive: true, force: true });
    }
  });
}
