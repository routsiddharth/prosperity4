"""Robustness experiment: distribution of realized scores under 100-path resamples.

Runs the candidate portfolios A..E, each constructed using a large-MC
"true fair value" path bank, and then evaluates each portfolio on 1000
independent 100-path samples (seeds 1000..1999). Reports the distribution of
the *mean realized PnL* (which is what the platform scores).

Also re-runs mean_var_optimize at lambda=0.003 with seeds {1, 2, 3} to gauge
position stability across fair-value seeds.
"""

from __future__ import annotations

import numpy as np

from simulator import Simulator
from products import build_universe
from portfolio import Portfolio
from optimize import mean_var_optimize, constrained_chooser_arb


N_FV_PATHS = 500_000           # large MC for "true fair value"
FV_SEED = 42
N_SCORE_SAMPLES = 1000         # number of independent 100-path samples
PATHS_PER_SAMPLE = 100         # the platform uses 100 paths
SAMPLE_SEED_BASE = 1000


def build_candidate_portfolios(products, fv_paths) -> dict[str, Portfolio]:
    pf = {}
    pf['A_chooser_arb']        = constrained_chooser_arb(products, 50)
    pf['B_meanvar_lam_0.003']  = mean_var_optimize(products, fv_paths, risk_lambda=0.003)
    pf['C_meanvar_lam_0.01']   = mean_var_optimize(products, fv_paths, risk_lambda=0.01)
    pf['D_meanvar_lam_0.001']  = mean_var_optimize(products, fv_paths, risk_lambda=0.001)
    pf['E_meanvar_lam_0.0003'] = mean_var_optimize(products, fv_paths, risk_lambda=0.0003)
    return pf


def realized_score_distribution(portfolio: Portfolio, sim: Simulator,
                                n_samples: int, paths_per_sample: int,
                                seed_base: int) -> np.ndarray:
    """Return array of n_samples realized scores (each = mean PnL over 100 paths)."""
    scores = np.empty(n_samples)
    for i in range(n_samples):
        seed = seed_base + i
        paths = sim.simulate(paths_per_sample, seed=seed)
        scores[i] = float(portfolio.pnl(paths).mean())
    return scores


def summarize(scores: np.ndarray) -> dict:
    return {
        'mean':   float(np.mean(scores)),
        'std':    float(np.std(scores)),
        'min':    float(np.min(scores)),
        'p5':     float(np.percentile(scores, 5)),
        'p25':    float(np.percentile(scores, 25)),
        'median': float(np.percentile(scores, 50)),
        'p75':    float(np.percentile(scores, 75)),
        'p95':    float(np.percentile(scores, 95)),
        'max':    float(np.max(scores)),
        'win':    float(np.mean(scores > 0)),
        'gt50k':  float(np.mean(scores > 50_000)),
        'gt100k': float(np.mean(scores > 100_000)),
    }


def positions_dict(pf: Portfolio) -> dict[str, int]:
    return {name: vol for name, (_, vol) in pf.positions.items() if vol != 0}


def main():
    sim = Simulator()
    products = build_universe(binary_payout=10.0, ko_barrier=45.0)

    print(f"Building 'true' fair-value path bank: {N_FV_PATHS} paths, seed={FV_SEED} ...")
    fv_paths = sim.simulate(N_FV_PATHS, seed=FV_SEED)

    print("Constructing candidate portfolios ...\n")
    candidates = build_candidate_portfolios(products, fv_paths)

    # Show portfolio descriptions
    for name, pf in candidates.items():
        print(f"=== {name} ===")
        print(pf.describe())
        print()

    # Now resample 1000 independent 100-path samples per portfolio
    print(f"Sampling realized scores: {N_SCORE_SAMPLES} samples x "
          f"{PATHS_PER_SAMPLE} paths each ...\n")

    # For efficiency: pre-generate the path samples ONCE and reuse for all portfolios.
    # That gives matched-sample comparison and saves time.
    all_sample_paths = []
    for i in range(N_SCORE_SAMPLES):
        all_sample_paths.append(sim.simulate(PATHS_PER_SAMPLE,
                                              seed=SAMPLE_SEED_BASE + i))

    summaries = {}
    raw_scores = {}
    for name, pf in candidates.items():
        scores = np.empty(N_SCORE_SAMPLES)
        for i, paths in enumerate(all_sample_paths):
            scores[i] = float(pf.pnl(paths).mean())
        summaries[name] = summarize(scores)
        raw_scores[name] = scores

    # Print a nicely formatted table
    cols = ['mean', 'std', 'p5', 'p25', 'median', 'p75', 'p95',
            'min', 'max', 'win', 'gt50k', 'gt100k']
    header = f"{'portfolio':<26}" + "".join(f"{c:>11}" for c in cols)
    print(header)
    print("-" * len(header))
    for name, s in summaries.items():
        row = f"{name:<26}"
        for c in cols:
            v = s[c]
            if c in ('win', 'gt50k', 'gt100k'):
                row += f"{v:>11.3f}"
            else:
                row += f"{v:>11,.0f}"
        print(row)
    print()

    # Best lambda by p5
    best_p5 = max(summaries.items(), key=lambda kv: kv[1]['p5'])
    print(f"Best p5 (guaranteed-min profit): {best_p5[0]} -> p5 = {best_p5[1]['p5']:,.0f}\n")

    # Stability of optimizer across fair-value seeds
    print("=== Optimizer position stability across fair-value seeds ===")
    fv_seeds = [1, 2, 3]
    pos_per_seed = {}
    n_fv_paths_stab = 200_000   # spec says "the *specific 200k seed*"
    for s in fv_seeds:
        paths_s = sim.simulate(n_fv_paths_stab, seed=s)
        pf_s = mean_var_optimize(products, paths_s, risk_lambda=0.003)
        pos_per_seed[s] = positions_dict(pf_s)

    all_keys = sorted({k for d in pos_per_seed.values() for k in d})
    header = f"{'product':<14}" + "".join(f"{f'seed={s}':>10}" for s in fv_seeds)
    print(header)
    print("-" * len(header))
    for k in all_keys:
        row = f"{k:<14}"
        for s in fv_seeds:
            row += f"{pos_per_seed[s].get(k, 0):>10d}"
        print(row)

    # Quick stability score: max abs difference across seeds, per product
    print("\nMax |position difference| across seeds, per product:")
    diffs = {}
    for k in all_keys:
        vals = [pos_per_seed[s].get(k, 0) for s in fv_seeds]
        diffs[k] = max(vals) - min(vals)
    for k, d in sorted(diffs.items(), key=lambda x: -x[1]):
        print(f"  {k:<14} {d:>5d}")

    # Also evaluate the seed=1,2,3 portfolios on the 1000-sample bank to compare
    print("\nRealized-score distribution of the seed-perturbed lam=0.003 portfolios:")
    print(header.replace(f"{'product':<14}", f"{'fv_seed':<14}"))
    for s, pf_s in [(s, mean_var_optimize(products, sim.simulate(n_fv_paths_stab, seed=s), risk_lambda=0.003))
                    for s in fv_seeds]:
        scores = np.empty(N_SCORE_SAMPLES)
        for i, paths in enumerate(all_sample_paths):
            scores[i] = float(pf_s.pnl(paths).mean())
        sm = summarize(scores)
        print(f"fv_seed={s:<6} mean={sm['mean']:>11,.0f}  std={sm['std']:>10,.0f}  "
              f"p5={sm['p5']:>11,.0f}  median={sm['median']:>11,.0f}  win={sm['win']:.3f}")


if __name__ == '__main__':
    main()
