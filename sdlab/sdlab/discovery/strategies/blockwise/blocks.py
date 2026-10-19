"""Weakly coupled blocks of stocks, and a model joined from the candidates block by block.

The blocks: the graph whose edges are the levels each row chose (a stock's change follows another
stock's level), split into connected components; a component larger than `most` is split again by
complete-linkage clustering on how little the stocks' changes are correlated. A measured input that
drives everything (traffic) is a column, not a stock, so it joins no blocks together.

The join: each block takes its rows from the candidate whose model behaves best on that block's
stocks (judge.py's per-stock errors); the rows are read into flows together (conservation and moves
across blocks included), and the joined model is judged as a whole.
"""

from __future__ import annotations

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial.distance import squareform


def blocks_of(ids: list[str], graph: dict[str, list[str]], dy: np.ndarray, most: int = 12) -> list[list[str]]:
    index = {s: i for i, s in enumerate(ids)}
    S = len(ids)
    r, c = [], []
    for a, js in graph.items():
        for b in js:
            if b in index:
                r.append(index[a])
                c.append(index[b])
    A = csr_matrix((np.ones(len(r)), (r, c)), shape=(S, S))
    _, lab = connected_components(A, directed=False)
    out = []
    for g in np.unique(lab):
        members = np.flatnonzero(lab == g)
        if len(members) <= most:
            out.append([ids[i] for i in members])
            continue
        with np.errstate(all="ignore"):
            C = np.nan_to_num(np.corrcoef(dy[members]))
        D = 1 - np.abs(C)
        np.fill_diagonal(D, 0)
        Z = linkage(squareform(np.clip((D + D.T) / 2, 0, None), checks=False), "complete")
        k = int(np.ceil(len(members) / most))
        sub = fcluster(Z, k, "maxclust")
        for q in np.unique(sub):
            out.append([ids[i] for i in members[sub == q]])
    return out


def pick_rows(cands: list[dict], blocks: list[list[str]], ids: list[str]) -> tuple[dict[str, int], str]:
    """For each stock, the candidate (index) whose model behaves best on its block: the block's
    share of the error in the data's own units plus its share with every stock weighed alike."""
    index = {s: i for i, s in enumerate(ids)}
    choice, picked = {}, []
    for b in blocks:
        idx = [index[s] for s in b]
        err = np.array([float(np.sum(c["per"][idx]) + np.sum(c["per_raw"][idx])) for c in cands])
        k = int(np.argmin(np.where(np.isfinite(err), err, np.inf)))
        picked.append(k)
        for s in b:
            choice[s] = k
    counts = np.bincount(picked, minlength=len(cands))
    desc = ", ".join(f"{cands[k]['name']} x{n}" for k, n in enumerate(counts) if n)
    return choice, desc
