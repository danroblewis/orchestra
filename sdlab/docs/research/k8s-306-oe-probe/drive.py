import sys, time, json
import importlib.util, os
_spec = importlib.util.spec_from_file_location('oe', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oe.py'))
oe = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(oe)
from sdlab.ladder import cases as casemod, data, score, store
C = '306-k8s-ready-replicas-cap'
c = casemod.load(C)
strats = sys.argv[1].split(','); variants = sys.argv[2].split(','); search = len(sys.argv) > 3
for v in variants:
    noise = casemod.variant(c, v)["noise"]; model = casemod.truth_model(c, v)
    d = {**data.load(c, v), **casemod.announced(c)}
    stocks = casemod.page_stocks(model)
    opts = {"inputs": d["inputs"], "injections": d["injections"]}
    run = {"t": d["t"], "levels": d["levels"], "boundary": d.get("boundary"), "boundary_declared": d.get("boundary_declared")}
    for s in strats:
        r = store.latest(case=C, strategy=s, variant=v, found=True)[0]
        t0 = time.time()
        m = oe.refit(r["found"], stocks, run, opts, search=search, log=lambda *a: print(*a, flush=True))
        if m is None:
            print(s, v, 'unsupported form'); continue
        fl = oe.normalise_drains(m.flows())
        sc = score.equations(c, noise, model, fl, d)
        print(f"== {s} {v}: {sc['status']} {sc['right']}/{sc['of']} ({time.time()-t0:.0f}s) stored {r['status']}", flush=True)
        for p in sc['parts']:
            print('   ', 'ok' if p['ok'] else 'X ', p.get('kind'), p.get('true') if not isinstance(p.get('true'), dict) else 'MIN', 'err', round(p['error'], 3), 'se', round(p['se'], 4) if p.get('se') else None)
        for sp in sc.get('spurious') or []:
            print('    + spurious', json.dumps(sp, default=str)[:160])
        for f in fl: print('     ', f['from'], '->', f['to'], json.dumps(f['rate'])[:140])
