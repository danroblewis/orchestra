// Capture what the live /dynamics and /machines pages fetch, as fixtures for the mockups.
//   PC=<puppeteer-core> CH=<chrome> TOK=<web token> BASE=http://127.0.0.1:8094 OUT=mockups/fixtures node capture.cjs
// Logs in through /login (a cookie, so the token never rides on a CDN request), loads each page,
// records every same-origin response (path + query -> body), opens a couple of machine dialogs,
// and saves the pages' served HTML and the settled graph layouts (localStorage).
const puppeteer = require(process.env.PC);
const fs = require("fs"), path = require("path");
const { BASE, OUT, TOK, CH } = process.env;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: CH, headless: true, userDataDir: "/tmp/puppeteer_dev_chrome_profile-mockcap", args: ["--no-first-run"] });
  const p = await b.newPage(); await p.setViewport({ width: 1440, height: 900 });
  const got = {};
  p.on("response", async (r) => {
    const u = new URL(r.url());
    if (u.origin !== BASE || r.request().method() !== "GET") return;
    const key = u.pathname + u.search;
    try { const t = await r.text(); got[key] = { status: r.status(), type: r.headers()["content-type"] || "", body: t }; } catch (e) {}
  });
  await p.goto(BASE + "/login?next=/dynamics");
  await p.type("input[name=token]", TOK);
  await Promise.all([p.waitForNavigation(), p.keyboard.press("Enter")]);
  await sleep(20000);                                  // ELK + the polish worker settle
  const dynLayout = await p.evaluate(() => localStorage.getItem("orchestra.netgraph.dynamics.v2"));
  await p.evaluate(() => { const s = MODEL.stocks[0]; Live.openStock(s.id); }); await sleep(3000); await p.evaluate(() => closeDrawer());
  await p.goto(BASE + "/machines"); await sleep(12000);
  const evLayout = await p.evaluate(() => ({ machines: localStorage.getItem("orchestra.netgraph.machines.machines"), events: localStorage.getItem("orchestra.netgraph.machines.events") }));
  for (const id of (process.env.MACHINES || "worker,merge_gate,coordinator,reviewer").split(",")) {
    await p.evaluate((i) => openMachine(i), id); await sleep(2500); await p.evaluate(() => closeMachine && closeMachine());
  }
  await p.evaluate(() => setMode("events")); await sleep(12000);
  const evLayout2 = await p.evaluate(() => localStorage.getItem("orchestra.netgraph.machines.events"));
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, "capture.json"), JSON.stringify(got, null, 1));
  fs.writeFileSync(path.join(OUT, "layouts.json"), JSON.stringify({ capturedAt: Date.now() / 1000, "dynamics.v2": dynLayout, "machines.machines": evLayout.machines, "machines.events": evLayout2 }, null, 1));
  console.log(Object.keys(got).length + " responses: " + Object.keys(got).join(" "));
  await b.close();
})();
