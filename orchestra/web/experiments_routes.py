"""The Experiments pages and their read routes (sd/experiments/): machines make and run
experiments through the events endpoint's HTTP API and the Python API; here they are only read
(AGENTS.md rule 9)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ..config import Project


def install(app: FastAPI, project: Project, metrics, page: Callable[[str], str]) -> None:
    def experiments():
        from ..sd.experiments.api import Experiments
        return Experiments(project, metrics=metrics)

    def answered(fn):
        from fastapi.responses import JSONResponse

        from ..sd.experiments.api import ExperimentError
        try:
            return fn()
        except ExperimentError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status)

    @app.get("/experiments", response_class=HTMLResponse)
    async def experiments_page() -> str:
        return page("experiments.html")

    @app.get("/experiments/{eid}", response_class=HTMLResponse)
    async def experiment_page(eid: str) -> str:
        return page("experiment.html")

    @app.get("/api/experiments")
    def experiments_list(owner: str | None = None, status: str | None = None, era: str | None = None):
        """Every experiment: who made it, its title and purpose, status, base, latest run and the
        verdict of its prediction; ``era``: those made on its model or predicting its change."""
        return answered(lambda: experiments().list(owner, status, era))

    @app.get("/api/experiments/{eid}")
    def experiment_one(eid: str, base: bool = False):
        """One experiment: its draft (equations in the language), scenario, edit log, runs and prediction."""
        return answered(lambda: experiments().get(eid, base))

    @app.get("/api/experiments/{eid}/diff")
    def experiment_diff(eid: str):
        return answered(lambda: experiments().diff(eid))

    @app.get("/api/experiments/{eid}/runs")
    def experiment_runs(eid: str):
        return answered(lambda: experiments().runs(eid))

    @app.get("/api/experiments/{eid}/runs/{rid}")
    def experiment_run(eid: str, rid: str):
        """One run in full: forward (trajectories and band), replay (observed against simulated, scores) or inverse."""
        return answered(lambda: experiments().run_result(eid, rid))

    @app.get("/api/experiments/{eid}/runs/{rid}/measured")
    def experiment_run_measured(eid: str, rid: str, before_s: float = 3600.0):
        """A forward run's stocks as measured: before its now, and since (up to its horizon or the present)."""
        return answered(lambda: experiments().measured(eid, rid, before_s))

    @app.get("/api/experiments/{eid}/prediction")
    def experiment_prediction(eid: str):
        """The prediction a committed experiment became, with its verdict once judged."""
        return answered(lambda: experiments().prediction(eid))
