export const meta = {
  name: 'subtraction-audit',
  description: 'Auditors whose only question is "should this exist here?" over each repository, plus a contract-drift auditor between repositories; a judge confirms; an implementor removes',
  whenToUse: 'Before a release or after moving code between repositories. The default answer to every finding is removal.',
  phases: [
    { title: 'Audit', detail: 'one auditor per repository, one for the contracts between them' },
    { title: 'Judge', detail: 'confirm against the code; keeping needs a reason' },
    { title: 'Remove', detail: 'delete, fix tests and docs, commit per repository' },
  ],
}

// args: { brief, out, repos: [{ path, scope, forbidden: 'a regex of words that must not appear except generically', exclude?: 'paths to skip' }], contracts?: [{ a, b, what }], fix? }
const MODEL = (args && args.model) || 'opus'      // the owner's choice for agents (2026-10-26)
const a = args || {}
if (!a.brief || !a.out || !a.repos || !a.repos.length) throw new Error('subtraction-audit needs args.brief, args.out, args.repos[]')
const PRE = `Read ${a.brief} first, all of it; every constraint in it binds you.\n\n`
const FINDINGS = { type: 'object', properties: { summary: { type: 'string' }, findings: { type: 'array', items: { type: 'object', properties: {
  title: { type: 'string' }, where: { type: 'string' }, severity: { type: 'string', enum: ['must', 'should', 'nice'] },
  what: { type: 'string' }, why: { type: 'string' }, fix: { type: 'string' } }, required: ['title', 'where', 'severity', 'what', 'why', 'fix'] } } }, required: ['summary', 'findings'] }
const TRIAGE = { type: 'object', properties: { clean: { type: 'boolean' }, work: { type: 'array', items: { type: 'object', properties: {
  title: { type: 'string' }, where: { type: 'string' }, severity: { type: 'string', enum: ['must', 'should'] }, instruction: { type: 'string' }, from: { type: 'string' } },
  required: ['title', 'where', 'severity', 'instruction', 'from'] } }, dropped: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, why: { type: 'string' } }, required: ['title', 'why'] } } }, required: ['clean', 'work', 'dropped'] }
const REPORT = { type: 'object', properties: { changed: { type: 'array', items: { type: 'string' } }, verified: { type: 'array', items: { type: 'string' } },
  skipped: { type: 'array', items: { type: 'object', properties: { item: { type: 'string' }, why: { type: 'string' } }, required: ['item', 'why'] } },
  commits: { type: 'array', items: { type: 'string' } }, notes: { type: 'string' } }, required: ['changed', 'verified', 'skipped', 'commits', 'notes'] }

const jobs = [
  ...a.repos.map((r) => ({ key: r.path.split('/').pop(), prompt: `Audit ${r.path}, whose whole scope is: ${r.scope}. (1) git grep -niE "${r.forbidden}" over tracked files${r.exclude ? ` excluding ${r.exclude}` : ''}; classify every hit as generic use or leftover. (2) List every tracked file and say in one line why it exists for this scope; any file you cannot justify is a finding. (3) Dead definitions: functions, classes, config fields, CSS classes, static files, test fixtures that nothing references (check in and out of tests). (4) Docs that describe something absent or another repository's concern. (5) Dependencies in pyproject nothing imports.` })),
  ...(a.contracts || []).map((c, i) => ({ key: `contract-${i + 1}`, prompt: `Audit the contract between ${c.a} and ${c.b}: ${c.what}. Same names, same fields, same semantics on both sides; any field one side sends and the other ignores or reads but never receives; the contract documented in exactly one place per repository and those places agreeing; both repos' docs telling the same story.` })),
]
const audits = (await parallel(jobs.map((j) => () =>
  agent(PRE + `You are an auditor whose only question is "should this exist here?". ${j.prompt}\n\nRead-only on the repositories; write only under ${a.out}/audit/. Return exhaustive, exact findings (file, line) in the schema.`,
    { model: MODEL, label: `audit ${j.key}`, phase: 'Audit', schema: FINDINGS, effort: 'high' })))).filter(Boolean)
const all = audits.flatMap((r, i) => r.findings.map((f) => ({ ...f, audit: jobs[i].key })))
log(`subtraction-audit: ${all.length} findings`)
const triage = await agent(PRE + `You are the judge for a subtraction audit. Confirm each finding against the code (read it), merge duplicates, drop what the brief puts out of scope or reserves for the owner. Removal is the default answer; keeping needs a reason the brief supports. Each work item names the repository.\n\nFINDINGS:\n${JSON.stringify(all, null, 1)}`,
  { model: MODEL, label: 'judge', phase: 'Judge', schema: TRIAGE, effort: 'high' })
let fix = null
if (a.fix !== false && triage && triage.work.length) {
  fix = await agent(PRE + `You are the implementor for the subtraction audit. Apply this work list: delete what should not exist, each repository in its own commits, full suites run and checked before each commit. If a removal breaks a test, decide against the brief whether the test or the removal is wrong, and say which. Docs describe only what remains.\n\nWORK LIST:\n${JSON.stringify(triage.work, null, 1)}`,
    { model: MODEL, label: 'remove', phase: 'Remove', schema: REPORT, effort: 'high' })
}
return { findings: all.length, triage, fix }
