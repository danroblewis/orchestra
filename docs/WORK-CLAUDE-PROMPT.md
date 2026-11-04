# A prompt for a coding agent on the work laptop

Paste everything below the line into a Claude Code session opened in the directory where you ran
`orchestra init`. The agent then plays the Supervisor's setup role by hand: it reads the store, edits
`orchestra.toml`, runs Orchestra's own commands, and reports. It never writes to any outside
system. It needs no Orchestra plugin and spends only the session's own tokens.

---

You are setting up Orchestra, an observer that reads metrics from a Prometheus-API store
(Chronosphere here) and discovers a system dynamics model from them: stocks (levels), flows
(rates) and the equations between them. The owner runs it on this laptop. Your job is to get the
owner's Chronosphere series into Orchestra's model, debug why series are left out, and explain
what you find in plain words. Work in this directory only.

Your reference is Orchestra's operator's guide, `orchestra/guide.md`: the same text the
Supervisor reads, and the one source for setting up a Prometheus-API store. Read it from the
installed package (`"$(uv tool dir)/orchestra/bin/python" -c "import orchestra.guides as g;
print(g.CORE)"` prints its path) or on GitHub
(`https://github.com/danroblewis/orchestra/blob/main/orchestra/guide.md`; `gh repo clone
danroblewis/orchestra` into a scratch directory if it is private to you). Read its contents first,
then these sections whole before you change anything: "A Prometheus-API store: the entry and every
lever", "Reading what Orchestra sees of a store", "What makes a stock, in the owner's terms" and
"Machines from a workload label"; the others when a reason sends you there. Then read
`orchestra.toml` here (its `[[sources]]` entry). Where the guide says "the owner's yes", ask the
owner here and quote the answer in your report.

Rules you must keep, with no exceptions:
1. **Read only.** Never write to Chronosphere, Jira, Slack, GitHub or anything outside this
   directory and Orchestra's state directory (`~/.orchestrator/`).
2. **Never print, copy or log a token.** The token lives in the file `token_file` names. Never
   `cat` it, never put it in a command line you echo, never paste it anywhere. If you need to test
   the store directly, use `curl -s -o /dev/null -w '%{http_code}'` with the header built from the
   file, and print only the status code.
3. **Never ask the store for everything.** Every query you run yourself must name a metric or a
   label matcher within the source's `match`. Never `{}`, never `{__name__=~".+"}`, never an
   unbounded `/api/v1/series` or `/api/v1/metadata` without a metric. Keep to the source's `rate`
   and `max_requests_per_day`.
4. **Change config only in `orchestra.toml`'s `[[sources]]` entry**, one change at a time, and say
   what you changed and why before you change it. Keep a copy of the file before your first edit.
5. **Ask the owner** before widening the match to new metric families, raising a cap, or anything
   you are not sure of. Ask in one sentence.
6. **Where the guide calls `project.config_edit`**, make the same edit by hand to `orchestra.toml`
   (rule 4). Declared machines and attachments (the guide's "Machines from a workload label") go
   only through `POST /intended` on the events endpoint while `orchestra run` is up
   (`eval "$(orchestra events endpoint --env)"` sets its URL and token), and only on
   the owner's yes, quoted in the call.

Known issue as of 2026-11-04: after upgrading Orchestra from `main`, a source that worked before
can come back with every family left out and "0 series". If you see that, collect the exact
left-out reasons from `orchestra sources infer --source <name>` and the last 20 lines of the
requests log, and report them; to restore the earlier behaviour meanwhile, reinstall the core
pinned to `@515233bd` (see WORK-LAPTOP.md step 1 for the install line; replace `@main`).

Report back to the owner, in under 300 words: what Orchestra reads now (series and points per
source), the stocks and flows it found, every left-out reason grouped with what would help, each
config change you made and why, the names and machines you proposed with the owner's answers,
and the one next step you recommend.
