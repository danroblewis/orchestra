// Render the Dynamics page's frames D1–D3 from the real page and API (intended_frames.py starts
// the servers) and report what each frame shows, as JSON on the last line of stdout.
//   D1_URL=… D2_URL=… OUT=… node render_intended.cjs [frame ...]
// Like mockups/tools/render.cjs: headless Chrome for Testing through puppeteer-core (PC and CH
// override where they are found), 1440 px wide; writes <OUT>/<frame>.png (the full page) and
// <OUT>/<frame>-1440x900.png (the first screen). The graph is pinned where the mockups pinned it,
// so the frames compare. D3 follows D2 in one browser: the owner presses "expect" on the new stock
// in the Changes panel, turns the changes off and opens the stock.
const fs = require("fs"), path = require("path"), os = require("os");
const HOME = os.homedir();
const PC = process.env.PC || fs.readdirSync(path.join(HOME, ".npm/_npx")).map((d) => path.join(HOME, ".npm/_npx", d, "node_modules/puppeteer-core"))
  .filter((d) => fs.existsSync(d)).sort((a, b) => require(b + "/package.json").version.localeCompare(require(a + "/package.json").version, undefined, { numeric: true }))[0];
const CH = process.env.CH || (() => { const base = path.join(HOME, ".cache/puppeteer/chrome"); const v = fs.readdirSync(base).sort().pop();
  return path.join(base, v, "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"); })();
const puppeteer = require(PC);
const { D1_URL, D2_URL, EXTRAS_URL, OUT } = process.env;
const want = process.argv.slice(2).length ? process.argv.slice(2) : ["D1", "D1-closed", "D2", "D3", "D3-closed", "D-extras"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// where a person would have dragged them (mockups/additions.js), the ghost beside DONE
const LAYOUT = [["s:tasks_tickets_OPEN", 0, 0], ["s:tasks_tickets_IN_PROGRESS", 330, 0], ["s:tasks_tickets_READY_FOR_REVIEW", 680, 0], ["s:test_report_files_read", 1030, 0],
  ["s:repo_files", 0, 210], ["s:repo_commits", 330, 210], ["x:features", 680, 210], ["s:tasks_tickets_DONE", 1030, 210], ["s:acceptance_tests_passing", 1030, 400], ["s:features_placeholder", 330, 400]];

// what a frame shows, read from the page's DOM
function inspect() {
  const q = (s) => document.querySelector(s), qa = (s) => [...document.querySelectorAll(s)];
  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : null);
  const node = (id) => q(`#diagram g.ng-node[data-id="${id}"]`);
  const tags = (id) => (node(id) ? [...node(id).querySelectorAll(".im-svgtag text")].map(txt) : null);
  const sw = q("#im-since");
  const open = q("#overlay").classList.contains("open");
  return {
    ghost: node("x:features") ? { cls: node("x:features").getAttribute("class"), tags: tags("x:features"), sub: txt(node("x:features").querySelector(".ng-sub")) } : null,
    acc: node("s:acceptance_tests_passing") ? { ring: !!node("s:acceptance_tests_passing").querySelector(".im-ring"), pin: !!node("s:acceptance_tests_passing").querySelector(".im-pin"), tags: tags("s:acceptance_tests_passing") } : null,
    removedEdge: !!q('#diagram g.ng-edge[data-id^="gone:"]'), removedLabel: txt(q('#diagram g.ng-label[data-id^="gone:"]')),
    newEdge: !!q("#diagram g.ng-edge.im-new-edge"),
    switch: sw ? { on: sw.classList.contains("on"), text: txt(sw) } : null,
    expectedGroup: qa("#stocks tr.im-exprow").map((r) => txt(r.cells[0])), nstocks: txt(q("#nstocks")),
    groups: qa("#stocks tr.im-group").map(txt),
    changes: q("#im-changes") ? { head: txt(q("#im-changes h2 span")), count: txt(q("#im-changes h2 .count")), rows: qa("#im-changes .im-chg[data-sign]").map((r) => ({ sign: r.dataset.sign, text: txt(r.children[1]), controls: [...r.querySelectorAll("button[data-control]")].map((b) => b.dataset.control) })),
      foot: txt(q("#im-changes .im-foot")) } : null,
    legend: qa("#legend .im-lg").map(txt),
    declaredFlow: txt(q('#diagram g.ng-label[data-id^="x:flow:"]')), predictedFlow: txt(q('#diagram g.ng-label[data-id^="x:pred:"]')),
    simulated: node("s:features_placeholder") ? { hatch: !!node("s:features_placeholder").querySelector(".im-hatch"), tags: tags("s:features_placeholder") } : null,
    tableMarks: { stocks: qa("#stocks .im-t-new").length, flows: qa("#flows .im-t-new").length, gone: qa("#flows tr.im-gone").map(txt) },
    drawer: open ? { head: txt(q("#drawer h3")), options: qa("#drawer .im-opt").map((o) => ({ key: o.dataset.option, on: o.classList.contains("on"), text: txt(o) })),
      recording: txt(q("#drawer .im-recline")), spark: !!q("#drawer svg.im-spark"), script: txt(q("#im-script summary")), peek: txt(q("#im-script .im-peek")),
      readOnly: qa("#drawer .im-radio").every((r) => r.getAttribute("aria-disabled") === "true"),
      expect: q("#drawer .im-expect") ? { on: q("#drawer .im-expect").classList.contains("on"), text: txt(q("#drawer .im-expect")) } : null } : null,
  };
}

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "puppeteer_dev_chrome_profile-intended-"));
  const b = await puppeteer.launch({ executablePath: CH, headless: true, userDataDir: profile, args: ["--no-first-run", "--hide-scrollbars"] });
  const report = {};
  let page = null, errors = [];
  const fresh = async (url) => {
    if (page) await page.close();
    page = await b.newPage(); errors = [];
    page.on("pageerror", (e) => errors.push("page error: " + e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
    page.on("response", (r) => { if (r.status() >= 400) errors.push(`${r.status()}: ${r.url()}`); });
    page.on("requestfailed", (r) => { if (!/cdn|cdnjs|jsdelivr/.test(r.url())) errors.push("request failed: " + r.url()); });
    await page.setViewport({ width: 1440, height: 900 });
    await page.evaluateOnNewDocument((lay) => {
      try { localStorage.clear(); const at = {}; for (const [id, x, y] of lay) at[id] = [x, y, 1]; localStorage.setItem("orchestra.netgraph.dynamics.v2", JSON.stringify(at)); } catch (e) {}
    }, LAYOUT);
    await page.goto(url + "/dynamics", { waitUntil: "networkidle0", timeout: 60000 });
    try { await page.waitForFunction(() => typeof MODEL !== "undefined" && MODEL && document.querySelector("#diagram svg g.ng-node"), { timeout: 60000, polling: 200 }); }
    catch (e) { throw new Error(`${url}: the diagram never drew: ${errors.join("; ")} · ${await page.evaluate(() => document.querySelector("#diagram").textContent.slice(0, 300))}`); }
    await sleep(2500);                                   // the history (sparklines) arrives and the graph settles
    await page.evaluate(() => Live.refresh()); await sleep(800);
    // every stock on the diagram, as in the mockups: the viewer ticks "stocks that only fill" (DONE, files, commits)
    await page.evaluate(() => { if (!window.SHOW_ACC) { window.SHOW_ACC = true; draw(); } }); await sleep(1500);
    await page.click("#diagram .ng-fit"); await sleep(900);          // the whole graph in view, as a person would press "fit"
  };
  const shoot = async (f) => {
    await sleep(500);
    await page.screenshot({ path: path.join(OUT, `${f}-1440x900.png`) });
    await page.screenshot({ path: path.join(OUT, `${f}.png`), fullPage: true });
    // the browser asks for /favicon.ico by itself, which the server has not got: not the page's error
    const fav = errors.filter((e) => /favicon\.ico$/.test(e)).length;
    let skip = fav;
    const errs = errors.filter((e) => !/favicon\.ico$/.test(e) && !(skip > 0 && /Failed to load resource: .*404/.test(e) && skip--));
    report[f] = { ...(await page.evaluate(inspect)), errors: errs };
  };
  try {
    for (const f of want) {
      if (f === "D1") {
        await fresh(D1_URL);
        await page.click('#diagram g.ng-node[data-id="x:features"]');
        await page.waitForFunction(() => document.querySelector("#im-script summary, #im-script .muted:not(:empty)") && !/reading/.test(document.querySelector("#im-script").textContent), { timeout: 15000 });
        await shoot(f);
      } else if (f === "D1-closed") {
        if (!page || !page.url().startsWith(D1_URL)) await fresh(D1_URL);
        await page.evaluate(() => closeDrawer()); await page.mouse.move(4, 4); await shoot(f);
      } else if (f === "D2") {
        await fresh(D2_URL); await shoot(f);
      } else if (f === "D3") {
        if (!page || !page.url().startsWith(D2_URL)) await fresh(D2_URL);
        // the owner presses "expect" on the new stock, then turns the changes off and opens it
        await page.click('#im-changes .im-chg[data-sign="+"][data-key="acceptance_tests_passing"] button[data-control="expect"]');
        await page.waitForFunction(() => document.querySelector('#im-changes .im-chg[data-key="acceptance_tests_passing"] button[data-control="unexpect"]'), { timeout: 15000 });
        report.expectClicked = await page.evaluate(() => MODEL.intended.marks.stocks.acceptance_tests_passing);
        await page.click("#im-since");
        await page.waitForFunction(() => !document.querySelector("#im-changes") && !document.querySelector("#im-since.on"), { timeout: 15000 });
        await sleep(800);
        await page.evaluate(() => Live.openStock("acceptance_tests_passing"));
        await sleep(1500);
        await shoot(f);
      } else if (f === "D-extras") {
        await fresh(EXTRAS_URL); await shoot(f);
      } else if (f === "D3-closed") {
        await page.evaluate(() => closeDrawer()); await shoot(f);
      }
      process.stderr.write(`${f}: ${path.join(OUT, f + ".png")}\n`);
    }
  } finally {
    await b.close(); fs.rmSync(profile, { recursive: true, force: true });
  }
  process.stdout.write(JSON.stringify(report) + "\n");
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
