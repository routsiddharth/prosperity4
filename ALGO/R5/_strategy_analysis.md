# Drinks (Oxygen Shakes) — Findings & Draft Strategy

## What the notebook actually shows

**Returns-level signals: essentially zero.**
- All pairwise Pearson correlations on returns ≤ 0.013
- Rolling correlations: `frac_above_0.3 = 0.0` for every pair, every window
- Lead-lag peaks ≤ 0.02 (noise)
- DY total spillover index = 0.07% (group is dis-integrated on returns)
- All Granger pseudo-significance lives at lag 5–50 with tiny coefficients

**Conclusion:** there is no usable directional or lead-lag alpha on returns.

**Levels-level signals: a real, durable cointegration edge exists.**

| Spread | ADF p | Half-life (ticks) | Daily std |
|---|---|---|---|
| **K3 = GARLIC + MORNING_BREATH + EVENING_BREATH − CHOCOLATE** | **0.0075** | **867** | 537 / 664 / 540 |
| K2 = GARLIC + MORNING_BREATH − CHOCOLATE | 0.010 | 1,310 | 907 / 728 / 428 |
| Pure −4·CHOCOLATE + 2·GARLIC | 0.014 | 1,245 | bigger gross |
| OLS pair CHOCOLATE − 0.38·GARLIC | 0.13 | 1,418 | weak |
| Johansen v1 (real-weight) | 0.004 | 946 | needs continuous coefs |

The cleanest *integer* basket — easiest to actually trade — is **K3**.

**Daily K3 spread stats (raw mid prices):**
- Day 2: mean 21,471, std 537
- Day 3: mean 21,679, std 664
- Day 4: mean 21,772, std 540
- Mean drifts +300 over 3 days → must use a rolling mean, not a static one.

**Rolling-z behavior (K3, after subtracting rolling mean & dividing by rolling std):**
- Window 200: z-std=1.37, q01=-2.74, q99=+2.87 — cleanest, mean closest to 0
- Window 500: z-std=1.40, q01=-2.83, q99=+2.97
- Longer windows pick up day-level drift; shorter is healthier
- Tails are slightly fat (Gaussian-corrected, expect z~3 not 2.9). Acceptable.

**Liquidity:**
- All five shakes show median top-of-book size 18 / 18 (bid / ask)
- Half-spread is 6.0–7.5 ticks per shake → round-trip cost ≈ 12–15 per leg
- 4-leg basket round-trip cost ≈ 50 ticks when paying full spread
- Spread move per 1σ ≈ 540 ticks → 1σ-z trade has ~10× edge over crossing the spread

**MINT:** carries no significant exposure in any cointegrating vector. Treat as out of scope for the basket trade — at most pure market-making on its own quote.

## Draft Strategy v0

### Core trade
**Basket spread S = mid(GARLIC) + mid(MORNING_BREATH) + mid(EVENING_BREATH) − mid(CHOCOLATE)**

Maintain a rolling mean μ and std σ of S using window W = 200 ticks. (Bootstrap from a hard-coded prior of μ₀ ≈ 21,640, σ₀ ≈ 580 until W samples are buffered.)

z = (S − μ) / σ

### Entry / exit ladder
- |z| < 1.0 → flat the basket (close any open position)
- |z| ≥ 1.5 → enter 1 basket unit *against* the move
  - z > +1.5 → sell basket (sell GARLIC, sell MORN, sell EVEN, buy CHOC)
  - z < −1.5 → buy basket (buy GARLIC, buy MORN, buy EVEN, sell CHOC)
- |z| ≥ 2.5 → scale to max basket units
- |z| ≥ 4.0 → **regime break: flatten and pause for W ticks.** The spread may be re-pricing (legal new equilibrium) — re-anchor the mean, do not double-down.

### Sizing
Assume position limit per shake = L (typically 60–80 in this comp). 1 basket unit = 1 of each of 4 shakes. Max basket units B_max = L. Use:
- B(z) = clip(round((|z| − 1.5) × 0.5 × L), 0, L), capped at L/2 to leave room for a second waved entry
- Target net basket position from z; trade incrementally toward target each tick

### Execution
- Always cross the spread on each leg (do not market-make the basket; legs decorrelate too quickly)
- Size each leg so that when one leg can't fill, **don't enter the other three** (atomic-ish sizing)
- Never carry an unhedged single-leg residual > 5 units across ticks; flatten first

### Fail-safes
- If μ deviates > 3·σ over a 1,000-tick window from the long-run mean, **suspect regime change**: cap size to ≤ 25% normal.
- If we have been in the same direction for > 2,500 ticks (≈ 3× half-life) without z crossing 0.5: stop adding, scale out at any cross of 1.0.
- Hard daily loss circuit-breaker: if cumulative drinks PnL < −3,000, flatten and stop trading shakes for the rest of the day.

## Open uncertainties
- Position limit per shake (likely 60 or 80, need to confirm)
- Whether OBI / micro-price gives an intra-tick edge on each leg (not analyzed for the basket execution layer)
- Whether MINT can be added at low weight to soak more variance — current data says no
