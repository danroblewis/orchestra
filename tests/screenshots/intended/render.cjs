// Render the Machines page's frames E1–E4 from the real web app, check each frame's DOM, and write
// tests/screenshots/intended/<frame>.png (full page) and <frame>-1440x900.png (the first screen).
//   node tests/screenshots/intended/render.cjs [frame ...]       (from the repository root)
// It is run by hand, and by no test (the unit tests check the same frames' API answers,
// tests/unit/test_intended_frames.py).
// Each frame: serve_frame.py serves a seeded project (tests/unit/machine_frames.py) on its own port; headless
// Chrome for Testing logs in with the project's token, opens /machines#<machine> (the panel open on
// it), with the map pinned where the mockups pinned it (mockups/fixtures/layouts.json and the
// places in mockups/additions.js), waits for it to settle, checks the frame's structure and that
// nothing was logged as an error. Exits 1 on any failed check. PC (puppeteer-core) and CH (Chrome)
// default to the ones in ~/.npm/_npx and ~/.cache/puppeteer, as mockups/tools/render.cjs.
const { spawn } = require("child_process");
const fs = require("fs"), path = require("path"), os = require("os"), readline = require("readline");
const HOME = os.homedir(), ROOT = path.resolve(__dirname, "../../.."), OUT = __dirname;
const PC = process.env.PC || fs.readdirSync(path.join(HOME, ".npm/_npx")).map((d) => path.join(HOME, ".npm/_npx", d, "node_modules/puppeteer-core"))
  .filter((d) => fs.existsSync(d)).sort((a, b) => require(b + "/package.json").version.localeCompare(require(a + "/package.json").version, undefined, { numeric: true }))[0];
const CH = process.env.CH || (() => { const base = path.join(HOME, ".cache/puppeteer/chrome"); const v = fs.readdirSync(base).sort().pop();
  return path.join(base, v, "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"); })();
const puppeteer = require(PC);
// a free port for each frame's server (never a fixed one: other work may be serving there)
const freePort = () => new Promise((resolve) => { const s = require("net").createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
const FRAMES = { E1: "feature_count_improver", E2: "feature_count_improver", E3: "nightly_metrics", "E3-continuous": "nightly_metrics",
  "E3-external": "nightly_metrics", E4: "sail" };
const want = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(FRAMES);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// the map as the mockups pinned it
function layout() {
  const lay = JSON.parse(JSON.parse(fs.readFileSync(path.join(ROOT, "mockups/fixtures/layouts.json"), "utf8"))["machines.events"]);
  const at = [["m:orchestra-host", -150, 40], ["m:planner", 60, 60], ["m:coordinator", 330, 300], ["m:supervisor", 60, 520], ["m:worker", 600, 60],
    ["m:reviewer", 600, 560], ["m:merge_gate", 330, 640], ["m:feature_count_improver", 935, 330], ["m:nightly_metrics", 930, 600], ["m:sail", 960, 330],
    ["ev:request.done", 200, 150], ["ev:request.refused", -80, 170], ["ev:ticket.created", 150, 300], ["ev:task.attention_needed", 170, 420],
    ["ev:group:ev:gate.conflict+ev:work.requested", 150, 470], ["ev:gate.conflict", 150, 470], ["ev:orchestra.prediction.judged", 330, 170],
    ["ev:task.assigned", 470, 330], ["ev:task.released", 470, 230], ["ev:review.requested", 620, 300], ["ev:review.approved", 480, 660],
    ["ev:gate.landed", 200, 600], ["ev:task.reported", 790, 120], ["ev:session.settled", 790, 220], ["ev:changes.requested", 790, 330],
    ["ev:gate.rejected", 790, 430], ["ev:work.requested", 560, 440], ["ev:work.improvement_proposed", 880, 530], ["ev:summary.requested", 790, 600],
    ["ev:summary.ready", 1000, 700]];
  for (const [id, x, y] of at) lay[id] = [x, y, 1];
  return JSON.stringify(lay);
}

// the structural checks: each returns a list of failures, run in the page
const CHECKS = {
  common: (id) => {
    const f = [], side = document.getElementById("im-side"), q = (s) => side.querySelector(s);
    if (!document.getElementById("im-row").classList.contains("open")) f.push("the panel is not open");
    if (side.querySelector("input, textarea, select")) f.push("the panel has an input: every field is read-only");
    if (!side.querySelector(".im-ask")) f.push("no 'ask the Supervisor' affordance");
    const node = document.querySelector(`#evsvg-host g.ng-node[data-id="m:${id}"]`);
    if (!node) f.push(`no node m:${id}`); else if (node.matches(".ng-dim,.ng-shade1,.ng-shade2")) f.push("the open machine is shaded");
    const card = document.querySelector("#cards .panel");
    if (!card || card.dataset.id !== id) f.push(`its card is not first (${card && card.dataset.id})`);
    if (!q(".im-head") || !q(".im-id")) f.push("no panel head");
    return f;
  },
  shades: () => {
    const f = [], n = (c) => document.querySelectorAll(`#evsvg-host g.ng-node.${c}`).length;
    if (!n("ng-shade1")) f.push("no node at .7 (one hop)"); if (!n("ng-shade2")) f.push("no node at .45 (two hops)"); if (!n("ng-dim")) f.push("nothing dimmed");
    const op = (sel) => { const e = document.querySelector(sel); return e ? +getComputedStyle(e).opacity : null; };
    if (op("#evsvg-host g.ng-node.ng-shade1") !== 0.7) f.push("one hop is not at .7");
    if (op("#evsvg-host g.ng-node.ng-shade2") !== 0.45) f.push("two hops are not at .45");
    return f;
  },
  E1: () => {
    const f = [], side = document.getElementById("im-side"), t = side.textContent;
    for (const s of ["Feature Count Improver", "unconfirmed", "proposed by the Supervisor", "create a new Universal Machine", "Invariants", "Steps", "Uses",
      "Expected effect", "waits for a series", "nobody listens for it yet", "horizon 7 days"]) if (!t.includes(s)) f.push(`panel lacks "${s}"`);
    if (side.querySelectorAll(".im-acts button").length !== 2) f.push("no confirm / discard");
    if ((side.querySelector(".im-seg button.on") || {}).textContent !== "Universal") f.push("kind is not Universal");
    const on = [...side.querySelectorAll(".im-ind span.on")].map((e) => e.textContent);
    if (!on.includes("orchestra") || !on.includes("continuous")) f.push(`indicators: ${on}`);
    if ([...side.querySelectorAll(".im-tag")].filter((e) => e.textContent === "a guess").length !== 2) f.push("not two guesses");
    const steps = [...side.querySelectorAll("h4")].find((h) => h.textContent.startsWith("Steps"));
    if (!steps || !steps.nextElementSibling || steps.nextElementSibling.querySelectorAll("li").length !== 5) f.push("not five steps");
    if (side.querySelectorAll(".im-pred").length !== 4) f.push("not four expected-effect rows");
    const node = document.querySelector('g.ng-node[data-id="m:feature_count_improver"]');
    if (!node || !node.classList.contains("im-proposed") || !node.textContent.toLowerCase().includes("unconfirmed")) f.push("node not drawn unconfirmed");
    const ev = document.querySelector('g.ng-node[data-id="ev:work.improvement_proposed"]');
    if (!ev) f.push("its declared event type is not drawn"); else { if (!ev.textContent.includes("declared")) f.push("its event type is not tagged declared"); if (ev.matches(".ng-dim,.ng-shade1,.ng-shade2")) f.push("its event type is shaded"); }
    const card = document.querySelector('#cards .panel[data-id="feature_count_improver"]');
    if (!card || !card.classList.contains("im-card") || !card.textContent.includes("unconfirmed")) f.push("card lacks the unconfirmed badge");
    return f;
  },
  E2: () => {
    const f = [], side = document.getElementById("im-side"), t = side.textContent;
    for (const s of ["changed just now", "was continuous", "rewritten just now", "daily at 00:00", "America/Los_Angeles", "+ added just now", "− removed"])
      if (!t.includes(s)) f.push(`panel lacks "${s}"`);
    if (document.querySelectorAll("g.ng-edge.im-gone-edge").length !== 2) f.push(`gone links: ${document.querySelectorAll("g.ng-edge.im-gone-edge").length}`);
    if (document.querySelectorAll("g.ng-edge.im-add-edge").length < 3) f.push("fewer than three new links");
    const tags = [...document.querySelectorAll("#evsvg-host .ng-tag")].map((e) => e.textContent);
    if (tags.filter((x) => x === "+ new link").length < 2) f.push("no '+ new link' tags"); if (tags.filter((x) => x === "− link removed").length < 1) f.push("no '− link removed' tag");
    if (!tags.includes("changed just now")) f.push("node lacks 'changed just now'");
    for (const ty of ["session.settled", "task.reported"]) { const n = [...document.querySelectorAll("#evsvg-host g.ng-node")].find((g) => g.textContent.includes(ty));
      if (n && n.matches(".ng-dim,.ng-shade1,.ng-shade2")) f.push(`removed link's ${ty} is shaded`); }
    if (!document.querySelector('#cards .panel[data-id="feature_count_improver"] .im-chip-gone')) f.push("card lacks the removed chips");
    return f;
  },
  E3: (id, mode) => {
    const f = [], side = document.getElementById("im-side"), t = side.textContent;
    for (const s of ["Nightly metrics", "added by you", "Declared as engaged"]) if (!t.includes(s)) f.push(`panel lacks "${s}"`);
    if ((side.querySelector(".im-seg button.on") || {}).textContent !== "Programmatic") f.push("kind is not Programmatic");
    const on = [...side.querySelectorAll(".im-ind span.on")].map((e) => e.textContent), label = (s) => [...side.querySelectorAll(".im-tabbody .im-fl")].some((e) => e.textContent === s);
    const want = { adhoc: ["orchestra", "ad hoc"], continuous: ["orchestra", "continuous"], external: ["external", "continuous"] }[mode];
    for (const w of want) if (!on.includes(w)) f.push(`indicator ${w} not on (${on})`);
    const fields = { adhoc: ["command", "arguments", "environment", "stdin", "exit"], continuous: ["command", "protocol", "listens on", "send", "receive", "health"], external: ["source", "runs where", "log"] }[mode];
    for (const s of fields) if (!label(s)) f.push(`no ${s} row`);
    if (mode === "external" && label("command")) f.push("an external machine shows a command");
    if (mode === "adhoc" && [...side.querySelectorAll(".im-ask")].filter((e) => e.textContent.includes("add one")).length !== 2) f.push("not two 'ask the Supervisor to add one'");
    if (!document.querySelector('g.ng-node[data-id="m:nightly_metrics"].im-proposed')) f.push("node not unconfirmed");
    return f;
  },
  E4: () => {
    const f = [], side = document.getElementById("im-side"), t = side.textContent;
    for (const s of ["SAIL", "declared · never heard", "declared by you", "none heard on the bus", "Measured by", "company_prom", "runner-3", "Flows (hypotheses)", "not readable"])
      if (!t.includes(s)) f.push(`panel lacks "${s}"`);
    if (side.querySelectorAll("table.im-meas tr").length !== 4) f.push("the measured table has not three rows");
    const node = document.querySelector('g.ng-node[data-id="m:sail"]');
    if (!node || !node.classList.contains("im-unheard")) f.push("node is not the outline"); else if (node.querySelector(".ng-halo")) f.push("node has a halo");
    if ([...document.querySelectorAll("#evsvg-host g.ng-edge")].some((e) => (e.dataset.id || "").includes("m:sail"))) f.push("node has links");
    if (!node || !node.textContent.includes("declared · measured")) f.push("node not tagged 'declared · measured'");
    const card = document.querySelector('#cards .panel[data-id="sail"]'), ct = card ? card.textContent : "";
    for (const s of ["never heard · measured by 1 instrument · 3 instances (last hour)", "last measured", "measured ×3", "declared · never heard"]) if (!ct.includes(s)) f.push(`card lacks "${s}"`);
    if (!document.querySelector("#evsvg-host g.ng-node.ng-dim")) f.push("the rest is not shadowed");
    return f;
  },
};
const checksOf = (frame) => frame === "E1" ? [CHECKS.E1, CHECKS.shades] : frame === "E2" ? [CHECKS.E2, CHECKS.shades] : frame === "E4" ? [CHECKS.E4] : [CHECKS.E3];

function serve(frame, port) {
  const proc = spawn("uv", ["run", "--no-sync", "python", path.join(__dirname, "serve_frame.py"), frame, String(port)],
    { cwd: ROOT, env: { ...process.env, PYTHONPATH: path.join(ROOT, "tests/unit") }, stdio: ["ignore", "pipe", "inherit"] });
  return new Promise((resolve, reject) => {
    readline.createInterface({ input: proc.stdout }).once("line", async (l) => {
      const srv = { proc, ...JSON.parse(l) };
      for (let i = 0; i < 100; i++) { try { if ((await fetch(srv.url + "/health")).ok) return resolve(srv); } catch (e) { /* not up yet */ } await sleep(200); }
      reject(new Error(`serve_frame ${frame} never answered`));
    });
    proc.once("exit", (c) => reject(new Error(`serve_frame ${frame} exited ${c}`)));
  });
}

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "puppeteer_dev_chrome_profile-intended-"));
  const b = await puppeteer.launch({ executablePath: CH, headless: true, userDataDir: profile, args: ["--no-first-run", "--hide-scrollbars"] });
  let failed = 0;
  try {
    for (const frame of want) {
      const id = FRAMES[frame], port = await freePort(), srv = await serve(frame, port), errors = [];
      try {
        const ctx = await b.createBrowserContext(), p = await ctx.newPage();
        p.on("pageerror", (e) => errors.push(`page error: ${e.message}`));
        p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(`console: ${m.text()}`); });
        let loggedIn = false;
        p.on("response", (r) => { if (loggedIn && r.status() >= 400 && !/favicon/.test(r.url())) errors.push(`${r.status()} ${r.url()}`); });
        await p.setViewport({ width: 1440, height: 900 });
        await p.evaluateOnNewDocument((lay) => { try { localStorage.setItem("orchestra.netgraph.machines.events", lay); localStorage.setItem("orchestra.evmap.mode", "events"); } catch (e) {} }, layout());
        await p.goto(`${srv.url}/login`, { waitUntil: "domcontentloaded" });
        await p.type("#token", srv.token);
        await Promise.all([p.waitForNavigation({ waitUntil: "domcontentloaded" }), p.keyboard.press("Enter")]);
        loggedIn = true;
        await p.goto(`${srv.url}/machines#${id}`, { waitUntil: "networkidle2", timeout: 60000 });
        await p.waitForFunction((i) => document.querySelector("#im-row.open") && document.querySelector(`g.ng-node[data-id="m:${i}"]`)
          && [...document.querySelectorAll("#cards .panel")].length >= 7, { timeout: 60000, polling: 250 }, id);
        await sleep(3500);                                  // the new nodes settle
        const fails = [];
        for (const c of [CHECKS.common, ...checksOf(frame)]) fails.push(...await p.evaluate(`(${c.toString()})(${JSON.stringify(id)}, ${JSON.stringify(frame.split("-")[1] || "adhoc")})`));
        fails.push(...errors.filter((e) => !/favicon/.test(e)));
        await p.screenshot({ path: path.join(OUT, `${frame}-1440x900.png`) });
        await p.evaluate(() => { const s = document.getElementById("im-side"); s.style.maxHeight = "none"; s.style.position = "static"; });   // the whole panel, on the full page
        await p.screenshot({ path: path.join(OUT, `${frame}.png`), fullPage: true });
        console.log(`${frame}: ${fails.length ? "FAILED\n  " + fails.join("\n  ") : "ok"} · ${path.relative(ROOT, path.join(OUT, frame + ".png"))}`);
        failed += fails.length ? 1 : 0;
        await ctx.close();
      } finally { srv.proc.kill(); }
    }
  } finally { await b.close(); fs.rmSync(profile, { recursive: true, force: true }); }
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
