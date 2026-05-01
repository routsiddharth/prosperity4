"""Hand-crafted strategy search for R4 manual.

Goal: find low-variance, high-mean portfolios that beat the mean-variance
optimizer's lambda=0.003 result (mean ~$241k, std ~$181k, p5 ~$89k, sharpe 1.33).

Constraint: at least 6 of 12 products active.

Score: mean - 2*std (conservative profit lower bound).
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
    return (f"{r['name']:<55} mean={r['mean']:>9,.0f} std={r['std']:>9,.0f} "
            f"p5={r['p5']:>9,.0f} p25={r['p25']:>8,.0f} med={r['median']:>8,.0f} "
            f"sh={r['sharpe']:>5.2f} w={r['win']:>5.1%} n={r['n']:>2} "
            f"score={r['score']:>10,.0f}")


def edges(products, paths):
    out = {}
    for name, prod in products.items():
        fv = prod.fair_value(paths)
        eb = fv - prod.ask
        es = prod.bid - fv
        out[name] = dict(fv=fv, edge_buy=eb, edge_sell=es)
    return out


# ----------------------------------------------------------------------
# Build "tame" extras — only include positive-edge products at MODERATE
# size, NOT max. Skip ones with huge tails.
# ----------------------------------------------------------------------

def safe_edge_extras(products, paths, exclude=(), shrink=None):
    """Return moderate-size positions on edge-positive products outside `exclude`.
    `shrink`: dict {name: fraction (0..1)} to scale down each product's volume.
    Default shrinkage strategy: shrink high-tail products.
    """
    if shrink is None:
        # naked-shorts on big-tail products limited
        shrink = {
            'AC_60_C': 1.0,    # short C unbounded upside risk -> trim hard
            'AC_40_BP': 1.0,   # binary capped, ok
            'AC_45_KO': 1.0,   # naked short cap = 50 * payoff_max ~= $30 -> bounded to ~50*0.15*500=37k
            'AC_50_P_2': 1.0,
            'AC_50_C_2': 1.0,
            'AC_50_C': 1.0,
        }
    es = edges(products, paths)
    out = {}
    for name, prod in products.items():
        if name in exclude:
            continue
        info = es[name]
        if info['edge_buy'] > 0 and info['edge_buy'] >= info['edge_sell']:
            sign = +1
        elif info['edge_sell'] > 0:
            sign = -1
        else:
            continue
        frac = shrink.get(name, 1.0)
        vol = int(round(prod.max_volume * frac))
        if vol > 0:
            out[name] = sign * vol
    return out


def evaluate_portfolio(name, builder, paths, products):
    pf = builder(products)
    return stats_row(name, pf, paths)


# ----------------------------------------------------------------------
# Hand-tuned strategies
# ----------------------------------------------------------------------

def main():
    sim = Simulator()
    products = build_universe()
    print("Simulating 500,000 paths…")
    paths = sim.simulate(500_000, n_steps=WEEKS_3_STEPS, seed=42)
    es = edges(products, paths)

    print("\n--- Per-product edges & variance contributions ---")
    print(f"{'Product':<12} {'fv':>9} {'edge_max':>10} {'side':>5} {'std(payoff)':>12}")
    for name, prod in products.items():
        info = es[name]
        if info['edge_buy'] > info['edge_sell']:
            side = 'B' if info['edge_buy'] > 0 else '-'
            edge = info['edge_buy']
        else:
            side = 'S' if info['edge_sell'] > 0 else '-'
            edge = info['edge_sell']
        std_p = float(np.std(prod.payoff(paths)))
        print(f"{name:<12} {info['fv']:>9.4f} {edge:>+10.4f} {side:>5} {std_p:>12.4f}")

    results = []

    # ====================================================================
    # Family A: pure shrink-greedy. Take all edge directions but shrink
    # the high-variance contracts.  Goal: find best mean-vol point.
    # ====================================================================
    print("\n\n=== Family A: shrink-greedy (all edges, scale per-product) ===")
    grid_A = []
    # frac configurations: (label, shrink dict). Edges-positive products are:
    # buy: AC_50_P_2, AC_50_C_2 (small edge each)
    # sell: AC_50_C (tiny edge), AC_60_C, AC_50_CO (big), AC_40_BP, AC_45_KO
    # The chooser arb (short CO, long C+P_2) drives high-mean-low-vol.
    for ko_frac in [0.4, 0.6, 0.8, 1.0]:
        for co_frac in [0.2, 0.4, 0.6, 0.8, 1.0]:
            for c2_frac in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
                for bp_frac in [0.0, 0.4, 0.8, 1.0]:
                    for c60_frac in [0.0, 0.4, 0.8]:
                        shrink = {
                            'AC_45_KO': ko_frac,
                            'AC_50_CO': co_frac,
                            'AC_50_C_2': c2_frac,
                            'AC_50_P_2': c2_frac,
                            'AC_50_C': 0.0,  # edge tiny, drop
                            'AC_40_BP': bp_frac,
                            'AC_60_C': c60_frac,
                        }
                        pf = Portfolio()
                        for name, prod in products.items():
                            info = es[name]
                            if info['edge_buy'] > 0 and info['edge_buy'] >= info['edge_sell']:
                                sign = +1
                            elif info['edge_sell'] > 0:
                                sign = -1
                            else:
                                continue
                            frac = shrink.get(name, 1.0)
                            vol = int(round(prod.max_volume * frac))
                            if vol > 0:
                                pf.add(prod, sign * vol)
                        if pf.n_assets_used >= 6:
                            tag = (f"A:KO={ko_frac} CO={co_frac} C2/P2={c2_frac} "
                                   f"BP={bp_frac} C60={c60_frac}")
                            grid_A.append(stats_row(tag, pf, paths))

    grid_A.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(grid_A)} A-family configs:")
    for r in grid_A[:10]:
        print(' ', fmt(r))
    results.extend(grid_A[:5])

    # ====================================================================
    # Family B: chooser-arb-centered, with hand-tuned add-ons
    # ====================================================================
    print("\n\n=== Family B: chooser-arb + hand-tuned add-ons ===")
    grid_B = []
    for n_co in [30, 40, 50]:
        # core arb: short n_co CO, long n_co AC_50_C, long n_co AC_50_P_2
        for n_ko in [0, 100, 250, 500]:  # KO short — capped tail since putoff bounded
            for n_bp in [0, 25, 50]:     # binary put short
                for n_c60 in [0, 10, 25, 50]:  # short 60C — naked-short-call risk
                    for n_c2 in [0, 25, 50]:   # extra long C2
                        for n_p2 in [0, 25, 50]: # extra long P2 (creates straddle if matched with C2)
                            pf = Portfolio()
                            pf.sell(products['AC_50_CO'], n_co)
                            pf.buy(products['AC_50_C'], n_co)
                            pf.buy(products['AC_50_P_2'], n_co)
                            if n_ko: pf.sell(products['AC_45_KO'], n_ko)
                            if n_bp: pf.sell(products['AC_40_BP'], n_bp)
                            if n_c60: pf.sell(products['AC_60_C'], n_c60)
                            # Note AC_50_P_2 already used; .add will accumulate
                            if n_c2:
                                cur_vol = pf.positions.get('AC_50_C_2', (None, 0))[1]
                                if abs(cur_vol + n_c2) <= 50:
                                    pf.add(products['AC_50_C_2'], n_c2)
                            if n_p2:
                                cur = pf.positions.get('AC_50_P_2', (None, 0))[1]
                                addv = n_p2
                                if abs(cur + addv) > 50:
                                    addv = 50 - cur
                                if addv > 0:
                                    pf.add(products['AC_50_P_2'], addv)
                            if pf.n_assets_used >= 6:
                                tag = (f"B:CO={n_co} KO={n_ko} BP={n_bp} "
                                       f"C60={n_c60} C2={n_c2} P2+={n_p2}")
                                grid_B.append(stats_row(tag, pf, paths))

    grid_B.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(grid_B)} B-family configs:")
    for r in grid_B[:10]:
        print(' ', fmt(r))
    results.extend(grid_B[:5])

    # ====================================================================
    # Family C: Bear put spreads (low-tail, defined risk) layered
    # ====================================================================
    print("\n\n=== Family C: bear put spreads + small KO + small chooser ===")
    grid_C = []
    # Build vertical spreads with defined risk
    spread_combos = [
        ('AC_45_P', 'AC_35_P'),  # long 45P short 35P — 10-wide
        ('AC_45_P', 'AC_40_P'),  # 5-wide
        ('AC_50_P', 'AC_40_P'),
        ('AC_50_P', 'AC_45_P'),
        ('AC_50_P', 'AC_35_P'),  # 15-wide
    ]
    for (long_p, short_p) in spread_combos:
        for n_sp in [10, 25, 50]:
            for n_co in [0, 25, 50]:
                for n_ko in [0, 250, 500]:
                    for n_bp in [0, 25, 50]:
                        pf = Portfolio()
                        pf.buy(products[long_p], n_sp)
                        pf.sell(products[short_p], n_sp)
                        if n_co:
                            pf.sell(products['AC_50_CO'], n_co)
                            pf.buy(products['AC_50_C'], n_co)
                            pf.buy(products['AC_50_P_2'], n_co)
                        if n_ko: pf.sell(products['AC_45_KO'], n_ko)
                        if n_bp: pf.sell(products['AC_40_BP'], n_bp)
                        if pf.n_assets_used >= 6:
                            tag = (f"C:{long_p}/{short_p}x{n_sp} "
                                   f"CO={n_co} KO={n_ko} BP={n_bp}")
                            grid_C.append(stats_row(tag, pf, paths))

    grid_C.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(grid_C)} C-family configs:")
    for r in grid_C[:10]:
        print(' ', fmt(r))
    results.extend(grid_C[:5])

    # ====================================================================
    # Family D: KO short + 45P long PAIR (correlation hedge)
    # ====================================================================
    print("\n\n=== Family D: KO short + long puts (correlation hedge) ===")
    grid_D = []
    for n_ko in [200, 300, 400, 500]:
        for n_45p in [0, 10, 25, 50]:
            for n_40p in [0, 10, 25, 50]:
                for n_co in [0, 25, 50]:
                    pf = Portfolio()
                    pf.sell(products['AC_45_KO'], n_ko)
                    if n_45p: pf.buy(products['AC_45_P'], n_45p)
                    if n_40p: pf.buy(products['AC_40_P'], n_40p)
                    if n_co:
                        pf.sell(products['AC_50_CO'], n_co)
                        pf.buy(products['AC_50_C'], n_co)
                        pf.buy(products['AC_50_P_2'], n_co)
                    if pf.n_assets_used >= 4:
                        tag = (f"D:KO={n_ko} 45P+={n_45p} 40P+={n_40p} CO={n_co}")
                        grid_D.append(stats_row(tag, pf, paths))

    grid_D.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(grid_D)} D-family configs (note: n>=4 here, may have <6):")
    for r in grid_D[:10]:
        print(' ', fmt(r))
    # Take only those with n>=6
    results.extend([r for r in grid_D if r['n'] >= 6][:5])

    # ====================================================================
    # Family E: Combined "pillars" — chooser arb + KO + spread + binary +
    # tiny short-60C — tuned for low variance
    # ====================================================================
    print("\n\n=== Family E: pillar combos ===")
    grid_E = []
    for n_co in [30, 40, 50]:
        for n_ko in [250, 400, 500]:
            for n_bp in [25, 50]:
                for n_c60 in [0, 10, 25]:
                    for n_sp in [0, 10, 25]:  # 45P/35P spread
                        pf = Portfolio()
                        pf.sell(products['AC_50_CO'], n_co)
                        pf.buy(products['AC_50_C'], n_co)
                        pf.buy(products['AC_50_P_2'], n_co)
                        pf.sell(products['AC_45_KO'], n_ko)
                        pf.sell(products['AC_40_BP'], n_bp)
                        if n_c60: pf.sell(products['AC_60_C'], n_c60)
                        if n_sp:
                            pf.buy(products['AC_45_P'], n_sp)
                            pf.sell(products['AC_35_P'], n_sp)
                        if pf.n_assets_used >= 6:
                            tag = (f"E:CO={n_co} KO={n_ko} BP={n_bp} "
                                   f"C60={n_c60} 45P/35P={n_sp}")
                            grid_E.append(stats_row(tag, pf, paths))

    grid_E.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(grid_E)} E-family configs:")
    for r in grid_E[:10]:
        print(' ', fmt(r))
    results.extend(grid_E[:5])

    # ====================================================================
    # Family F: include AC underlying! Hedging short-call risk.
    # Short 60C is high-tail; long AC reduces risk.
    # ====================================================================
    print("\n\n=== Family F: with underlying AC for delta hedging ===")
    grid_F = []
    for n_co in [40, 50]:
        for n_ko in [300, 500]:
            for n_bp in [25, 50]:
                for n_c60 in [25, 50]:
                    for n_AC_long in [0, 50, 100, 150, 200]:
                        pf = Portfolio()
                        pf.sell(products['AC_50_CO'], n_co)
                        pf.buy(products['AC_50_C'], n_co)
                        pf.buy(products['AC_50_P_2'], n_co)
                        pf.sell(products['AC_45_KO'], n_ko)
                        pf.sell(products['AC_40_BP'], n_bp)
                        pf.sell(products['AC_60_C'], n_c60)
                        if n_AC_long:
                            pf.buy(products['AC'], n_AC_long)
                        if pf.n_assets_used >= 6:
                            tag = (f"F:CO={n_co} KO={n_ko} BP={n_bp} "
                                   f"C60={n_c60} AC+={n_AC_long}")
                            grid_F.append(stats_row(tag, pf, paths))

    grid_F.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(grid_F)} F-family configs:")
    for r in grid_F[:10]:
        print(' ', fmt(r))
    results.extend(grid_F[:5])

    # ====================================================================
    # Family G: max-product (all 12 used) — small sizes + chooser core
    # ====================================================================
    print("\n\n=== Family G: all-12 with mixed micro-sizes ===")
    grid_G = []
    # Use small sizes on each. Try: chooser arb 50, KO short 500, binary 50,
    # short 60C 25, long P_2/C_2 25 each, vertical spread on puts.
    for n_co in [40, 50]:
        for n_ko in [500]:
            for n_bp in [50]:
                for n_c60 in [10, 25, 50]:
                    for n_AC in [0, 50, 100, 200]:
                        for n_sp in [10, 25, 50]:  # 45P/35P spread
                            for n_40p_short in [0, 10, 25, 50]:
                                pf = Portfolio()
                                # core
                                pf.sell(products['AC_50_CO'], n_co)
                                pf.buy(products['AC_50_C'], n_co)
                                pf.buy(products['AC_50_P_2'], n_co)
                                pf.sell(products['AC_45_KO'], n_ko)
                                pf.sell(products['AC_40_BP'], n_bp)
                                pf.sell(products['AC_60_C'], n_c60)
                                if n_AC: pf.buy(products['AC'], n_AC)
                                # vertical
                                pf.buy(products['AC_45_P'], n_sp)
                                pf.sell(products['AC_35_P'], n_sp)
                                # extra short 40P (FV ~6.5, bid 6.5 => zero edge)
                                if n_40p_short:
                                    pf.sell(products['AC_40_P'], n_40p_short)
                                # 50_C_2 long if room
                                if pf.n_assets_used < 12:
                                    pf.buy(products['AC_50_C_2'], 50)
                                if pf.n_assets_used >= 8:
                                    tag = (f"G:CO={n_co} KO={n_ko} BP={n_bp} "
                                           f"C60={n_c60} AC={n_AC} "
                                           f"sp={n_sp} 40Ps={n_40p_short}")
                                    grid_G.append(stats_row(tag, pf, paths))

    grid_G.sort(key=lambda r: -r['score'])
    print(f"Top 10 of {len(grid_G)} G-family configs:")
    for r in grid_G[:10]:
        print(' ', fmt(r))
    results.extend(grid_G[:5])

    # ====================================================================
    # FINAL ranking
    # ====================================================================
    print("\n\n========== FINAL RANKING (n>=6, by mean - 2*std) ==========")
    final = [r for r in results if r['n'] >= 6]
    seen = set()
    uniq = []
    for r in final:
        if r['name'] not in seen:
            seen.add(r['name'])
            uniq.append(r)
    uniq.sort(key=lambda r: -r['score'])
    print(f"\n{'name':<55} {'mean':>9} {'std':>9} {'p5':>9} {'p25':>8} {'med':>8} {'sh':>5} "
          f"{'w':>6} {'n':>3} {'score':>10}")
    for r in uniq[:20]:
        print(fmt(r))

    print("\n\n========== DETAIL: TOP 3 ==========")
    for i, r in enumerate(uniq[:3]):
        print(f"\n*** #{i+1}: {r['name']} ***")
        print(r['pf'].describe())
        print(fmt(r))


if __name__ == '__main__':
    main()
