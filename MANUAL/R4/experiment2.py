"""Tighter exploration around the leading C-family + investigate variance source."""

from __future__ import annotations

import numpy as np
from simulator import Simulator, WEEKS_3_STEPS
from products import build_universe
from portfolio import Portfolio


def stats_row(name, pf, paths):
    s = pf.stats(paths)
    score = s['mean'] - 2 * s['std']
    return {
        'name': name,
        'mean': s['mean'],
        'std': s['std'],
        'p5': s['p5'],
        'p25': s['p25'],
        'median': s['median'],
        'sharpe': s['sharpe'],
        'win': s['win_rate'],
        'n': s['n_assets_used'],
        'score': score,
        'pf': pf,
    }


def fmt(r):
    return (f"{r['name']:<60} mean={r['mean']:>9,.0f} std={r['std']:>9,.0f} "
            f"p5={r['p5']:>9,.0f} p25={r['p25']:>8,.0f} med={r['median']:>8,.0f} "
            f"sh={r['sharpe']:>5.2f} w={r['win']:>5.1%} n={r['n']:>2} "
            f"score={r['score']:>10,.0f}")


def main():
    sim = Simulator()
    products = build_universe()
    print("Simulating 500,000 paths…")
    paths = sim.simulate(500_000, n_steps=WEEKS_3_STEPS, seed=42)

    print("\n=== Variance contribution per single-product position (50 vol) ===")
    for name, prod in products.items():
        max_v = prod.max_volume
        # Test buy and sell at max vol
        for sign, side in [(+1, 'BUY'), (-1, 'SELL')]:
            pf = Portfolio()
            pf.add(prod, sign * max_v)
            s = pf.stats(paths)
            tag = f"{name} {side} x{max_v}"
            print(f"  {tag:<25} mean={s['mean']:>9,.0f} std={s['std']:>10,.0f} "
                  f"p5={s['p5']:>10,.0f} score={s['mean']-2*s['std']:>10,.0f}")

    # ----------------------------------------
    # Test: pure chooser arb alone — should be near deterministic
    # ----------------------------------------
    print("\n=== Standalone strategies ===")

    pf = Portfolio()
    pf.sell(products['AC_50_CO'], 50)
    pf.buy(products['AC_50_C'], 50)
    pf.buy(products['AC_50_P_2'], 50)
    print(fmt(stats_row("Pure ChArb x50", pf, paths)))

    pf = Portfolio()
    pf.sell(products['AC_45_KO'], 500)
    print(fmt(stats_row("Pure KO short x500", pf, paths)))

    pf = Portfolio()
    pf.sell(products['AC_40_BP'], 50)
    print(fmt(stats_row("Pure BP short x50", pf, paths)))

    pf = Portfolio()
    pf.buy(products['AC_45_P'], 50)
    pf.sell(products['AC_35_P'], 50)
    print(fmt(stats_row("BPS 45/35 x50", pf, paths)))

    pf = Portfolio()
    pf.buy(products['AC_45_P'], 50)
    pf.sell(products['AC_40_P'], 50)
    print(fmt(stats_row("BPS 45/40 x50", pf, paths)))

    # ----------------------------------------
    # Combine pieces incrementally
    # ----------------------------------------
    print("\n=== Incremental builds ===")
    base = Portfolio()
    base.sell(products['AC_45_KO'], 500)
    print(fmt(stats_row("KO x500", base, paths)))

    pf = Portfolio()
    pf.sell(products['AC_45_KO'], 500)
    pf.sell(products['AC_40_BP'], 50)
    print(fmt(stats_row("KO x500 + BP x50", pf, paths)))

    pf = Portfolio()
    pf.sell(products['AC_45_KO'], 500)
    pf.sell(products['AC_40_BP'], 50)
    pf.sell(products['AC_50_CO'], 50)
    pf.buy(products['AC_50_C'], 50)
    pf.buy(products['AC_50_P_2'], 50)
    print(fmt(stats_row("KO+BP+ChArb50", pf, paths)))

    # Now expand: try varying ChArb size
    for n_co in [10, 20, 30, 40, 50]:
        pf = Portfolio()
        pf.sell(products['AC_45_KO'], 500)
        pf.sell(products['AC_40_BP'], 50)
        pf.sell(products['AC_50_CO'], n_co)
        pf.buy(products['AC_50_C'], n_co)
        pf.buy(products['AC_50_P_2'], n_co)
        print(fmt(stats_row(f"KO+BP+ChArb{n_co}", pf, paths)))

    # Add bear put spread on top
    print("\n--- + Bear put spread 45/35 ---")
    for n_co in [0, 10, 20, 30, 50]:
        for n_sp in [10, 25, 50]:
            pf = Portfolio()
            pf.sell(products['AC_45_KO'], 500)
            pf.sell(products['AC_40_BP'], 50)
            if n_co:
                pf.sell(products['AC_50_CO'], n_co)
                pf.buy(products['AC_50_C'], n_co)
                pf.buy(products['AC_50_P_2'], n_co)
            pf.buy(products['AC_45_P'], n_sp)
            pf.sell(products['AC_35_P'], n_sp)
            tag = f"KO+BP+ChArb{n_co}+BPS{n_sp}"
            r = stats_row(tag, pf, paths)
            if r['n'] >= 6:
                print(fmt(r))

    print("\n--- Add long-2wk-straddle sweetener ---")
    # AC_50_P_2 and AC_50_C_2 each have +0.115 edge
    for n_co in [0, 10, 25]:
        for n_str in [0, 25, 50]:
            for n_sp in [0, 25, 50]:
                pf = Portfolio()
                pf.sell(products['AC_45_KO'], 500)
                pf.sell(products['AC_40_BP'], 50)
                if n_co:
                    pf.sell(products['AC_50_CO'], n_co)
                    pf.buy(products['AC_50_C'], n_co)
                    pf.buy(products['AC_50_P_2'], n_co)  # base
                if n_str:
                    pf.buy(products['AC_50_C_2'], n_str)
                    # add to existing P_2 if no chooser, else fold in
                    cur = pf.positions.get('AC_50_P_2', (None, 0))[1]
                    addv = min(n_str, 50 - cur)
                    if addv > 0:
                        pf.add(products['AC_50_P_2'], addv)
                if n_sp:
                    pf.buy(products['AC_45_P'], n_sp)
                    pf.sell(products['AC_35_P'], n_sp)
                tag = f"KO+BP+ChArb{n_co}+Str{n_str}+BPS{n_sp}"
                r = stats_row(tag, pf, paths)
                if r['n'] >= 6:
                    print(fmt(r))

    print("\n--- Refine top: small ChArb size + small KO + put spread ---")
    rows = []
    for n_co in [10, 15, 20, 25, 30]:
        for n_ko in [250, 350, 500]:
            for n_bp in [0, 10, 25, 50]:
                for n_sp in [10, 25, 50]:
                    for spread in [('AC_45_P','AC_35_P'),
                                   ('AC_45_P','AC_40_P'),
                                   ('AC_50_P','AC_45_P'),
                                   ('AC_50_P','AC_40_P'),
                                   ('AC_50_P','AC_35_P')]:
                        pf = Portfolio()
                        pf.sell(products['AC_45_KO'], n_ko)
                        if n_bp:
                            pf.sell(products['AC_40_BP'], n_bp)
                        pf.sell(products['AC_50_CO'], n_co)
                        pf.buy(products['AC_50_C'], n_co)
                        pf.buy(products['AC_50_P_2'], n_co)
                        pf.buy(products[spread[0]], n_sp)
                        pf.sell(products[spread[1]], n_sp)
                        tag = f"CO={n_co} KO={n_ko} BP={n_bp} {spread[0]}/{spread[1]}x{n_sp}"
                        r = stats_row(tag, pf, paths)
                        if r['n'] >= 6:
                            rows.append(r)

    rows.sort(key=lambda r: -r['score'])
    print(f"\nTop 15 of {len(rows)} refined configs (score = mean - 2*std):")
    for r in rows[:15]:
        print(fmt(r))

    print("\n\nTop 10 by p5 (worst-case 5%):")
    rows.sort(key=lambda r: -r['p5'])
    for r in rows[:10]:
        print(fmt(r))

    print("\n\nTop 10 by p25:")
    rows.sort(key=lambda r: -r['p25'])
    for r in rows[:10]:
        print(fmt(r))

    print("\n\nTop 10 by sharpe (mean>=200k):")
    high = [r for r in rows if r['mean'] >= 200_000]
    high.sort(key=lambda r: -r['sharpe'])
    for r in high[:10]:
        print(fmt(r))

    # ----------------------------------------------------------------
    # Final detail: Top 3 by score
    # ----------------------------------------------------------------
    rows.sort(key=lambda r: -r['score'])
    print("\n\n========== DETAIL: TOP 3 BY SCORE ==========")
    for i, r in enumerate(rows[:3]):
        print(f"\n*** #{i+1}: {r['name']} ***")
        print(r['pf'].describe())
        print(fmt(r))


if __name__ == '__main__':
    main()
