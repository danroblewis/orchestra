import sys
import importlib.util, os
_spec = importlib.util.spec_from_file_location('oe', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oe.py'))
oe = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(oe)
from sdlab.ladder import cases as casemod, data, score
C = '306-k8s-ready-replicas-cap'; c = casemod.load(C)
P = lambda a, b, s, k: {"from": a, "to": b, "rate": {"form": "proportional", "stock": s, "k": k}}
for v in sys.argv[1].split(','):
    noise = casemod.variant(c, v)["noise"]; model = casemod.truth_model(c, v)
    d = {**data.load(c, v), **casemod.announced(c)}; stocks = casemod.page_stocks(model)
    opts = {"inputs": d["inputs"], "injections": d["injections"]}
    run = {"t": d["t"], "levels": d["levels"], "boundary": d.get("boundary"), "boundary_declared": True}
    truth = [P(None, 'queue', 'traffic', 1.0), {"from": 'queue', "to": 'inflight', "rate": {"form": "expr", "expr": "min(0.6 * queue, 40 * ready)"}},
             P('queue', 'retries', 'queue', .08), P('retries', 'queue', 'retries', .6), P('retries', None, 'retries', .4),
             P('inflight', 'responses_total', 'inflight', .5), P('inflight', 'errors_total', 'inflight', .03)]
    m = oe.refit(truth, stocks, run, opts, search=False)
    fl = oe.normalise_drains(m.flows()); sc = score.equations(c, noise, model, fl, d)
    print(v, 'truth-structure OE: bic', round(m.bic, 1), sc['status'], sc['right'], '/', sc['of'])
    for p in sc['parts']: print('   ', 'ok' if p['ok'] else 'X ', p.get('kind'), 'err', round(p['error'], 3), 'tol3se', round(3 * p['se'], 4) if p.get('se') else None)
    for f in fl: print('     ', f['from'], '->', f['to'], f['rate'].get('expr') or [t['k'] for t in f['rate']['terms']])
    print('   status keys:', {k: sc[k] for k in ('pass', 'equivalent', 'spurious', 'invented_boundary', 'notes') if k in sc})
    import numpy as np
    R = m.resid(m.p[None])[0]
    print('   per-stock weighted SSR', dict(zip(m.sim_ids, np.round((R ** 2).sum(0), 0))))
    print('   noise sd median', {k: round(float(np.median(m.sd[k])), 2) for k in m.sim_ids})
    if 'clean' in d:
        print('   true meas sd median', {k: round(float(np.median(np.abs(np.asarray(d['levels'][k]) - np.asarray(d['clean']['levels'][k]))) * 1.4826), 2) for k in m.sim_ids})
