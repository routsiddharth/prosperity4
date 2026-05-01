"""Main entry point: print fair values, edges, and evaluate sample portfolios.

Usage:
    python main.py                 # default — show fair values + sample portfolios
    python main.py --paths 200000  # use more MC paths for fair-value accuracy
"""

from __future__ import annotations

import argparse
import numpy as np

from simulator import Simulator, WEEKS_3_STEPS
from products import build_universe
from portfolio import Portfolio, CONTRACT_SIZE


def report_fair_values(products: dict, paths: np.ndarray) -> dict[str, dict]:
    """Compute fair value, bid/ask, and edges for each product."""
    print(f"\n{'Product':<12} {'Bid':>8} {'Ask':>8} {'FairMC':>10} "
          f"{'EdgeBuy':>9} {'EdgeSell':>9} {'Action':<6} {'EdgeMax':>9}")
    print('-' * 80)
    out = {}
    for name, prod in products.items():
        fv = prod.fair_value(paths)
        edge_buy = fv - prod.ask        # gain per unit if bought
        edge_sell = prod.bid - fv       # gain per unit if sold
        if edge_buy >= edge_sell and edge_buy > 0:
            action, edge = 'BUY', edge_buy
        elif edge_sell > edge_buy and edge_sell > 0:
            action, edge = 'SELL', edge_sell
        else:
            action, edge = 'skip', max(edge_buy, edge_sell)
        out[name] = dict(fair=fv, edge_buy=edge_buy, edge_sell=edge_sell,
                         action=action, edge_max=edge)
        print(f"{name:<12} {prod.bid:>8.4f} {prod.ask:>8.4f} {fv:>10.4f} "
              f"{edge_buy:>+9.4f} {edge_sell:>+9.4f} {action:<6} {edge:>+9.4f}")
    return out


def greedy_portfolio(products: dict, fv_report: dict, fraction: float = 1.0) -> Portfolio:
    """Take the unconstrained-greedy positions: max long if edge_buy > 0,
    max short if edge_sell > 0. `fraction` scales the volume (0..1)."""
    pf = Portfolio()
    for name, prod in products.items():
        info = fv_report[name]
        vol = int(round(prod.max_volume * fraction))
        if info['edge_buy'] > 0 and info['edge_buy'] >= info['edge_sell']:
            pf.add(prod, +vol)
        elif info['edge_sell'] > 0:
            pf.add(prod, -vol)
    return pf


def chooser_arb_portfolio(products: dict, n: int = 50) -> Portfolio:
    """Pure replication: short chooser, long 3wk call + 2wk put.
    PnL is path-independent (assuming put-call parity holds).
    """
    return (Portfolio()
            .sell(products['AC_50_CO'], n)
            .buy(products['AC_50_C'], n)
            .buy(products['AC_50_P_2'], n))


def evaluate(name: str, pf: Portfolio, paths: np.ndarray):
    s = pf.stats(paths)
    print(f"\n--- {name} ---")
    print(pf.describe())
    print(f"\n{'mean':<10}{s['mean']:>14,.0f}")
    print(f"{'std':<10}{s['std']:>14,.0f}")
    print(f"{'min':<10}{s['min']:>14,.0f}")
    print(f"{'p5':<10}{s['p5']:>14,.0f}")
    print(f"{'median':<10}{s['median']:>14,.0f}")
    print(f"{'p95':<10}{s['p95']:>14,.0f}")
    print(f"{'max':<10}{s['max']:>14,.0f}")
    print(f"{'win_rate':<10}{s['win_rate']:>14.2%}")
    print(f"{'sharpe':<10}{s['sharpe']:>14.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths', type=int, default=200_000,
                    help='# of MC paths for fair-value estimation (default 200k)')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--binary-payout', type=float, default=10.0,
                    help='Payout amount for AC_40_BP if triggered')
    ap.add_argument('--ko-barrier', type=float, default=45.0,
                    help='Knock-out barrier for AC_45_KO')
    args = ap.parse_args()

    sim = Simulator()
    products = build_universe(binary_payout=args.binary_payout,
                              ko_barrier=args.ko_barrier)

    print(f"Simulating {args.paths:,} paths over {WEEKS_3_STEPS} steps "
          f"(σ=2.51 ann., r=0)...")
    paths = sim.simulate(n_sims=args.paths, n_steps=WEEKS_3_STEPS, seed=args.seed)

    fv_report = report_fair_values(products, paths)

    # ----- sample portfolios -----
    evaluate("PURE CHOOSER ARB (50× short chooser hedged with call+put)",
             chooser_arb_portfolio(products, 50),
             paths)

    evaluate("GREEDY MAX-EDGE (full size)",
             greedy_portfolio(products, fv_report, fraction=1.0),
             paths)

    evaluate("GREEDY MAX-EDGE (75% size)",
             greedy_portfolio(products, fv_report, fraction=0.75),
             paths)


if __name__ == '__main__':
    main()
