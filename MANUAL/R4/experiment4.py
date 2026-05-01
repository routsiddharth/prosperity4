"""Final tuning: explore tiny chooser-arb add to top portfolios.

The chooser arb (short CO, long C+P_2 at K=50) has +$0.335 edge per unit.
But it adds variance through path-dependent payoff differences.

For our top portfolio (KO500 + 5x1 singles), each unit of chooser arb adds:
  - +$0.335 * 3000 = $1005 mean
  - some std contribution
What's the variance contribution per unit?
"""

from __future__ import annotations

import itertools
import numpy as np
from simulator import Simulator, WEEKS_3_STEPS
from products import build_universe
from portfolio import Portfolio


def stats_row(name, pf, paths):
    s = pf.stats(paths)
    score = s['mean'] - 2 * s['std']
    return {
        'name': name, 'mean': s['mean'], 'std': s['std'],
        'p5': s['p5'], 'p25': s['p25'], 'median': s['median'],
        'sharpe': s['sharpe'], 'win': s['win_rate'],
        'n': s['n_assets_used'], 'score': score, 'pf': pf,
    }


def fmt(r):
    return (f"{r['name']:<78} mean={r['mean']:>9,.0f} std={r['std']:>9,.0f} "
            f"p5={r['p5']:>9,.0f} p25={r['p25']:>8,.0f} med={r['median']:>8,.0f} "
            f"sh={r['sharpe']:>5.2f} w={r['win']:>5.1%} n={r['n']:>2} "
            f"score={r['score']:>10,.0f}")


def main():
    sim = Simulator()
    products = build_universe()
    print("Simulating 500,000 paths (final validation grade)…", flush=True)
    paths = sim.simulate(500_000, n_steps=WEEKS_3_STEPS, seed=42)

    rows = []

    # The winning core: KO500 short + tiny longs/shorts.
    # Variations to push higher:
    print("=== Winning core variants ===")

    base_singles = ['AC_50_P_2', 'AC_50_C', 'AC_60_C', 'AC_40_BP', 'AC_35_P']

    # Variant A: +1 chooser arb (n=8 assets)
    pf = Portfolio()
    pf.sell(products['AC_45_KO'], 500)
    pf.buy(products['AC_50_P_2'], 1)
    pf.buy(products['AC_50_C'], 1)
    pf.sell(products['AC_60_C'], 1)
    pf.sell(products['AC_40_BP'], 1)
    pf.sell(products['AC_35_P'], 1)
    # add chooser arb on top
    pf.sell(products['AC_50_CO'], 1)
    pf.buy(products['AC_50_C'], 1)  # adds to existing
    pf.buy(products['AC_50_P_2'], 1) # adds to existing
    rows.append(stats_row("WIN+ChArb1 (8 asset)", pf, paths))
    print(fmt(rows[-1]))

    for n_co in [1, 2, 3, 5, 10]:
        pf = Portfolio()
        pf.sell(products['AC_45_KO'], 500)
        pf.sell(products['AC_50_CO'], n_co)
        pf.buy(products['AC_50_C'], 1 + n_co)
        pf.buy(products['AC_50_P_2'], 1 + n_co)
        pf.sell(products['AC_60_C'], 1)
        pf.sell(products['AC_40_BP'], 1)
        pf.sell(products['AC_35_P'], 1)
        rows.append(stats_row(f"WIN+ChArb{n_co} (6 asset)", pf, paths))
        print(fmt(rows[-1]))

    # Variant B: bear put spread layer
    print("\n=== With bear put spread ===")
    for n_sp in [1, 2, 3, 5, 10, 25, 50]:
        pf = Portfolio()
        pf.sell(products['AC_45_KO'], 500)
        pf.buy(products['AC_50_P_2'], 1)
        pf.buy(products['AC_50_C'], 1)
        pf.sell(products['AC_60_C'], 1)
        pf.sell(products['AC_40_BP'], 1)
        # spread:
        pf.buy(products['AC_45_P'], n_sp)
        pf.sell(products['AC_35_P'], n_sp)
        rows.append(stats_row(f"WIN+BPS45/35x{n_sp} (6 asset)", pf, paths))
        print(fmt(rows[-1]))

    # Variant C: bear put spread + chooser arb
    print("\n=== Combined: ChArb + BPS ===")
    for n_co in [1, 2, 3, 5, 10]:
        for n_sp in [1, 5, 10, 25, 50]:
            pf = Portfolio()
            pf.sell(products['AC_45_KO'], 500)
            pf.sell(products['AC_50_CO'], n_co)
            pf.buy(products['AC_50_C'], 1 + n_co)
            pf.buy(products['AC_50_P_2'], 1 + n_co)
            pf.sell(products['AC_60_C'], 1)
            pf.sell(products['AC_40_BP'], 1)
            pf.buy(products['AC_45_P'], n_sp)
            pf.sell(products['AC_35_P'], n_sp)
            rows.append(stats_row(
                f"WIN+ChArb{n_co}+BPS{n_sp} (8 asset)", pf, paths))

    rows.sort(key=lambda r: -r['score'])
    print("\nTop 15 combined ChArb+BPS:")
    for r in rows[:15]:
        print(fmt(r))

    # Stretch: 9-12 assets minimum (use AC + extra C2)
    print("\n=== 9+ asset configs ===")
    rows_big = []
    for n_co in [1, 3, 5]:
        for n_sp in [10, 25, 50]:
            for n_AC in [10, 50, 100]:
                for n_c2 in [1, 5, 25, 50]:
                    for n_40p in [0, 1, 5]:
                        pf = Portfolio()
                        pf.sell(products['AC_45_KO'], 500)
                        pf.sell(products['AC_50_CO'], n_co)
                        pf.buy(products['AC_50_C'], n_co)
                        pf.buy(products['AC_50_P_2'], n_co)
                        pf.sell(products['AC_60_C'], 1)
                        pf.sell(products['AC_40_BP'], 1)
                        pf.buy(products['AC_45_P'], n_sp)
                        pf.sell(products['AC_35_P'], n_sp)
                        pf.buy(products['AC'], n_AC)
                        pf.buy(products['AC_50_C_2'], n_c2)
                        pf.add(products['AC_50_P'], +1)  # buy 1 of 50P
                        if n_40p:
                            pf.sell(products['AC_40_P'], n_40p)
                        if pf.n_assets_used >= 9:
                            tag = (f"BIG: ChArb={n_co} BPS={n_sp} AC={n_AC} "
                                   f"C2={n_c2} 50P=+1 40Ps={n_40p}")
                            rows_big.append(stats_row(tag, pf, paths))

    rows_big.sort(key=lambda r: -r['score'])
    print(f"Top 15 of {len(rows_big)} 9+ asset:")
    for r in rows_big[:15]:
        print(fmt(r))

    # Combine all
    all_rows = rows + rows_big
    all_rows.sort(key=lambda r: -r['score'])

    print("\n\n========== FINAL TOP 15 BY SCORE ==========")
    for r in all_rows[:15]:
        print(fmt(r))

    print("\n========== TOP 10 BY p5 ==========")
    all_rows.sort(key=lambda r: -r['p5'])
    for r in all_rows[:10]:
        print(fmt(r))

    print("\n========== TOP 10 BY MEAN (n>=6) ==========")
    high = [r for r in all_rows if r['n'] >= 6]
    high.sort(key=lambda r: -r['mean'])
    for r in high[:10]:
        print(fmt(r))

    # ============================================================
    # PRINT DETAIL FOR TOP 3 by score
    # ============================================================
    all_rows.sort(key=lambda r: -r['score'])
    print("\n\n========== DETAIL: TOP 3 BY SCORE ==========")
    for i, r in enumerate(all_rows[:3]):
        print(f"\n*** #{i+1}: {r['name']} ***")
        print(r['pf'].describe())
        print(fmt(r))


if __name__ == '__main__':
    main()
