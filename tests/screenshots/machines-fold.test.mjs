// The Machines page's folded machines in the real page (machine-fold.js, machines.html): two
// machines that only announced themselves and one the owner hid are not cards and not on the map;
// they are listed, with their counts, in the collapsed groups after the cards; "Hide all of these"
// sends one control naming both, "Show" one unignore, "Hide this machine" one ignore; the legend's
// toggle draws them on the map; the page stays no wider than a 390 px phone. Served as
// machines-width.test.mjs serves the page, from the same saved fixture with the three added.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(import.meta.dirname, "../..");
const STATIC = path.join(ROOT, "orchestra/web/static");
const FIXTURE = path.join(ROOT, "tests/fixtures/machines/phone-width-2026-11-03.json");
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

const NOW = Date.now() / 1000;
function data() {
  const d = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
  const person = (id) => ({ ...d.machines.find((m) => m.id === "review_nudger"), id, name: null, kind: "person", publishes: [], subscribes: [],
    flows: [], instances: [], first_seen: NOW - 3600, last_seen: NOW - 3600, active: false, announced: 1, announced_at: NOW - 3600, announced_only: true, hidden: null, intent: null });
  d.machines.push(person("person.tracker.u1"), person("person.tracker.u2"));
  for (const m of d.machines) { m.announced_only = m.announced_only || false; m.hidden = m.hidden || null; }
  d.machines.find((m) => m.id === "review_nudger").hidden = { provenance: { author: "owner", via: "page", at: NOW - 120 }, change: "c9.0" };
  return d;
}

const TYPES = { ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json" };
function serve(posted) {
  const fixture = JSON.stringify(data());
  const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(typeof body === "string" ? body : JSON.stringify(body)); };
  const server = http.createServer((req, res) => {
    const p = new URL(req.url, "http://x").pathname;
    if (p === "/machines") { res.writeHead(200, { "content-type": "text/html" }); return res.end(fs.readFileSync(path.join(STATIC, "machines.html"), "utf8").replaceAll("{{v}}", "1")); }
    if (p.startsWith("/static/")) {
      const f = path.join(STATIC, p.slice(8));
      if (!f.startsWith(STATIC + path.sep) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "content-type": TYPES[path.extname(f)] || "application/octet-stream" }); return res.end(fs.readFileSync(f));
    }
    if (p === "/api/intended/control" && req.method === "POST") {
      let b = ""; req.on("data", (c) => { b += c; }); req.on("end", () => { posted.push(JSON.parse(b)); json(res, { ok: true, version: posted.length }); }); return;
    }
    if (p === "/api/machines") return json(res, fixture);
    if (p === "/api/project") return json(res, { key: "fold" });
    if (p === "/api/plugins") return json(res, { pages: [], scripts: [] });
    return json(res, { ok: false, error: "not in this test" }, 404);
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r(server)));
}

const FOLDED = ["person.tracker.u1", "person.tracker.u2", "review_nudger"];
const tools = find();
for (const width of [1280, 390]) {
  test(`folded machines leave the cards and the map at ${width} px`, { skip: !tools && "no puppeteer-core or Chrome for Testing", timeout: 60000 }, async () => {
    const puppeteer = require(tools.PC);
    const posted = [], server = await serve(posted), port = server.address().port;
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), "machines-fold-"));
    const b = await puppeteer.launch({ executablePath: tools.CH, headless: true, userDataDir: profile, args: ["--no-first-run", "--hide-scrollbars"] });
    try {
      const page = await b.newPage();
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      await page.goto(`http://127.0.0.1:${port}/machines`, { waitUntil: "networkidle0" });
      await page.waitForSelector("#cards .panel");
      if (width < 760) { await page.click("#show-map"); }
      await new Promise((r) => setTimeout(r, 1200));
      const cards = await page.$$eval("#cards .panel", (es) => es.map((e) => e.dataset.id));
      for (const id of FOLDED) assert.ok(!cards.includes(id), `${id} is a card`);
      assert.ok(cards.includes("worker"));
      assert.equal(await page.$eval("#nm", (e) => e.textContent), String(cards.length));
      const groups = await page.$$eval("#folded details", (es) => es.map((e) => ({ id: e.id, open: e.open, summary: e.querySelector("summary").textContent })));
      assert.deepEqual(groups.map((g) => [g.id, g.open]), [["fold-announced", false], ["fold-hidden", false]]);
      assert.match(groups[0].summary, /^announced only, never acted 2/); assert.match(groups[1].summary, /^hidden by you 1/);
      const mapText = await page.$eval("#evsvg-host", (e) => e.textContent);
      for (const id of FOLDED) assert.ok(!mapText.includes(id), `${id} is on the map`);
      assert.ok(await page.$("#ev-folded"), "the legend offers the folded machines");
      const W = await page.evaluate(() => document.documentElement.scrollWidth);
      assert.equal(W, width, `the page is ${W} px wide at ${width}`);
      await page.evaluate(() => { for (const d of document.querySelectorAll("#folded details")) d.open = true; });
      if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `machines-fold-${width}.png`), fullPage: true });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width, "the open groups fit");
      // the controls: one change for the whole group, one per machine
      await page.click("#fold-announced .fold-all");
      await page.click("#fold-hidden .fold-row button");
      await page.click(`#cards .panel[data-id="worker"] .hide-row button`);
      await new Promise((r) => setTimeout(r, 300));
      assert.deepEqual(posted.map((x) => [x.control, x.part, x.keys || x.id]), [["ignore", "machine", ["person.tracker.u1", "person.tracker.u2"]],
        ["unignore", "machine", "review_nudger"], ["ignore", "machine", "worker"]]);
      // the legend's toggle draws them
      await page.click("#ev-folded");
      await new Promise((r) => setTimeout(r, 1200));
      const shown = await page.$eval("#evsvg-host", (e) => e.textContent);
      assert.ok(shown.includes("person.tracker.u1") && shown.includes("review_nudger"), "shown on the map when asked");
    } finally {
      await b.close();
      server.close();
      fs.rmSync(profile, { recursive: true, force: true });
    }
  });
}
