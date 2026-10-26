export const meta = {
  name: 'ux-review',
  description: 'A user-experience review panel for a running Orchestra: personas walk the UI live with screenshots, experts judge the screenshots, a judge triages, an implementor fixes; repeats until the panel is satisfied',
  whenToUse: 'After UI work in Orchestra or a plugin, or before a release. Needs a demo that one command starts.',
  phases: [
    { title: 'Walk', detail: 'personas use the running UI and log every friction point' },
    { title: 'Judge', detail: 'information design, consistency and honesty experts over the screenshots' },
    { title: 'Triage', detail: 'merge, confirm against the code, drop taste' },
    { title: 'Fix', detail: 'the implementor applies the work list and commits' },
  ],
}

// args: {
//   brief: path to the shared brief every agent reads first (required)
//   repo: the repository under review (required)
//   start: the one command that starts the demo and prints its URL (required)
//   stop: how to stop it (default: Ctrl-C / kill the process group you started)
//   pages: list of paths to look at (default: Orchestra's pages plus whatever /api/plugins lists)
//   out: directory for screenshots and journey logs (required)
//   rounds: max review→fix rounds (default 2)
//   fix: whether to run the implementor (default true)
//   personas: override the persona list
// }
const a = args || {}
if (!a.brief || !a.repo || !a.start || !a.out) throw new Error('ux-review needs args.brief, args.repo, args.start, args.out')
const PRE = `Read ${a.brief} first, all of it; every constraint in it binds you.\n\n`
const ROUNDS = a.rounds || 2
const PAGES = a.pages || ['/', '/machines', '/dynamics', '/core', 'and every page /api/plugins lists']

const PERSONAS = a.personas || [
  { key: 'new-operator', who: 'an operator who has never seen Orchestra, told only "the system is at this URL; is it healthy and what is it doing?"' },
  { key: 'on-call', who: 'an SRE on call at 3am who was paged that work is stuck; they need to find what is stuck, why, and who or what is supposed to act, in under two minutes' },
  { key: 'modeller', who: 'the owner, reviewing the system dynamics model: are the stocks and flows the ones they expect, where does each number come from, can they trust it' },
  { key: 'machine-author', who: 'a developer who wrote a program that fills a role and wants to see it appear as a machine, watch it take work, read its events, and know when it misbehaves' },
]

const FINDINGS = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    findings: { type: 'array', items: { type: 'object', properties: {
      title: { type: 'string' }, page: { type: 'string' }, element: { type: 'string' },
      severity: { type: 'string', enum: ['must', 'should', 'nice'] },
      what: { type: 'string' }, why: { type: 'string' }, fix: { type: 'string' },
      screenshot: { type: 'string', description: 'path of the screenshot that shows it' },
    }, required: ['title', 'page', 'element', 'severity', 'what', 'why', 'fix'] } },
  },
  required: ['summary', 'findings'],
}
const TRIAGE = {
  type: 'object',
  properties: {
    clean: { type: 'boolean' },
    work: { type: 'array', items: { type: 'object', properties: {
      title: { type: 'string' }, where: { type: 'string' }, severity: { type: 'string', enum: ['must', 'should'] },
      instruction: { type: 'string' }, from: { type: 'string' },
    }, required: ['title', 'where', 'severity', 'instruction', 'from'] } },
    dropped: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, why: { type: 'string' } }, required: ['title', 'why'] } },
  },
  required: ['clean', 'work', 'dropped'],
}
const REPORT = {
  type: 'object',
  properties: {
    changed: { type: 'array', items: { type: 'string' } }, verified: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'object', properties: { item: { type: 'string' }, why: { type: 'string' } }, required: ['item', 'why'] } },
    commits: { type: 'array', items: { type: 'string' } }, notes: { type: 'string' },
  },
  required: ['changed', 'verified', 'skipped', 'commits', 'notes'],
}

const HYGIENE = `Start the demo yourself with: ${a.start}. Wait for the URL to serve. Take screenshots with the headless browser (puppeteer; the brief says where it is installed) into ${a.out}/<your key>/round<N>/, one per page and one per drawer or dialog you open, at 1440×900 and at 390×844 (phone). When done: ${a.stop || 'stop every process you started (the process group of the start command)'} and kill your headless Chrome (pkill -f puppeteer_dev_chrome_profile). Never kill Playwright Chromes. You are read-only on the repository; write only under ${a.out}.`

let history = []
for (let round = 1; round <= ROUNDS; round++) {
  log(`ux-review round ${round}: ${PERSONAS.length} personas walk the UI`)
  const walks = (await parallel(PERSONAS.map((p) => () =>
    agent(PRE + `You are ${p.who}. Use the running UI as that person would, without reading the code first: go to ${PAGES.join(', ')}; click what looks clickable; try to answer your questions. Keep a journey log in ${a.out}/${p.key}/round${round}/journey.md: every step, what you expected, what you saw, how long it took you to understand, what you misunderstood, what you could not find. Then read enough of the code (${a.repo}, static/ and the API it reads) to say where each problem comes from. ${HYGIENE}` +
      (history.length ? `\n\nEarlier rounds fixed: ${JSON.stringify(history[history.length - 1].work.map((w) => w.title))}. Check those are fixed for you as a user; look for what remains.` : '') +
      `\n\nReturn findings in the schema: "must" means a user would be misled or stuck; "should" means a careful product owner would insist; "nice" is taste.`,
      { label: `${p.key} r${round}`, phase: 'Walk', schema: FINDINGS, effort: 'high' })))).filter(Boolean)
  const EXPERTS = [
    { key: 'information-design', who: 'an information-design expert (Tufte, Few): hierarchy, density, labels, units, colour used for meaning only, state readable at a glance, nothing decorative, nothing truncated that matters, consistent names for the same thing on every page' },
    { key: 'honesty', who: 'an expert in operator tools whose only question is "does the UI lie?": stale data shown as live, "running" for a process that is gone, a count that excludes something, a chart whose axis hides the shape, a badge whose meaning the user cannot discover, an empty state that does not say why it is empty' },
    { key: 'consistency', who: 'a front-end reviewer: the same component drawn two ways, CSS from one plugin leaking into another or into Orchestra, broken layout at phone width, keyboard access, flicker on refresh, console errors (read them in the headless browser)' },
  ]
  log(`ux-review round ${round}: experts judge ${walks.length} journeys`)
  const judged = (await parallel(EXPERTS.map((e) => () =>
    agent(PRE + `You are ${e.who}. Read every journey log and screenshot under ${a.out}/*/round${round}/ (the personas' walks), then look yourself where you need to (${HYGIENE}). Return findings in the schema with the screenshot that shows each.`,
      { label: `${e.key} r${round}`, phase: 'Judge', schema: FINDINGS, effort: 'high' })))).filter(Boolean)
  const all = [...walks, ...judged].flatMap((r) => r.findings)
  log(`ux-review round ${round}: ${all.length} findings`)
  const triage = await agent(PRE + `You are the triage judge for a UX review of ${a.repo}. Merge duplicates (the same problem seen by several personas is one item, with their count as evidence of weight), confirm each against the code and the screenshot, drop taste and anything the brief puts out of scope or reserves for the owner. The work list must be executable by an implementor who did not see the reviews: name the file, the element, the change.\n\nFINDINGS:\n${JSON.stringify(all, null, 1)}`,
    { label: `triage r${round}`, phase: 'Triage', schema: TRIAGE, effort: 'high' })
  if (!triage) break
  history.push(triage)
  if (triage.clean || !triage.work.length) { log(`ux-review: clean after round ${round}`); break }
  if (a.fix === false) break
  const fix = await agent(PRE + `You are the implementor for ${a.repo}. Apply this UX work list, item by item, then start the demo (${a.start}) and check each fix in the headless browser yourself with a before/after screenshot into ${a.out}/fix/round${round}/. Keep each change in this repository's scope; if a fix belongs in another repository (Orchestra's own page versus a plugin's), say so in skipped. Run the test suites and ruff, check the results, commit locally (message ends with the Co-Authored-By line from the brief). Do not push. Stop what you started; kill your Chrome.\n\nWORK LIST:\n${JSON.stringify(triage.work, null, 1)}`,
    { label: `fix r${round}`, phase: 'Fix', schema: REPORT, effort: 'high' })
  if (fix) log(`ux-review fix r${round}: ${fix.commits.length} commit(s), ${fix.skipped.length} skipped`)
}
return { rounds: history.length, last: history[history.length - 1] || null, clean: !!(history.length && history[history.length - 1].clean) }
