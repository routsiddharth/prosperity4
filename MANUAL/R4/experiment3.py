"""Final tuning: small chooser-arb + KO short + spread + variations.

Reduced grid for speed.
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
    return (f"{r['name']:<70} mean={r['mean']:>9,.0f} std={r['std']:>9,.0f} "
            f"p5={r['p5']:>9,.0f} p25={r['p25']:>8,.0f} med={r['median']:>8,.0f} "
            f"sh={r['sharpe']:>5.2f} w={r['win']:>5.1%} n={r['n']:>2} "
            f"score={r['score']:>10,.0f}")


def main():
    sim = Simulator()
    products = build_universe()
    print("Simulating 200,000 paths…", flush=True)
    paths = sim.simulate(200_000, n_steps=WEEKS_3_STEPS, seed=42)

    rows = []

    # --------------------------------------------------------------
    # CORE INSIGHT (from prior runs):
    # KO short 500 standalone: mean $220k, std $152k, sharpe 1.45, p5 $225k
    # The KO is essentially "free money" since fair value is ~0.003 vs bid 0.15.
    # The optimizer at λ=0.003 had mean $241k std $181k sharpe 1.33 — barely
    # different from pure KO short (which only uses 1 asset!).
    # We need to add 5+ assets while keeping sharpe high.
    # --------------------------------------------------------------

    # ============================================================
    # Stage 1: KO500 + small chooser arb (n=4 assets) + 2 small singles
    # ============================================================
    print("\n=== Stage 1: KO500 + small ChArb + small singles ===", flush=True)
    edge_singles = {
        'AC_50_C_2':  +1,   # buy, edge +0.113
        'AC_60_C':    -1,   # sell, edge +0.040
        'AC_40_BP':   -1,   # sell, edge +0.236
    }
    # Vary chooser size, then 4 single-products at small size
    for n_co in [1, 3, 5, 8, 10, 15]:
        for n_60 in [0, 5, 10, 25, 50]:
            for n_bp in [0, 5, 10, 25, 50]:
                for n_c2 in [0, 5, 10, 25, 50]:
                    pf = Portfolio()
                    pf.sell(products['AC_45_KO'], 500)
                    pf.sell(products['AC_50_CO'], n_co)
                    pf.buy(products['AC_50_C'], n_co)
                    pf.buy(products['AC_50_P_2'], n_co)
                    if n_60:
                        pf.sell(products['AC_60_C'], n_60)
                    if n_bp:
                        pf.sell(products['AC_40_BP'], n_bp)
                    if n_c2:
                        pf.buy(products['AC_50_C_2'], n_c2)
                    if pf.n_assets_used >= 6:
                        tag = f"S1: KO500+CO{n_co}+C60s{n_60}+BPs{n_bp}+C2{n_c2}"
                        rows.append(stats_row(tag, pf, paths))

    rows.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(rows)}:")
    for r in rows[:10]:
        print(fmt(r))

    # ============================================================
    # Stage 2: + bear put spread layer
    # ============================================================
    print("\n=== Stage 2: + bear put spread ===", flush=True)
    rows2 = []
    for n_co in [3, 5, 10]:
        for n_60 in [0, 10, 25]:
            for n_bp in [0, 25, 50]:
                for spread in [('AC_45_P','AC_35_P'),
                               ('AC_45_P','AC_40_P'),
                               ('AC_50_P','AC_40_P'),
                               ('AC_50_P','AC_45_P')]:
                    for n_sp in [10, 25, 50]:
                        pf = Portfolio()
                        pf.sell(products['AC_45_KO'], 500)
                        pf.sell(products['AC_50_CO'], n_co)
                        pf.buy(products['AC_50_C'], n_co)
                        pf.buy(products['AC_50_P_2'], n_co)
                        if n_60:
                            pf.sell(products['AC_60_C'], n_60)
                        if n_bp:
                            pf.sell(products['AC_40_BP'], n_bp)
                        pf.buy(products[spread[0]], n_sp)
                        pf.sell(products[spread[1]], n_sp)
                        if pf.n_assets_used >= 6:
                            tag = (f"S2: KO500+CO{n_co}+C60s{n_60}+BPs{n_bp}+"
                                   f"{spread[0][3:]}/{spread[1][3:]}x{n_sp}")
                            rows2.append(stats_row(tag, pf, paths))

    rows2.sort(key=lambda r: -r['score'])
    print(f"Top 15 of {len(rows2)}:")
    for r in rows2[:15]:
        print(fmt(r))

    # ============================================================
    # Stage 3: Push to high n with combined elements
    # ============================================================
    print("\n=== Stage 3: high-n configs ===", flush=True)
    rows3 = []
    for n_co in [3, 5]:
        for n_60 in [10, 25]:
            for n_bp in [25, 50]:
                for n_sp1 in [25, 50]:  # 45/35 PUT
                    for n_sp2 in [0, 25, 50]:  # 50/40 PUT
                        for n_AC in [0, 100]:
                            for n_c2 in [0, 25, 50]:  # extra C_2 long
                                pf = Portfolio()
                                pf.sell(products['AC_45_KO'], 500)
                                pf.sell(products['AC_50_CO'], n_co)
                                pf.buy(products['AC_50_C'], n_co)
                                pf.buy(products['AC_50_P_2'], n_co)
                                pf.sell(products['AC_60_C'], n_60)
                                pf.sell(products['AC_40_BP'], n_bp)
                                pf.buy(products['AC_45_P'], n_sp1)
                                pf.sell(products['AC_35_P'], n_sp1)
                                if n_sp2:
                                    pf.buy(products['AC_50_P'], n_sp2)
                                    pf.sell(products['AC_40_P'], n_sp2)
                                if n_AC:
                                    pf.buy(products['AC'], n_AC)
                                if n_c2:
                                    pf.buy(products['AC_50_C_2'], n_c2)
                                if pf.n_assets_used >= 8:
                                    tag = (f"S3: CO{n_co}+C60s{n_60}+BPs{n_bp}+"
                                           f"45/35={n_sp1}+50/40={n_sp2}+"
                                           f"AC={n_AC}+C2={n_c2}")
                                    rows3.append(stats_row(tag, pf, paths))

    rows3.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(rows3)}:")
    for r in rows3[:10]:
        print(fmt(r))

    # ============================================================
    # Stage 4: Minimal — KO + tiny singles for n=6
    # ============================================================
    print("\n=== Stage 4: KO500 + 5 minimal singles ===", flush=True)
    rows4 = []
    edge_dirs = {
        'AC_50_P_2':  +1, 'AC_50_C_2': +1, 'AC_50_C': +1,
        'AC_60_C':    -1, 'AC_50_CO':  -1, 'AC_40_BP': -1,
        'AC_35_P':    -1, 'AC_40_P':   -1,
    }
    keys = list(edge_dirs.keys())
    for combo in itertools.combinations(keys, 5):
        for size in [1, 2, 5]:
            pf = Portfolio()
            pf.sell(products['AC_45_KO'], 500)
            for k in combo:
                pf.add(products[k], edge_dirs[k] * size)
            if pf.n_assets_used >= 6:
                tag = f"S4: KO500+x{size} on " + ",".join(combo)
                rows4.append(stats_row(tag, pf, paths))

    rows4.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(rows4)}:")
    for r in rows4[:10]:
        print(fmt(r))

    # ============================================================
    # FINAL ranking — all together
    # ============================================================
    all_rows = rows + rows2 + rows3 + rows4
    seen = set()
    uniq = []
    for r in all_rows:
        if r['name'] not in seen:
            seen.add(r['name'])
            uniq.append(r)

    print("\n\n========== FINAL TOP 25 BY SCORE (mean - 2*std), n>=6 ==========")
    uniq.sort(key=lambda r: -r['score'])
    for r in uniq[:25]:
        print(fmt(r))

    print("\n========== TOP 10 BY p5 ==========")
    uniq.sort(key=lambda r: -r['p5'])
    for r in uniq[:10]:
        print(fmt(r))

    print("\n========== TOP 10 BY p25 ==========")
    uniq.sort(key=lambda r: -r['p25'])
    for r in uniq[:10]:
        print(fmt(r))

    print("\n========== TOP 10 BY SHARPE (mean>=200k) ==========")
    high = [r for r in uniq if r['mean'] >= 200_000]
    high.sort(key=lambda r: -r['sharpe'])
    for r in high[:10]:
        print(fmt(r))

    # Detail final 3
    uniq.sort(key=lambda r: -r['score'])
    print("\n\n========== DETAIL: TOP 3 BY SCORE ==========")
    for i, r in enumerate(uniq[:3]):
        print(f"\n*** #{i+1}: {r['name']} ***")
        print(r['pf'].describe())
        print(fmt(r))

    # Validate top-3 with FRESH 100k paths and DIFFERENT seed
    print("\n\n========== VALIDATION (fresh 100k paths, seed 7) ==========")
    paths_v = sim.simulate(100_000, n_steps=WEEKS_3_STEPS, seed=7)
    for i, r in enumerate(uniq[:5]):
        rv = stats_row(r['name'], r['pf'], paths_v)
        print(fmt(rv))


if __name__ == '__main__':
    main()
