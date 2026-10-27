"""``orchestra sources infer`` says each family's reporting interval, or in words why it has none."""

from types import SimpleNamespace

from orchestra.sources.report import infer


def test_a_family_with_too_few_samples_says_why_it_has_no_interval():
    families = [{"name": "app_latency_seconds", "kind": "gauge", "stats": ["avg", "max"], "resolution_s": 60.0, "labels": {}},
                {"name": "disk_bytes", "kind": "gauge", "stats": [], "resolution_s": None, "labels": {}}]
    inf = SimpleNamespace(families=families, kept=[], left_out=[], notes=[], script=None)
    cat = SimpleNamespace(specs=SimpleNamespace(sources=[SimpleNamespace(name="rig", prefix="rig", producers={})]),
                          inference=lambda *a, **k: inf)
    project = SimpleNamespace(config=SimpleNamespace(discovery_window=3600.0, discovery_step=60.0))
    out = "\n".join(infer(cat, project))
    assert "family app_latency_seconds [gauge, avg/max] every 60 s:" in out
    assert "family disk_bytes [gauge] its reporting interval not measured: fewer than three samples of it in the window:" in out
    assert "?" not in out
