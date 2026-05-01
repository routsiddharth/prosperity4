"""Numerical portfolio optimizers.

Two solvers:

* greedy_max_mean(paths, products): linear opt, per-product bid/ask edge maxing.
* mean_var_optimize(paths, products, risk_lambda, min_assets):
    quadratic mean-variance opt subject to volume bounds.

Both produce a Portfolio (with integer-rounded volumes).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

from products import Product
from portfolio import Portfolio, CONTRACT_SIZE


def _payoff_matrix(products: dict[str, Product], paths: np.ndarray) -> np.ndarray:
    """Returns payoff matrix shape (n_products, n_sims) and product list."""
    keys = list(products.keys())
    M = np.stack([products[k].payoff(paths) for k in keys], axis=0)
    return keys, M


def greedy_max_mean(products: dict, paths: np.ndarray,
                    fraction: float = 1.0,
                    skip_zero_edge: bool = True) -> Portfolio:
    """Per-product greedy: take max long if buy-edge > 0, max short if sell-edge > 0."""
    pf = Portfolio()
    for name, prod in products.items():
        fv = prod.fair_value(paths)
        edge_buy = fv - prod.ask
        edge_sell = prod.bid - fv
        vol = int(round(prod.max_volume * fraction))
        if vol == 0:
            continue
        if edge_buy > 0 and edge_buy >= edge_sell:
            pf.add(prod, +vol)
        elif edge_sell > 0:
            pf.add(prod, -vol)
        elif not skip_zero_edge:
            pass
    return pf


def mean_var_optimize(products: dict, paths: np.ndarray,
                      risk_lambda: float = 1e-7,
                      contract_size: int = CONTRACT_SIZE,
                      min_active: int = 0) -> Portfolio:
    """Solve  max  c·v − λ·vᵀΣv   subject to |v_i| ≤ max_vol_i.

    `c` is per-unit edge (using bid for shorts, ask for longs), but since the
    optimal side per product is whichever direction is profitable, we model
    each product with a piecewise objective by allowing v to be signed and
    using a midpoint cost approximation, then snap to bid/ask after.

    For a clean solve we instead use a per-product variable v_i ∈ [-max, +max]
    and approximate the bid/ask as a single mid-price.  After solving we re-
    cost using the correct side.  This gives the right portfolio (volumes &
    signs) for tight spreads.
    """
    keys = list(products.keys())
    n = len(keys)
    # midpoints
    mids = np.array([(products[k].bid + products[k].ask) / 2.0 for k in keys])
    fairs = np.array([products[k].fair_value(paths) for k in keys])
    edges = fairs - mids  # per-unit expected PnL if long at mid
    # half-spreads (penalty per unit traded)
    half_spreads = np.array([(products[k].ask - products[k].bid) / 2.0 for k in keys])
    max_vols = np.array([products[k].max_volume for k in keys])
    payoffs = np.stack([products[k].payoff(paths) for k in keys], axis=0)
    # de-meaned payoff matrix
    Pcent = payoffs - payoffs.mean(axis=1, keepdims=True)
    # Σ = Pcent @ Pcent.T / n_sims
    Sigma = Pcent @ Pcent.T / paths.shape[0]

    # Objective (negate for minimize): -[edges·v - half_spreads·|v| - λ vᵀΣv]
    def obj(v):
        m = edges @ v - half_spreads @ np.abs(v)
        var = v @ Sigma @ v
        return -(m - risk_lambda * var)

    def grad(v):
        gm = edges - half_spreads * np.sign(v)
        gv = 2 * Sigma @ v
        return -(gm - risk_lambda * gv)

    # SLSQP-friendly bounds; replace |v| with smooth via abs (handled
    # by sign in grad — fine since we never sit exactly at 0 typically).
    bounds = [(-mv, mv) for mv in max_vols]
    v0 = np.zeros(n)
    res = minimize(obj, v0, jac=grad, bounds=bounds, method='L-BFGS-B',
                   options={'maxiter': 500, 'ftol': 1e-9})
    v_opt = res.x

    # Round to integers (volumes must be integer)
    v_int = np.round(v_opt).astype(int)
    v_int = np.clip(v_int, -max_vols.astype(int), max_vols.astype(int))

    pf = Portfolio(contract_size=contract_size)
    for k, vi, prod_key in zip(keys, v_int, keys):
        if vi == 0:
            continue
        pf.add(products[k], int(vi))
    return pf


def constrained_chooser_arb(products: dict, n: int = 50) -> Portfolio:
    return (Portfolio()
            .sell(products['AC_50_CO'], n)
            .buy(products['AC_50_C'], n)
            .buy(products['AC_50_P_2'], n))


def chooser_arb_plus(products: dict, paths: np.ndarray) -> Portfolio:
    """Chooser arb + add max-edge positions on remaining products."""
    pf = constrained_chooser_arb(products, 50)
    # Now add edge plays on uncommitted products
    for name in ['AC_45_KO', 'AC_40_BP', 'AC_60_C', 'AC_50_C_2',
                 'AC_50_P', 'AC_35_P', 'AC_40_P', 'AC_45_P', 'AC']:
        prod = products[name]
        fv = prod.fair_value(paths)
        edge_buy = fv - prod.ask
        edge_sell = prod.bid - fv
        if edge_buy > 0:
            pf.add(prod, +prod.max_volume)
        elif edge_sell > 0:
            pf.add(prod, -prod.max_volume)
    return pf
