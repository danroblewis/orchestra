// Render the mockup frames to PNGs: full page and a 1440×900 view of each.
//   node mockups/tools/render.cjs [frame ...]        (from the repository root)
// Starts tools/serve.py on PORT (default 8187), opens each frame in headless Chrome for Testing,
// waits for the frame to say it is finished (MOCK.done), and writes out/<frame>.png and
// out/<frame>-1440x900.png. PC (puppeteer-core) and CH (Chrome) default to the ones in ~/.npm and
// ~/.cache/puppeteer.
const { spawn } = require("child_process");
const fs = require("fs"), path = require("path"), os = require("os");
const HOME = os.homedir();
const PC = process.env.PC || fs.readdirSync(path.join(HOME, ".npm/_npx")).map((d) => path.join(HOME, ".npm/_npx", d, "node_modules/puppeteer-core"))
  .filter((d) => fs.existsSync(d)).sort((a, b) => require(b + "/package.json").version.localeCompare(require(a + "/package.json").version, undefined, { numeric: true }))[0];
const CH = process.env.CH || (() => { const base = path.join(HOME, ".cache/puppeteer/chrome"); const v = fs.readdirSync(base).sort().pop();
  return path.join(base, v, "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"); })();
const puppeteer = require(PC);
const PORT = +(process.env.PORT || 8187), ROOT = path.resolve(__dirname, "../.."), OUT = path.join(ROOT, "mockups/out");
const FRAMES = { layout_dynamics: "/dynamics?frame=layout_dynamics", layout_machines: "/machines?frame=layout_machines", base_dynamics: "/dynamics", D1: "/dynamics?frame=D1", D2: "/dynamics?frame=D2", D3: "/dynamics?frame=D3",
  base_machines: "/machines", E1: "/machines?frame=E1", E2: "/machines?frame=E2", E3: "/machines?frame=E3", E4: "/machines?frame=E4" };
const urlOf = (f) => FRAMES[f] || (f.startsWith("D") ? `/dynamics?frame=${f}` : `/machines?frame=${f}`);
const want = process.argv.slice(2).length ? process.argv.slice(2) : ["D1", "D1-closed", "D2", "D3", "D3-closed", "E1", "E2", "E3", "E3-continuous", "E3-external", "E4"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const server = spawn("python3", [path.join(ROOT, "mockups/tools/serve.py"), String(PORT)], { stdio: "inherit" });
  await sleep(700);
  fs.mkdirSync(OUT, { recursive: true });
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "puppeteer_dev_chrome_profile-mockups-"));
  const b = await puppeteer.launch({ executablePath: CH, headless: true, userDataDir: profile, args: ["--no-first-run", "--hide-scrollbars"] });
  try {
    for (const f of want) {
      const p = await b.newPage();
      p.on("pageerror", (e) => console.log(`${f} page error: ${e.message}`));
      p.on("console", (m) => { if (["error", "warning"].includes(m.type())) console.log(`${f} console: ${m.text()}`); });
      await p.setViewport({ width: 1440, height: 900 });
      await p.goto(`http://127.0.0.1:${PORT}${urlOf(f)}`, { waitUntil: "networkidle0", timeout: 60000 });
      await p.waitForFunction(() => window.MOCK && MOCK.done, { timeout: 60000, polling: 200 });
      await sleep(400);
      if (f.startsWith("layout_")) {            // a layout pass: keep where the graph put everything, for every frame after
        const key = f === "layout_dynamics" ? "dynamics.v2" : "machines.events";
        const at = await p.evaluate((k) => localStorage.getItem("orchestra.netgraph." + k), key);
        const lf = path.join(ROOT, "mockups/fixtures/layouts.json"), lay = JSON.parse(fs.readFileSync(lf, "utf8"));
        lay[key] = at; fs.writeFileSync(lf, JSON.stringify(lay, null, 1));
        require("child_process").execFileSync("python3", [path.join(ROOT, "mockups/tools/split.py")]);
        console.log(`${f}: saved the layout of ${Object.keys(JSON.parse(at)).length} nodes`);
      }
      const missing = await p.evaluate(() => MOCK.missing);
      if (missing.length) console.log(`${f}: not in the fixtures: ${[...new Set(missing)].join(" ")}`);
      await p.screenshot({ path: path.join(OUT, `${f}-1440x900.png`) });
      await p.screenshot({ path: path.join(OUT, `${f}.png`), fullPage: true });
      console.log(`${f}: out/${f}.png, out/${f}-1440x900.png`);
      await p.close();
    }
  } finally { await b.close(); server.kill(); fs.rmSync(profile, { recursive: true, force: true }); }
})();
