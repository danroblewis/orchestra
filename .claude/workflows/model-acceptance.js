export const meta = {
  name: 'model-acceptance',
  description: 'Run a use case against Orchestra, discover its system dynamics model, and judge the model against the stocks, flows and loops the use case is known to have; refuters attack every pass; general discovery bugs become fixes with unit tests',
  whenToUse: 'After changes to discovery, to a machine package\'s metrics, or before claiming a model is meaningful. One case or many.',
  phases: [
    { title: 'Run', detail: 'start the case, let metrics accumulate, discover' },
    { title: 'Judge', detail: 'a modeller compares the model to the expected structure' },
    { title: 'Refute', detail: 'skeptics attack each pass' },
    { title: 'Fix', detail: 'general discovery or metric-naming fixes, with tests' },
  ],
}

// args: {
//   brief: path to the shared brief (required)
//   out: directory for discovered models, logs and the report (required)
//   cases: [{ name, start, stop?, minutes, repo, expected: { stocks: [...], flows: [...], loops: [...], forbidden: [...] }, notes? }]  (required)
//   fix: run the implementor on confirmed general bugs (default true)
// }
const MODEL = (args && args.model) || 'opus'      // the owner's choice for agents (2026-10-26)
const a = args || {}
if (!a.brief || !a.out || !a.cases || !a.cases.length) throw new Error('model-acceptance needs args.brief, args.out, args.cases[]')
const PRE = `Read ${a.brief} first, all of it; every constraint in it binds you.\n\n`

const RUN = { type: 'object', properties: {
  ran: { type: 'boolean' }, minutes: { type: 'number' }, model_path: { type: 'string', description: 'where the discovered model JSON was saved under out' },
  series: { type: 'array', items: { type: 'string' }, description: 'every metric series name observed' },
  stocks: { type: 'array', items: { type: 'string' } }, flows: { type: 'array', items: { type: 'string' } },
  left_out: { type: 'array', items: { type: 'string' }, description: 'series discovery left out, with its reason' },
  problems: { type: 'array', items: { type: 'string' } }, log: { type: 'string' },
}, required: ['ran', 'minutes', 'model_path', 'series', 'stocks', 'flows', 'left_out', 'problems', 'log'] }

const VERDICT = { type: 'object', properties: {
  pass: { type: 'boolean' }, score: { type: 'number', description: '0-16 on the analysis-method rubric where it applies, else 0-10' },
  matched: { type: 'array', items: { type: 'string' } }, missing: { type: 'array', items: { type: 'string' } },
  spurious: { type: 'array', items: { type: 'string' } },
  causes: { type: 'array', items: { type: 'object', properties: {
    what: { type: 'string' }, where: { type: 'string', description: 'file: Orchestra discovery, or the package\'s measures' },
    kind: { type: 'string', enum: ['discovery-bug', 'metric-naming', 'too-little-data', 'expectation-wrong', 'other'] },
    fix: { type: 'string' } }, required: ['what', 'where', 'kind', 'fix'] } },
  reasoning: { type: 'string' },
}, required: ['pass', 'score', 'matched', 'missing', 'spurious', 'causes', 'reasoning'] }

const REFUTE = { type: 'object', properties: { refuted: { type: 'boolean' }, why: { type: 'string' } }, required: ['refuted', 'why'] }
const REPORT = { type: 'object', properties: {
  changed: { type: 'array', items: { type: 'string' } }, verified: { type: 'array', items: { type: 'string' } },
  skipped: { type: 'array', items: { type: 'object', properties: { item: { type: 'string' }, why: { type: 'string' } }, required: ['item', 'why'] } },
  commits: { type: 'array', items: { type: 'string' } }, notes: { type: 'string' } }, required: ['changed', 'verified', 'skipped', 'commits', 'notes'] }

const results = await pipeline(a.cases,
  (c) => agent(PRE + `You run the use case "${c.name}" and discover its model. Start it with: ${c.start}. ${c.notes || ''} Let it run ${c.minutes} minutes so the metrics have motion (watch the metrics store or /api/metrics; note when the first stock moves). Then run discovery (\`uv run orchestra sd discover\` in the project, or POST the Dynamics page's rediscover endpoint) and save the resulting model JSON (the model store under ~/.orchestrator/<key>/, or /api/dynamics/model) to ${a.out}/${c.name}/model.json, the list of series to series.txt, and your log to run.md. Record every series discovery left out and the reason it gives. Then stop the case: ${c.stop || 'stop every process you started'}. Report in the schema; do not judge the model, just record it exactly.`,
    { model: MODEL, label: `run ${c.name}`, phase: 'Run', schema: RUN, effort: 'medium' }),
  (run, c) => run && run.ran ? agent(PRE + `You are a system dynamics modeller judging a discovered model. The use case "${c.name}" is known to have this structure:\n${JSON.stringify(c.expected, null, 1)}\n\nThe run recorded: ${JSON.stringify({ stocks: run.stocks, flows: run.flows, left_out: run.left_out, series: run.series, problems: run.problems }, null, 1)}\nRead the full model at ${run.model_path} and the run log at ${a.out}/${c.name}/run.md; read how discovery decided (${'/Users/daniellewis/orchestra_2/orchestra/sd/discover.py'} and the strategy named in the model) and how the package names its series (${c.repo}). Judge: every expected stock present as a stock (not a flow, not left out); every expected flow present, with instances merged into one flow; conservation where the use case conserves; equation origins recorded; nothing from the forbidden list in the model (noise series left out); loops the use case says exist are representable by the model's structure. For every miss or spurious item, name the cause and where it lives: a discovery bug (Orchestra), a metric name or label the package writes badly, too little data (say how much would be enough), or an expectation that is wrong. pass = true only if nothing expected is missing and nothing spurious is in. Fill the schema exactly.`,
    { model: MODEL, label: `judge ${c.name}`, phase: 'Judge', schema: VERDICT, effort: 'high' }) : null,
  async (verdict, c) => {
    if (!verdict) return { name: c.name, verdict: null, upheld: false }
    if (!verdict.pass) return { name: c.name, verdict, upheld: true }
    const votes = (await parallel([0, 1, 2].map((i) => () =>
      agent(PRE + `A modeller passed the discovered model of "${c.name}" with this reasoning:\n${verdict.reasoning}\nmatched: ${JSON.stringify(verdict.matched)}\nExpected structure: ${JSON.stringify(c.expected)}\nModel: ${a.out}/${c.name}/model.json. Try to refute the pass from angle ${['structure (is each "stock" really the conserved level, each flow really the rate that moves it, or are names matched but roles wrong?)', 'data (did the window hold enough motion for these fits to mean anything; are rates fitted on a handful of points; is any equation a tautology of a counter against itself?)', 'honesty (are origins recorded for every equation; does the model claim a loop the data cannot show; would the owner, who rejected "conveyor belts without dynamics", accept this?)'][i]}. Default to refuted = true when uncertain.`,
        { model: MODEL, label: `refute ${c.name} ${i + 1}`, phase: 'Refute', schema: REFUTE, effort: 'high' })))).filter(Boolean)
    const upheld = votes.filter((v) => !v.refuted).length >= 2
    return { name: c.name, verdict, upheld, refutations: votes.filter((v) => v.refuted).map((v) => v.why) }
  })

const done = results.filter(Boolean)
const failing = done.filter((r) => !r.verdict || !r.verdict.pass || !r.upheld)
log(`model-acceptance: ${done.length - failing.length}/${done.length} cases pass`)
const causes = done.flatMap((r) => (r.verdict ? r.verdict.causes : []).filter((x) => x.kind === 'discovery-bug' || x.kind === 'metric-naming').map((x) => ({ ...x, case: r.name })))
let fix = null
if (a.fix !== false && causes.length) {
  fix = await agent(PRE + `You are the implementor. These causes were found when judging discovered models; fix the ones that are real, each in the repository it belongs to (Orchestra's discovery: a general bug, named generally, with a unit test in tests/unit/test_discover.py that reproduces it with synthetic series; a package's metrics: the series name or label, with its tests). Confirm each against the code before changing anything; if a cause is wrong, say so in skipped. Run the suites, check the results, commit locally per repository (Co-Authored-By line from the brief). Do not push.\n\nCAUSES:\n${JSON.stringify(causes, null, 1)}`,
    { model: MODEL, label: 'fix causes', phase: 'Fix', schema: REPORT, effort: 'high' })
}
return { cases: done.map((r) => ({ name: r.name, pass: !!(r.verdict && r.verdict.pass && r.upheld), score: r.verdict ? r.verdict.score : null, missing: r.verdict ? r.verdict.missing : [], spurious: r.verdict ? r.verdict.spurious : [], refutations: r.refutations || [] })), causes, fix }
