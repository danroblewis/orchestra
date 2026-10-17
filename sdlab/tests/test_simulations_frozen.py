"""The ground-truth simulations are fixed: discovery works against them, never the other way round.

Every file that decides what the ground-truth examples' data is - the engine (sdlab/sdtruth.py), the
equation functions it uses from sdlab/runner.py, and each sd-* example's truth model, schedule and
programs - has its fingerprint recorded in tests/simulations.sha256. Changing any of them fails this
test. See docs/DISCOVERY-LOOP.md: improve discovery, not the data it is tested on.

    uv run python tests/test_simulations_frozen.py --record     # only when adding a NEW example
"""

import hashlib
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "tests" / "simulations.sha256"


def fingerprints() -> dict[str, str]:
    from sdlab import runner
    out = {"sdlab/sdtruth.py": hashlib.sha256((ROOT / "sdlab" / "sdtruth.py").read_bytes()).hexdigest()}
    for fn in (runner.desired_rate, runner.multiplier, runner.effect_value):
        out[f"sdlab/runner.py:{fn.__name__}"] = hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()
    for p in sorted((ROOT / "sdlab" / "examples").glob("sd-*/**/*")):
        if p.is_file() and p.suffix in (".json", ".py") and p.name != "truth.json" and "__pycache__" not in p.parts:
            out[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted((ROOT / "sdlab" / "examples").glob("sd-*.json")):
        out[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def recorded() -> dict[str, str]:
    return dict(line.split("  ", 1)[::-1] for line in RECORD.read_text().splitlines() if line.strip())


def test_the_simulations_have_not_changed():
    now, then = fingerprints(), recorded()
    changed = sorted(k for k in then if now.get(k) != then[k])
    assert not changed, f"ground-truth simulation files changed (they must not): {changed}"


def test_no_simulation_file_is_unrecorded():
    new = sorted(set(fingerprints()) - set(recorded()))
    assert not new, f"new simulation files not recorded (record them only when adding a new example): {new}"


if __name__ == "__main__" and "--record" in sys.argv:
    RECORD.write_text("".join(f"{h}  {k}\n" for k, h in sorted(fingerprints().items())))
    print(f"recorded {len(fingerprints())} fingerprints in {RECORD.relative_to(ROOT)}")
