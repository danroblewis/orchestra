"""The core's modules and names the plugins import (PLUGINS.md §11), found by reading the agents',
workflows' and bridges' code outside their tests: each must import here, so a rename or a move
fails in the core first, not in a plugin after a release."""

import importlib
import importlib.util

import pytest

SURFACE = {
    "orchestra": ["endpoint", "runtime"],
    "orchestra.collect": ["spec"],
    "orchestra.collect.round": ["collect"],
    "orchestra.collect.spec": ["Collector", "TIMEOUT_S", "check"],
    "orchestra.config": ["ConfigError", "Project", "load_project", "parse_duration"],
    "orchestra.config_edit": ["Change", "ConfigEdit", "plugin_checks"],
    "orchestra.events": ["Events", "event_time", "machine_and_instance", "now"],
    "orchestra.guides": ["collect"],
    "orchestra.launcher": ["NAME", "Process"],
    "orchestra.metrics": ["MetricsStore", "Point", "ProjectStore", "for_project", "step_sample"],
    "orchestra.overlay": ["OVERLAY", "REPO", "describe"],
    "orchestra.plugins": ["Declared", "Page", "Plugin"],
    "orchestra.runtime": ["alive"],
    "orchestra.sd.discover": ["MIN_COVER", "MIN_STEPS"],
    "orchestra.sd.eras": ["recorded"],
    "orchestra.sd.flows_of": ["flows_of", "name_unit"],
    "orchestra.sd.intended.checks": ["PROVENANCE"],
    "orchestra.sd.intended.keys": ["Keys"],
    "orchestra.sd.intended.display": ["declared_names"],
    "orchestra.sd.intended.names": ["ABSENT", "WAITS", "WAITS_LINK", "resolve"],
    "orchestra.sd.intended.ops": ["ENV_NAME", "OPTION"],
    "orchestra.sd.predictions": ["PredictionError", "Predictions", "expectation", "plain"],
    "orchestra.sd.series": ["Declared", "series_key"],
    "orchestra.sd.store": ["ModelStore"],
    "orchestra.sources": ["SourceError", "report"],
    "orchestra.sources.catalogue": ["Catalogue"],
    "orchestra.sources.fetch": ["accumulate"],
    "orchestra.sources.limits": ["Budget", "RateLimit", "store_dir", "store_key"],
    "orchestra.sources.listing": ["TooManyNames", "listing"],
    "orchestra.sources.plan": ["counter_step", "grid_step"],
    "orchestra.sources.report": ["check"],
    "orchestra.sources.spec": ["Specs", "for_project", "load"],
    "orchestra.tokens": ["owner_only"],
    # used today, to be moved out of the web package (PLUGINS.md §11)
    "orchestra.web.dynamics": ["model_view"],
    "orchestra.web.instruments": ["instruments_view"],
    "orchestra.web.machine_logs": ["readable", "tail"],
}
NEEDS_SD = {"orchestra.sd.reads": ["ModelReads", "ReadError"],
            "orchestra.sd.equations.language": ["reference"]}


@pytest.mark.parametrize("module", sorted(SURFACE))
def test_every_name_the_plugins_import_is_there(module):
    mod = importlib.import_module(module)
    missing = [n for n in SURFACE[module] if not hasattr(mod, n) and importlib.util.find_spec(f"{module}.{n}") is None]
    assert not missing, f"{module} lacks {missing}"


@pytest.mark.parametrize("module", sorted(NEEDS_SD))
def test_the_model_reads_names_are_there(module):
    pytest.importorskip("numpy")
    mod = importlib.import_module(module)
    assert all(hasattr(mod, n) for n in NEEDS_SD[module]), module


def test_the_doc_names_every_module():
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[2] / "PLUGINS.md").read_text(encoding="utf-8")
    for module in [*SURFACE, *NEEDS_SD]:
        if module in ("orchestra", "orchestra.collect"):
            continue
        short = module.rsplit(".", 1)[-1]
        assert f"`{module}`" in doc or f"`.{short}`" in doc, module
