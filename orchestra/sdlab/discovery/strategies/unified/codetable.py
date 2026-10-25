"""Code-table versions: how the noise character eta is estimated and priced (unified-objective-test.md,
failure M1: eta free per candidate absorbs mean structure). Each version is ONE global choice, the
same for every case, set, variant and input type; nothing here reads the data's kind.

    v1                    (default) eta = (phi, beta, tau, alpha, rho2) fitted freely by every fit of
                          every candidate; its price is taken to cancel and is left out.
    v2-<option>[+<option>...]   one or more of:

    eta-lean     eta fitted ONCE per data set, on the lean model (each measured stock: a constant
                 inflow and an own drain, eta free; design 6, step 1a), then held fixed for every
                 candidate, truth included. Its price is paid once, so it really cancels.
    eta-joint    eta fitted ONCE per data set, jointly across the candidate set: the eta that
                 minimises the sum over candidates of D(theta_c, eta) at each candidate's own
                 free-eta fit; then held fixed for every candidate (who are refitted in theta).
    phi-lean     only the dispersion phi is held at one value per data set (from the lean model);
    phi-joint    ... or from the joint fit across the candidate set; beta, tau, alpha and rho2 stay
                 free per candidate. phi is one number for every stock in every version (kalman.py),
                 so this makes it one number for the data set, priced once.
    tau-priced   each per-stock shock variance tau_s is a priced element: off (ln tau at TAU_OFF)
                 unless turning it on lowers J by more than its price 1/2 ln N_s (N_s the stock's
                 scored reports; the pooled hidden-stock tau: all scored reports). When counting noise
                 explains the innovations, tau stays off.
    phi-prior[=w]  a prior on ln phi, normal, centred on 0 (phi = 1) with declared width w (default
                 1.0): J gains 1/2 (ln phi / w)^2 (its normalising constant is the same for every
                 candidate and left out), and every fit minimises D plus it. Applied to every case.

Pinning phi to the counting value where reports are whole numbers is NOT an option: it branches on
the input type.

The active version comes from the environment variable SDLAB_UNIFIED_CODE_TABLE (default v1), so the
objective test's worker processes inherit it; `objective-test --code-table NAME` sets it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ENV = "SDLAB_UNIFIED_CODE_TABLE"
DEFAULT = "v1"
TAU_OFF = -40.0                 # ln tau of a tau that is off (the bound; exp(-40) x scale^2 is ~0)
PHI_PRIOR_WIDTH = 1.0           # the declared default width of the ln phi prior
OPTIONS = ("eta-lean", "eta-joint", "phi-lean", "phi-joint", "tau-priced", "phi-prior")


@dataclass(frozen=True)
class Table:
    held: str = ""              # "" (nothing held), "all" (every eta component) or "phi"
    source: str = ""            # where a held value comes from: "lean" or "joint"
    tau_priced: bool = False
    phi_prior: float | None = None   # the prior's width on ln phi, or None

    @property
    def name(self) -> str:
        tok = []
        if self.held:
            tok.append(f"{'eta' if self.held == 'all' else 'phi'}-{self.source}")
        if self.tau_priced:
            tok.append("tau-priced")
        if self.phi_prior is not None:
            tok.append("phi-prior" if self.phi_prior == PHI_PRIOR_WIDTH else f"phi-prior={self.phi_prior:g}")
        return "v2-" + "+".join(sorted(tok)) if tok else DEFAULT

    @property
    def is_v1(self) -> bool:
        return self.name == DEFAULT

    def free_only(self) -> "Table":
        """The same table with nothing held (how the lean reference and the joint first pass fit)."""
        return Table(tau_priced=self.tau_priced, phi_prior=self.phi_prior)

    def held_index(self, m: int) -> list[int]:
        """The eta components held at the data set's value (m measured stocks; kalman.eta_names)."""
        if self.held == "all":
            return list(range(3 + 3 * m))
        if self.held == "phi":
            return [0]
        return []


def parse(name: str | None) -> Table:
    name = (name or DEFAULT).strip()
    if name == DEFAULT:
        return Table()
    if not name.startswith("v2-"):
        raise ValueError(f"unknown code table {name!r}: v1, or v2-<option>[+<option>...] with options {', '.join(OPTIONS)}")
    held = source = ""
    tau = False
    prior = None
    for tok in name[3:].split("+"):
        key, _, val = tok.partition("=")
        if key in ("eta-lean", "eta-joint", "phi-lean", "phi-joint") and not val:
            if held:
                raise ValueError(f"{name!r}: at most one of eta-lean, eta-joint, phi-lean, phi-joint")
            held, source = ("all" if key.startswith("eta") else "phi"), key.split("-")[1]
        elif key == "tau-priced" and not val:
            tau = True
        elif key == "phi-prior":
            prior = float(val) if val else PHI_PRIOR_WIDTH
            if not prior > 0:
                raise ValueError(f"{name!r}: the phi prior's width must be positive")
        else:
            raise ValueError(f"{name!r}: unknown option {tok!r} (have {', '.join(OPTIONS)})")
    if held == "all" and (tau or prior is not None):
        raise ValueError(f"{name!r}: with every eta component held, tau-priced and phi-prior have nothing to act on")
    if held == "phi" and prior is not None:
        raise ValueError(f"{name!r}: phi is held, so a prior on it has nothing to act on")
    return Table(held, source, tau, prior)


def active() -> Table:
    return parse(os.environ.get(ENV))


__all__ = ["Table", "parse", "active", "ENV", "DEFAULT", "TAU_OFF", "PHI_PRIOR_WIDTH", "OPTIONS"]
