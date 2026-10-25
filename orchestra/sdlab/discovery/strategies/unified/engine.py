"""The step function, in JAX: the engine's order for one step of a Structure (unified-design.md, 2.4).

    inputs -> rates (base x effects, floored unless two-way) -> x dt (sub-steps) -> floor share
    -> ceiling share -> move (levels floored at 0 unless signed)

Injections are added before the step by the filter. Everything a structure fixes (readers, the
stoichiometry, who takes from which stock) is closed over; the numbers come in as theta, so one traced
function serves every fit of a structure and its derivatives come from JAX.
"""

from __future__ import annotations

from .frontend import Structure


def make_step(st: Structure):
    """step(theta_ext, x, tidx_row, u_row) -> (x_next, amounts over the step, per flow). theta_ext is
    theta with a trailing 0 (the fixed-zero slot)."""
    import jax.numpy as np

    F = len(st.flows)
    term_reader = np.asarray(st.term_reader, dtype=int)
    V0 = np.asarray(st.V)
    onehot = np.asarray(__import__("numpy").eye(max(F, 1))[st.term_flow][:, :F]) if st.term_flow else None
    two_way = np.asarray(st.two_way)
    unsigned = ~np.asarray(st.signed)
    dt = 1.0 / st.n_sub
    # who takes from each stock: (flow, fixed weight) and co-flows (flow, slot)
    takers = {}
    for fi, f in enumerate(st.flows):
        if f.get("from") is not None:
            c = st.ids.index(f["from"])
            takers.setdefault(c, []).append((fi, float(f.get("ratio") or 1), None))
    for fi, c, sl in st.uses:
        takers.setdefault(c, []).append((fi, None, sl))
    takers = {c: takers[c] for c in sorted(takers) if not bool(st.signed[c])}     # stock by stock, in order, as the engine
    into = {c: [fi for fi, f in enumerate(st.flows) if f.get("to") == st.ids[c]] for c, _ in st.ceilings}
    rows = {c: np.asarray([any(fi == x for x, _, _ in tk) for fi in range(F)]) for c, tk in takers.items()}
    cap_rows = {c: np.asarray([fi in ins for fi in range(F)]) for c, ins in into.items()}
    effects = st.effects
    uses = st.uses

    def stoich(th):
        V = V0
        for fi, c, sl in uses:
            V = V.at[c, fi].add(-th[sl])
        return V

    def amounts(th, x, trow, urow):
        z = np.concatenate([x, urow, np.ones(1)])
        coef = th[trow]
        base = (coef * z[term_reader]) @ onehot if len(st.term_flow) else np.zeros(F)
        r = np.where(two_way, base, np.maximum(base, 0.0))
        for e in effects:
            fi, rd = e[0], e[1]
            v = z[rd]
            if e[2] == "table":
                xs = np.asarray(e[3])
                ys = th[np.asarray(e[4])]
                m = np.maximum(0.0, np.interp(v, xs, ys))
            else:
                normal, lo, hi = (th[p] if not isinstance(p, tuple) else p[1] for p in e[3:6])
                m = np.minimum(hi, np.maximum(lo, v / np.maximum(1e-9, normal)))
            r = r * np.where(np.arange(F) == fi, m, 1.0)
        return r

    def share(th, x, a):
        for c, tk in takers.items():
            w = [(fi, wt if wt is not None else th[sl]) for fi, wt, sl in tk]
            want = sum(a[fi] * wt for fi, wt in w)
            lvl = x[c]
            k = np.where((want > lvl) & (lvl > -1), np.maximum(0.0, lvl) / np.where(want > 0, want, 1.0), 1.0)
            a = a * np.where(rows[c], k, 1.0)
        for c, cap in st.ceilings:
            ins = into.get(c) or []
            if not ins:
                continue
            want = a[np.asarray(ins)].sum()
            room = np.maximum(0.0, cap - x[c])
            k = np.where(want > room, room / np.where(want > 0, want, 1.0), 1.0)
            a = a * np.where(cap_rows[c], k, 1.0)
        return a

    def step(th, x, trow, urow):
        V = stoich(th)
        total = np.zeros(F)
        for _ in range(st.n_sub):
            a = amounts(th, x, trow, urow) * dt
            a = share(th, x, a)
            x = x + V @ a
            x = np.where(unsigned, np.maximum(x, 0.0), x)
            total = total + a
        return x, total

    step.stoich = stoich
    step.takers = takers
    return step
