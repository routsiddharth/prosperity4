"""CVaR / max-min portfolio search for R4 manual.

Objective: maximize the 5th percentile of the realized 100-path score, where
the score is the mean PnL over 100 sample paths. We treat that score as a
random variable, draw 1000 independent 100-path subsamples from a large pool
of pre-simulated paths, and use the 5th percentile of that distribution.

Method:
1. Pre-simulate POOL_PATHS paths once and pre-compute the per-path payoff
   matrix for all products: M[k, i] = payoff of product k on path i.
2. Pre-cost row c[k] = ask if long, bid if short — but since direction is
   chosen by the sign of the volume, we maintain two arrays (ask, bid) and
   compute portfolio cost from sign(v).
3. Per-path PnL of a portfolio with vol v (length 12) on path-set indices I
   is `((M[:, I].T @ v) - cost(v)) * CONTRACT_SIZE`.
4. Pre-sample 1000 random 100-index batches once. For each candidate v we
   compute the mean PnL over each batch — that is the 100-path "score"
   distribution. We take np.percentile(scores, 5).
5. Initial guess: mean_var_optimize(risk_lambda=0.003). Then random
   coordinate descent over volumes.
"""

from __future__ import annotations

import numpy as np
import time

from simulator import Simulator, WEEKS_3_STEPS
from products import build_universe
from portfolio import Portfolio, CONTRACT_SIZE
from optimize import mean_var_optimize


# ---------- config ----------
POOL_PATHS = 200_000
N_BATCHES = 1000
BATCH_SIZE = 100
SEARCH_STEPS = 4000
N_RESTARTS = 6
MIN_ASSETS = 6
SEED_POOL = 42
SEED_BATCH = 7
SEED_SEARCH = 13


def build_payoff_matrix(products, paths):
    keys = list(products.keys())
    M = np.stack([products[k].payoff(paths) for k in keys], axis=0)  # (K, N)
    asks = np.array([products[k].ask for k in keys])
    bids = np.array([products[k].bid for k in keys])
    max_vols = np.array([products[k].max_volume for k in keys], dtype=int)
    return keys, M, asks, bids, max_vols


def portfolio_cost(v, asks, bids):
    """Per-unit upfront cost given signed volumes v.
    Long pays ask, short receives bid (so cost is negative for shorts).
    """
    long_mask = v > 0
    short_mask = v < 0
    return float(v[long_mask] @ asks[long_mask] + v[short_mask] @ bids[short_mask])


def per_path_pnl(v, M, asks, bids, contract_size=CONTRACT_SIZE):
    """Per-path PnL across all paths in pool. Shape (N,)."""
    realized = v @ M  # (N,)
    cost = portfolio_cost(v, asks, bids)
    return (realized - cost) * contract_size


def score_distribution(per_path_pnl_arr, batch_indices):
    """Given a (N,)-array of per-path PnL and (N_BATCHES, BATCH_SIZE) indices,
    return the per-batch mean (the 100-path "score") as a (N_BATCHES,) array.
    """
    return per_path_pnl_arr[batch_indices].mean(axis=1)


def p5_objective(v, M, asks, bids, batch_indices):
    pnl = per_path_pnl(v, M, asks, bids)
    scores = score_distribution(pnl, batch_indices)
    return float(np.percentile(scores, 5))


def random_local_search(v_init, M, asks, bids, max_vols, batch_indices,
                        n_steps=SEARCH_STEPS, rng=None, min_assets=MIN_ASSETS):
    if rng is None:
        rng = np.random.default_rng(SEED_SEARCH)
    K = len(v_init)
    v = v_init.copy()
    cur = p5_objective(v, M, asks, bids, batch_indices)

    # Step sizes to try (each will be tried with both + and -)
    step_sizes = [1, 5, 10, 25, 50]
    set_targets_factor = [0.0, 0.25, 0.5, 0.75, 1.0]  # fraction of max_vol

    accepted = 0
    for step in range(n_steps):
        k = int(rng.integers(0, K))
        mv = int(max_vols[k])
        moves = []
        for s in step_sizes:
            moves.append(+s)
            moves.append(-s)
        # Also try absolute set-points (fraction of max_vol, both signs)
        for f in set_targets_factor:
            target = int(round(f * mv))
            for sign in (+1, -1):
                moves.append(sign * target - v[k])  # delta to reach this
        # Try setting to zero (drop)
        moves.append(-v[k])

        # Sample a few moves randomly to keep search broad and cheap
        rng.shuffle(moves)
        moves = moves[:14]

        best_delta = 0
        best_obj = cur
        for d in moves:
            new_v_k = v[k] + d
            if abs(new_v_k) > mv:
                continue
            v_try = v.copy()
            v_try[k] = new_v_k
            # check min_assets constraint
            if int(np.sum(v_try != 0)) < min_assets:
                continue
            obj = p5_objective(v_try, M, asks, bids, batch_indices)
            if obj > best_obj + 1e-6:
                best_obj = obj
                best_delta = d

        if best_delta != 0:
            v[k] += best_delta
            cur = best_obj
            accepted += 1

    return v, cur, accepted


def polish(v, M, asks, bids, max_vols, batch_indices, min_assets=MIN_ASSETS):
    """Sweep every coordinate, try a range of moves until no axis improves."""
    K = len(v)
    cur = p5_objective(v, M, asks, bids, batch_indices)
    improved = True
    rounds = 0
    deltas = (+1, -1, +2, -2, +5, -5, +10, -10, +25, -25, +50, -50)
    while improved and rounds < 80:
        improved = False
        rounds += 1
        for k in range(K):
            mv = int(max_vols[k])
            best_obj = cur
            best_new = v[k]
            for d in deltas:
                new = v[k] + d
                if abs(new) > mv:
                    continue
                v_try = v.copy()
                v_try[k] = new
                if int(np.sum(v_try != 0)) < min_assets:
                    continue
                obj = p5_objective(v_try, M, asks, bids, batch_indices)
                if obj > best_obj + 1e-6:
                    best_obj = obj
                    best_new = new
            if best_new != v[k]:
                v[k] = best_new
                cur = best_obj
                improved = True
    return v, cur, rounds


def random_init(max_vols, rng, min_assets=MIN_ASSETS):
    K = len(max_vols)
    v = np.zeros(K, dtype=int)
    # randomly populate min_assets to all
    n_active = int(rng.integers(min_assets, K + 1))
    active_idx = rng.choice(K, size=n_active, replace=False)
    for k in active_idx:
        sign = int(rng.choice([-1, 1]))
        mag = int(rng.integers(1, max_vols[k] + 1))
        v[k] = sign * mag
    return v


def report(v, keys, products_dict, M, asks, bids, batch_indices, label):
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    pnl = per_path_pnl(v, M, asks, bids)
    scores = score_distribution(pnl, batch_indices)
    n_active = int(np.sum(v != 0))

    pf = Portfolio()
    for k, vi in zip(keys, v):
        if vi != 0:
            pf.add(products_dict[k], int(vi))
    print("\nPosition table:")
    print(pf.describe())

    print("\n100-path score distribution (across 1000 batches):")
    print(f"  p5:     {np.percentile(scores, 5):>14,.0f}")
    print(f"  p25:    {np.percentile(scores, 25):>14,.0f}")
    print(f"  median: {np.percentile(scores, 50):>14,.0f}")
    print(f"  p75:    {np.percentile(scores, 75):>14,.0f}")
    print(f"  p95:    {np.percentile(scores, 95):>14,.0f}")
    print(f"  mean:   {np.mean(scores):>14,.0f}")
    print(f"  std:    {np.std(scores):>14,.0f}")
    print(f"  min:    {np.min(scores):>14,.0f}")
    print(f"  max:    {np.max(scores):>14,.0f}")
    print(f"  P(score > 0):       {np.mean(scores > 0):.3f}")
    print(f"  P(score > 50,000):  {np.mean(scores > 50_000):.3f}")
    print(f"  P(score > 100,000): {np.mean(scores > 100_000):.3f}")
    print(f"  P(score > 200,000): {np.mean(scores > 200_000):.3f}")

    print("\nPer-simulation distribution (over pool):")
    print(f"  mean:    {np.mean(pnl):>14,.0f}")
    print(f"  std:     {np.std(pnl):>14,.0f}")
    print(f"  p5:      {np.percentile(pnl, 5):>14,.0f}")
    print(f"  p25:     {np.percentile(pnl, 25):>14,.0f}")
    print(f"  median:  {np.percentile(pnl, 50):>14,.0f}")
    print(f"  p75:     {np.percentile(pnl, 75):>14,.0f}")
    print(f"  p95:     {np.percentile(pnl, 95):>14,.0f}")
    print(f"  win%:    {np.mean(pnl > 0):.3f}")
    print(f"  n_assets: {n_active}/12")


def main():
    print(f"Simulating {POOL_PATHS:,} paths …")
    t0 = time.time()
    sim = Simulator()
    products_dict = build_universe(binary_payout=10.0, ko_barrier=45.0)
    paths = sim.simulate(n_sims=POOL_PATHS, n_steps=WEEKS_3_STEPS, seed=SEED_POOL)
    print(f"  done in {time.time() - t0:.1f}s")

    keys, M, asks, bids, max_vols = build_payoff_matrix(products_dict, paths)
    K = len(keys)

    # Pre-sample batch indices once. Reusing the same batches across all
    # candidates makes the search smooth (no batch noise inside the loop)
    rng_batch = np.random.default_rng(SEED_BATCH)
    batch_indices = rng_batch.integers(0, POOL_PATHS, size=(N_BATCHES, BATCH_SIZE))

    # ---- Initial: mean-var solve ----
    print("\nWarm-start: mean-var optimization (risk_lambda=0.003) …")
    pf_mv = mean_var_optimize(products_dict, paths, risk_lambda=0.003)
    v_mv = np.zeros(K, dtype=int)
    for kn, (prod, vol) in pf_mv.positions.items():
        v_mv[keys.index(kn)] = vol
    obj_mv = p5_objective(v_mv, M, asks, bids, batch_indices)
    n_active_mv = int(np.sum(v_mv != 0))
    print(f"  mean-var p5 score = {obj_mv:,.0f},   n_assets={n_active_mv}")

    # If MV start has too few assets, fall back to greedy fractional
    if n_active_mv < MIN_ASSETS:
        print("  (MV solution too sparse; using random init instead)")

    # ---- Multi-restart local search ----
    rng = np.random.default_rng(SEED_SEARCH)
    candidates = []

    # Restart 0: from mean-var
    print("\n=== Restart 0: from mean_var_optimize ===")
    t0 = time.time()
    v_best, obj_best, acc = random_local_search(
        v_mv, M, asks, bids, max_vols, batch_indices,
        n_steps=SEARCH_STEPS, rng=rng, min_assets=MIN_ASSETS,
    )
    print(f"  → p5 = {obj_best:,.0f}  (accepted {acc}/{SEARCH_STEPS}) "
          f"in {time.time()-t0:.1f}s")
    candidates.append((obj_best, v_best))

    # Perturbed-MV restarts: take the MV start, randomly perturb a few coords,
    # then local search. Much more likely to find nearby better optima than a
    # fully random start.
    for r in range(1, N_RESTARTS + 1):
        v0 = v_mv.copy()
        # Pick 2-4 random coords to perturb
        n_perturb = int(rng.integers(2, 5))
        idx = rng.choice(K, size=n_perturb, replace=False)
        for i in idx:
            mv = int(max_vols[i])
            sign = int(rng.choice([-1, 1]))
            mag = int(rng.integers(1, mv + 1))
            v0[i] = sign * mag
        # Ensure min assets
        while int(np.sum(v0 != 0)) < MIN_ASSETS:
            zeros = np.where(v0 == 0)[0]
            i = int(rng.choice(zeros))
            mv = int(max_vols[i])
            sign = int(rng.choice([-1, 1]))
            v0[i] = sign * int(rng.integers(1, mv + 1))

        obj0 = p5_objective(v0, M, asks, bids, batch_indices)
        print(f"\n=== Restart {r}: perturbed-MV init (initial p5={obj0:,.0f}) ===")
        t0 = time.time()
        v_r, obj_r, acc = random_local_search(
            v0, M, asks, bids, max_vols, batch_indices,
            n_steps=SEARCH_STEPS, rng=rng, min_assets=MIN_ASSETS,
        )
        print(f"  → p5 = {obj_r:,.0f}  (accepted {acc}/{SEARCH_STEPS}) "
              f"in {time.time()-t0:.1f}s")
        candidates.append((obj_r, v_r))

    # Pick best
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_obj, best_v = candidates[0]

    # ---- Polish best solution: coordinate sweep with small steps ----
    print(f"\n=== Polishing best (p5 = {best_obj:,.0f}) with coordinate sweep ===")
    t0 = time.time()
    best_v, best_obj, rounds = polish(
        best_v, M, asks, bids, max_vols, batch_indices, min_assets=MIN_ASSETS,
    )
    print(f"  → polished p5 = {best_obj:,.0f}  ({rounds} sweep rounds, "
          f"{time.time()-t0:.1f}s)")

    # Final report
    report(v_mv, keys, products_dict, M, asks, bids, batch_indices,
           "BASELINE: mean_var_optimize(risk_lambda=0.003)")
    report(best_v, keys, products_dict, M, asks, bids, batch_indices,
           f"BEST PORTFOLIO (p5 = {best_obj:,.0f})")

    # Show all restart results sorted
    print("\n--- Restart leaderboard ---")
    for i, (o, v) in enumerate(candidates):
        active = int(np.sum(v != 0))
        print(f"  rank {i+1}: p5 = {o:>14,.0f}   n_assets = {active}/12")


if __name__ == '__main__':
    main()
