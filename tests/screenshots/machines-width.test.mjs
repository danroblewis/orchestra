// The Machines page fits a phone (SPEC §10: no sideways scroll at phone width): at 390 px, with
// boxes on (the default) and with the map shown, the document is no wider than the viewport. The
// real page and its scripts, served by a stub of the routes it reads (/api/machines from a saved
// fixture), in headless Chrome for Testing through puppeteer-core, found as render_intended.cjs
// finds them (PC and CH override); skipped when neither is installed. The nav scrolls sideways
// inside itself by design (style.css), so the document's width is what is measured.
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

function find() {
  const npx = path.join(HOME, ".npm/_npx");
  const pcs = fs.existsSync(npx) ? fs.readdirSync(npx).map((d) => path.join(npx, d, "node_modules/puppeteer-core")).filter((d) => fs.existsSync(d)) : [];
  const PC = process.env.PC || pcs.sort((a, b) => require(b + "/package.json").version.localeCompare(require(a + "/package.json").version, undefined, { numeric: true }))[0];
  const base = path.join(HOME, ".cache/puppeteer/chrome");
  const v = fs.existsSync(base) ? fs.readdirSync(base).sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).pop() : null;
  const CH = process.env.CH || (v && path.join(base, v, "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"));
  return PC && CH && fs.existsSync(CH) ? { PC, CH } : null;
}

const TYPES = { ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json" };
function serve() {
  const fixture = fs.readFileSync(FIXTURE, "utf8");
  const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(typeof body === "string" ? body : JSON.stringify(body)); };
  const server = http.createServer((req, res) => {
    const p = new URL(req.url, "http://x").pathname;
    if (p === "/machines") { res.writeHead(200, { "content-type": "text/html" }); return res.end(fs.readFileSync(path.join(STATIC, "machines.html"), "utf8").replaceAll("{{v}}", "1")); }
    if (p.startsWith("/static/")) {
      const f = path.join(STATIC, p.slice(8));
      if (!f.startsWith(STATIC + path.sep) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "content-type": TYPES[path.extname(f)] || "application/octet-stream" }); return res.end(fs.readFileSync(f));
    }
    if (p === "/api/machines") return json(res, fixture);
    if (p === "/api/project") return json(res, { key: "phone-width" });
    if (p === "/api/plugins") return json(res, { pages: [], scripts: [] });
    return json(res, { ok: false, error: "not in this test" }, 404);
  });
  return new Promise((r) => server.listen(0, "127.0.0.1", () => r(server)));
}

const tools = find();
test("the Machines page is no wider than a 390 px phone", { skip: !tools && "no puppeteer-core or Chrome for Testing", timeout: 60000 }, async () => {
  const puppeteer = require(tools.PC);
  const server = await serve(), port = server.address().port;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "machines-width-"));
  const b = await puppeteer.launch({ executablePath: tools.CH, headless: true, userDataDir: profile, args: ["--no-first-run", "--hide-scrollbars"] });
  try {
    const page = await b.newPage();
    await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 });
    await page.goto(`http://127.0.0.1:${port}/machines`, { waitUntil: "networkidle0" });
    await page.waitForSelector("#cards .panel");
    // what is wider than the screen, outermost first, to say what overflowed
    const measure = () => page.evaluate(() => {
      const W = document.documentElement.clientWidth, nav = document.getElementById("nav"), wide = [];
      for (const e of document.querySelectorAll("body *")) {
        if (nav.contains(e) || e.closest("svg") && e.tagName !== "svg") continue;
        const r = e.getBoundingClientRect();
        if (r.width && r.right > W + 0.5 && !(e.parentElement.getBoundingClientRect().right > W + 0.5)) wide.push(`${e.tagName.toLowerCase()}${e.id ? "#" + e.id : ""}${e.className && typeof e.className === "string" ? "." + e.className.split(" ")[0] : ""} to ${Math.round(r.right)} px`);
      }
      return { doc: document.documentElement.scrollWidth, W, wide };
    });
    const list = await measure();
    assert.ok(await page.$eval("#era", (e) => e.style.display !== "none"), "the fixture's eras show the era control");
    assert.equal(list.doc, 390, `with the phone list the page is ${list.doc} px wide: ${list.wide.join("; ")}`);
    // a name with nowhere to break ellipsizes in its card's title
    const name = await page.$$eval("#cards .panel h3 .mname", (es) => es.map((e) => ({ t: e.textContent, over: e.scrollWidth > e.clientWidth, right: e.getBoundingClientRect().right })).find((x) => x.t.startsWith("a_machine_name_much_longer")));
    assert.ok(name && name.over && name.right <= 390, `the long name is not ellipsized inside the card: ${JSON.stringify(name)}`);
    await page.click("#show-map");
    await new Promise((r) => setTimeout(r, 1000));
    const map = await measure();
    assert.equal(map.doc, 390, `with the map shown the page is ${map.doc} px wide: ${map.wide.join("; ")}`);
  } finally {
    await b.close();
    server.close();
    fs.rmSync(profile, { recursive: true, force: true });
  }
});
