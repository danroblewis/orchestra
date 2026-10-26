export const meta = {
  name: 'release-gate',
  description: 'Everything that must hold before Orchestra and its plugins are called done: a subtraction audit, a UX panel on each demo, model acceptance on the known use cases, a fresh layered review per repository, and a final verifier',
  whenToUse: 'Before pushing a milestone. Chains the other review workflows; takes a day of agents.',
  phases: [
    { title: 'Subtraction audit', detail: 'what should not be in each repository; contract drift' },
    { title: 'UX panels', detail: 'personas and experts on each demo' },
    { title: 'Model acceptance', detail: 'the known use cases yield their models' },
    { title: 'Fresh review', detail: 'a layered review per repository with new eyes' },
    { title: 'Verify', detail: 'suites, greps, git state, demos run' },
  ],
}

// args: { brief, out, repos: [{path, scope, forbidden, exclude?}], contracts: [...], demos: [{repo, start, stop?, pages?}], cases: [...model-acceptance cases], skip?: ['audit'|'ux'|'models'|'review'] }
const MODEL = (args && args.model) || 'opus'      // the owner's choice for agents (2026-10-26)
const a = args || {}
if (!a.brief || !a.out || !a.repos) throw new Error('release-gate needs args.brief, args.out, args.repos')
const W = '/Users/daniellewis/orchestra_2/.claude/workflows/'
const skip = new Set(a.skip || [])
const out = {}

if (!skip.has('audit')) {
  phase('Subtraction audit')
  out.audit = await workflow({ scriptPath: W + 'subtraction-audit.js' }, { brief: a.brief, out: a.out + '/audit', repos: a.repos, contracts: a.contracts || [] })
  log(`audit: ${out.audit && out.audit.findings} findings`)
}
if (!skip.has('ux') && a.demos && a.demos.length) {
  phase('UX panels')
  out.ux = []
  for (const d of a.demos) {                                  // one demo at a time: they share ports and the viewer's attention
    const r = await workflow({ scriptPath: W + 'ux-review.js' }, { brief: a.brief, repo: d.repo, start: d.start, stop: d.stop, pages: d.pages, out: a.out + '/ux/' + d.repo.split('/').pop(), rounds: 2 })
    out.ux.push({ repo: d.repo, result: r })
    log(`ux ${d.repo}: ${r && r.clean ? 'clean' : 'not clean'} after ${r && r.rounds} round(s)`)
  }
}
if (!skip.has('models') && a.cases && a.cases.length) {
  phase('Model acceptance')
  out.models = await workflow({ scriptPath: W + 'model-acceptance.js' }, { brief: a.brief, out: a.out + '/models', cases: a.cases })
  log(`models: ${out.models ? out.models.cases.filter((c) => c.pass).length + '/' + out.models.cases.length + ' pass' : 'no result'}`)
}
if (!skip.has('review')) {
  phase('Fresh review')
  out.review = []
  for (const r of a.repos) {                                  // sequential: each review's fix commits to its own repo, but reviewers start demos on shared ports
    const res = await workflow({ scriptPath: W + 'layered-review.js' }, { brief: a.brief, repo: r.path, scope: r.scope, out: a.out + '/review/' + r.path.split('/').pop(), rounds: 2, demo: r.demo })
    out.review.push({ repo: r.path, result: res })
  }
}
phase('Verify')
out.final = await agent(`Read ${a.brief} first. You are the final verifier for these repositories: ${JSON.stringify(a.repos.map((r) => r.path))}. For each: git status (clean?), branch, git log --oneline -12; run the full test suite (uv run python -m pytest -q) and ruff; git grep -niE "${a.repos.map((r) => r.forbidden).join('|')}" and classify every hit against each repo's scope (${a.repos.map((r) => r.path.split('/').pop() + ': ' + r.scope).join('; ')}). For each demo (${JSON.stringify((a.demos || []).map((d) => d.start))}) run the one command for two minutes, confirm the URL serves and work moves, and stop it. Confirm the READMEs point at each other correctly. Return a plain-text report: a results table, every problem, then "ready to push: yes/no" with reasons. Stop every process you start.`,
  { model: MODEL, label: 'final verifier', phase: 'Verify', effort: 'medium' })
return out
