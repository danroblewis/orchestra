export const meta = {
  name: 'layered-review',
  description: 'Four independent reviews of one repository (code, requirements, design, user experience), a triage judge that confirms findings against the code, and an implementor that applies the work list; repeats until nothing of weight remains',
  whenToUse: 'After an implementation phase on Orchestra or a plugin. Pass the repo, its scope in one sentence, and the brief.',
  phases: [
    { title: 'Review', detail: 'code, requirements, design, UX in parallel' },
    { title: 'Triage', detail: 'merge, confirm, drop out-of-scope' },
    { title: 'Fix', detail: 'the implementor applies the work list and commits' },
  ],
}

// args: { brief, repo, scope, out, rounds?, lenses?, demo?, fixExtra?, fix? }
const a = args || {}
if (!a.brief || !a.repo || !a.scope || !a.out) throw new Error('layered-review needs args.brief, args.repo, args.scope, args.out')
const PRE = `Read ${a.brief} first, all of it; every constraint in it binds you.\n\n`
const ROUNDS = a.rounds || 3
const FINDINGS = { type: 'object', properties: { summary: { type: 'string' }, findings: { type: 'array', items: { type: 'object', properties: {
  title: { type: 'string' }, where: { type: 'string' }, severity: { type: 'string', enum: ['must', 'should', 'nice'] },
  what: { type: 'string' }, why: { type: 'string' }, fix: { type: 'string' } }, required: ['title', 'where', 'severity', 'what', 'why', 'fix'] } } }, required: ['summary', 'findings'] }
const TRIAGE = { type: 'object', properties: { clean: { type: 'boolean' }, work: { type: 'array', items: { type: 'object', properties: {
  title: { type: 'string' }, where: { type: 'string' }, severity: { type: 'string', enum: ['must', 'should'] }, instruction: { type: 'string' }, from: { type: 'string' } },
  required: ['title', 'where', 'severity', 'instruction', 'from'] } }, dropped: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, why: { type: 'string' } }, required: ['title', 'why'] } } }, required: ['clean', 'work', 'dropped'] }
const REPORT = { type: 'object', properties: { changed: { type: 'array', items: { type: 'string' } }, verified: { type: 'array', items: { type: 'string' } },
  skipped: { type: 'array', items: { type: 'object', properties: { item: { type: 'string' }, why: { type: 'string' } }, required: ['item', 'why'] } },
  commits: { type: 'array', items: { type: 'string' } }, notes: { type: 'string' } }, required: ['changed', 'verified', 'skipped', 'commits', 'notes'] }

const LENSES = {
  code: `You are a senior code reviewer. Review ${a.repo} (${a.scope}) for correctness, dead code, leftovers of earlier designs, tests that do not test the real contract, lint, modules with two purposes, comments describing code that is gone, config read but unused, duplicated helpers, error paths that swallow failures. Read the code, run the suites (uv run python -m pytest -q; uv run ruff check), read the recent git log and diffs. Concrete findings with file and line; no padding.`,
  requirements: `You are a requirements reviewer. Re-evaluate whether ${a.repo} (${a.scope}) does the right thing for the end goal in the brief. Does the repo contain exactly its scope and nothing else? Are the claims in its README true (test them: follow the README as a stranger would, in ${a.out}/req-check/, and time yourself)? Do the docs describe what exists today and nothing more? Which requirements are wrong or missing for the goal? Do not propose features the brief puts out of scope.`,
  design: `You are a software architect reviewing ${a.repo} (${a.scope}): module boundaries and names, the contracts it exposes and depends on and their documentation, config and state layout, how it uses Orchestra's plugin interface, event sources and names, whether it reaches into anything not its own, error paths (timeouts, a counterpart that never answers, shutdown with work out), whether every piece has one reason to exist here. Check the docs match the code.`,
  ux: `You are a user experience reviewer for operator tools. ${a.demo ? `Start the demo exactly as its README says (${a.demo}),` : 'Start the demo exactly as the README says,'} open every page and panel the repo adds to Orchestra's web UI plus Orchestra's own Dashboard, Machines and Core pages with it loaded, in a headless browser (puppeteer; the brief says where), and save screenshots to ${a.out}/ux/. Is the state readable at a glance; are names the user's words; do cards, pills and banners say what is happening and why something waits; anything stale, broken, overlapping, unstyled or lying? Judge the command line too (status, help). Stop every process you started and kill your headless Chrome (pkill -f puppeteer_dev_chrome_profile).`,
}
const lenses = a.lenses || Object.keys(LENSES)
const history = []
for (let round = 1; round <= ROUNDS; round++) {
  log(`layered-review ${a.repo} round ${round}`)
  const reviews = (await parallel(lenses.map((l) => () =>
    agent(PRE + LENSES[l] + `\n\nRound ${round}.` + (history.length ? ` Earlier rounds fixed: ${JSON.stringify(history[history.length - 1].work.map((w) => w.title))}; check those landed, look for what was missed.` : '') +
      `\nYou are read-only on the repositories; write only under ${a.out}/. Return findings in the schema ("must": violates the brief or breaks the system; "should": a careful owner would insist; "nice": taste).`,
      { label: `${l} r${round}`, phase: 'Review', schema: FINDINGS, effort: 'high' })))).filter(Boolean)
  const all = reviews.flatMap((r, i) => r.findings.map((f) => ({ ...f, lens: lenses[i] })))
  log(`round ${round}: ${all.length} findings`)
  const triage = await agent(PRE + `You are the triage judge for ${a.repo} (${a.scope}). Merge duplicates, drop findings that contradict the brief or touch the owner's reserved decisions, drop "nice" unless trivial beside another fix, confirm each remaining finding against the code yourself. Produce a self-contained work list. clean = true only if nothing must/should remains.\n\nFINDINGS:\n${JSON.stringify(all, null, 1)}`,
    { label: `triage r${round}`, phase: 'Triage', schema: TRIAGE, effort: 'high' })
  if (!triage) break
  history.push(triage)
  if (triage.clean || !triage.work.length) { log(`clean after round ${round}`); break }
  if (a.fix === false) break
  const fix = await agent(PRE + `You are the implementor for ${a.repo} (${a.scope}). Apply this work list item by item. ${a.fixExtra || ''}\n\nWORK LIST:\n${JSON.stringify(triage.work, null, 1)}\n\nKeep every change inside this repo's scope (skip and explain otherwise); delete rather than comment out; update docs and tests with the code; run the full suites and ruff and check the results; commit locally (Co-Authored-By line from the brief); do not push; stop any process you start.`,
    { label: `fix r${round}`, phase: 'Fix', schema: REPORT, effort: 'high' })
  if (fix) log(`fix r${round}: ${fix.commits.length} commit(s), ${fix.skipped.length} skipped`)
}
return { rounds: history.length, clean: !!(history.length && history[history.length - 1].clean), last: history[history.length - 1] || null }
