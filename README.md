# Orchestra

A ticket tracker, milestone planner, and CI/CD workflow operated by AI agents on
the [Pi](https://github.com/earendil-works/pi) harness. Point it at a git
repository; describe work to the Supervisor; workers build tickets on their
own branches, reviewers check them, and a batched, bisecting merge gate lands
what passes on `main`.

- `SPEC.md` is the design.
- `AGENTS.md` is the list of rules that must not be broken.

Status: the v0 prototype has been removed (it is in git history before
`960f875`). The rewrite starts from the spec.
