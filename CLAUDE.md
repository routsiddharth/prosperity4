# Prosperity 4 — Project Instructions

## Always-read references

Before working on ANY algorithmic trading round task, read these first:

- `ALGO/algo_trading_reference.md` — full algo writing guide: `Trader` class, `TradingState`/`OrderDepth`/`Order`/`Trade`, position limits, order matching mechanics, conversions, supported libraries, `datamodel.py`, common patterns.
- `backtester_reference.md` — local backtester CLI: flags, data format, order matching, position limit enforcement, output log format, visualizer.

These docs are the source of truth for exchange rules, the data model, and the testing tools.

## Hard rules from the exchange

- `buy_orders` quantities are **positive**; `sell_orders` quantities are **negative**.
- Orders: positive quantity = buy, negative quantity = sell.
- `Trader.run` must return the 3-tuple `(result, conversions, traderData)`.
- `Trader.bid()` is only used in Round 2 — it is safe to leave a `bid()` method in any submission; it is ignored elsewhere.
- AWS Lambda is stateless across calls — persist state via the `traderData` string (≤ 50,000 chars). Never rely on class/global variables persisting.
- Per-call budget: 900 ms hard, ~100 ms target average.
- Position limits are per-product; check the round-specific info doc before sizing.

## Repo layout

```
prosperity/
├── CLAUDE.md                       this file
├── README.md                       public-facing repo overview
├── backtester_reference.md         local backtester CLI reference
├── ALGO/
│   ├── algo_trading_reference.md   exchange API, datamodel, patterns
│   ├── R1/  …  R5/                 one folder per algo round
│   └── R{N}/ROUND_{N}/             official price/trade CSVs
├── MANUAL/
│   ├── R1/                         (empty placeholder)
│   └── R4/                         Aether Crystal options portfolio search
├── TUTORIAL_ROUND_1/               tutorial round artifacts
├── backtests/                      generated backtest logs (gitignored if large)
└── screenshots/                    UI screenshots
```

Each algo round folder typically contains:
- `trader.py` — current submission for the round.
- `ROUND_{N}/` — official `prices_round_{N}_day_*.csv` and `trades_round_{N}_day_*.csv`.
- A handful of numbered subfolders (e.g. `496712/`, `523446/`) — past submissions, each with the algo file, log, and visualizer JSON.
- `round{N}_info.md` or similar — copy of the round brief.

## Round-by-round summary

| Round | Theme | Products | Position limits |
|---|---|---|---|
| Tutorial | Warmup | `EMERALDS` | — |
| **R1** | "First Intarian Goods" | `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT` | 80 each |
| **R2** | "Limited Market Access" | Same as R1 + a `bid()` for extra book flow | 80 each |
| **R3** | Vouchers introduced | `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT` (VEV), 10× `VEV_*` call vouchers | 200 / 200 / 300 each voucher |
| **R4** | "Hello, I'm Mark" — counterparty IDs | Same as R3, but `Trade.buyer`/`seller` populated; manual-trading side game on Aether Crystal options | 200 / 200 / 300 |
| **R5** | Final round | All previous + drinks basket (`GARLIC`, `MORNING_BREATH`, `EVENING_BREATH`, `CHOCOLATE`, `MINT`) and snackpacks combinations | see round info |

Per-round briefs:
- R1 — `ALGO/R1/round1_info.md`
- R2 — `ALGO/R2/round2_info.md`
- R4 — `ALGO/R4/README.md`
- R5 drinks analysis — `ALGO/R5/_strategy_analysis.md`
- R4 manual recs — `MANUAL/R4/RECOMMENDATIONS.md`

R3 vouchers expire 7 days from R1 start; TTE is 5d at R3 start, 4d at R4 start.

## Working conventions

- **Don't overfit to training days.** Use online/rolling stats and canonical thresholds; don't hardcode constants from training-day sweeps. (Saved in user feedback.)
- **Prefer backtester runs over hypothetical critique.** When evaluating a strategy change, run the backtester rather than reasoning by analogy. (Saved in user feedback.)
- **Never carry an unhedged residual** across ticks for basket strategies — flatten the residual leg first.
- **Fail-safes belong in the trader**: hard daily-loss circuit-breakers, regime-break z thresholds (`|z| ≥ 4` → flatten + pause + re-anchor mean), and size caps under suspected regime change.
- **Atomic-ish multi-leg sizing**: if one leg can't fill, don't enter the others.
- **Match position limits before sizing.** Check the round info file; the limits are not always the same across rounds.

## Backtester quickstart

See `backtester_reference.md` for full flags. Typical run:

```
python -m prosperity4bt path/to/trader.py --data ALGO/R{N}/ROUND_{N}
```

Logs land in `backtests/` and are visualizer-compatible. Logs over ~95MB are excluded from git via `.gitignore`.

## What's gitignored

`venv/`, `__pycache__/`, `*.log`, `.DS_Store`, `*.ipynb.bak*`, editor folders. Backtest CSVs and notebooks are tracked.
