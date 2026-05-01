# Prosperity 4

My code, data, and analysis for IMC's **Prosperity 4** algorithmic + manual trading competition.

Five algo rounds plus per-round manual challenges. Each round introduces new products on a fictional planet ("Intara") that trade against bots on a simulated exchange. Algos are written as a Python `Trader` class running on AWS Lambda; manual rounds are one-shot decision problems.

## Layout

```
prosperity/
├── ALGO/
│   ├── algo_trading_reference.md   exchange API + datamodel reference
│   ├── R1/                         "First Intarian Goods" — ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT
│   ├── R2/                         "Limited Market Access" — adds bid() for extra book flow
│   ├── R3/                         Vouchers — HYDROGEL_PACK, VELVETFRUIT_EXTRACT, 10× VEV_* call options
│   ├── R4/                         "Hello, I'm Mark" — counterparty IDs disclosed; same instruments as R3
│   └── R5/                         Final round — drinks basket, snackpacks, full-product algo
├── MANUAL/
│   ├── R1/                         placeholder
│   └── R4/                         Aether Crystal options portfolio optimizer
├── TUTORIAL_ROUND_1/               tutorial round
├── backtester_reference.md         local backtester CLI reference
├── CLAUDE.md                       working notes / conventions
└── backtests/                      generated backtest logs
```

Each `ALGO/R{N}/` folder typically holds:
- `trader.py` — submission code
- `ROUND_{N}/prices_round_{N}_day_*.csv` + `trades_round_{N}_day_*.csv` — official market data
- numbered subfolders (e.g. `496712/`, `523446/`) — historical submissions with their logs and visualizer JSON

## Round summary

| Round | Products | Position limits | Notes |
|---|---|---|---|
| Tutorial | `EMERALDS` | — | warmup |
| R1 | `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT` | 80 / 80 | first algo |
| R2 | same as R1 | 80 / 80 | adds `bid()` blind-auction for extra flow |
| R3 | `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, 10× `VEV_*` vouchers | 200 / 200 / 300 ea | options introduced; TTE = 5d at start |
| R4 | same as R3 | same | counterparty names populated (`Mark 01`, `Mark 14`, …); TTE = 4d; manual side-game on Aether Crystal options |
| R5 | all of the above + drinks basket (`GARLIC` / `MORNING_BREATH` / `EVENING_BREATH` / `CHOCOLATE` / `MINT`) + snackpacks | see round info | final round |

## Highlights

- **R5 drinks basket** — found a real cointegration edge on `K3 = GARLIC + MORNING_BREATH + EVENING_BREATH − CHOCOLATE` (ADF p ≈ 0.0075, half-life ~867 ticks). Returns-level signals were essentially zero; levels-level edge is the play. Full writeup in `ALGO/R5/_strategy_analysis.md`.
- **R5 combination search** — notebooks (`combination_search*.ipynb`) brute-force evaluate basket combinations of drinks and snackpacks.
- **R4 manual** — `MANUAL/R4/` is a small mean-variance optimizer over an Aether Crystal options menu (puts, calls, KO, chooser). The KO barrier is unspecified by the challenge and swings expected PnL by ±$220k — see `MANUAL/R4/RECOMMENDATIONS.md` for the three portfolios I considered.

## Local backtester

Backtester usage is documented in `backtester_reference.md`. Typical:

```bash
python -m prosperity4bt path/to/ALGO/R{N}/trader.py --data ALGO/R{N}/ROUND_{N}
```

The logs are compatible with the official Prosperity visualizer.

## Conventions

- `buy_orders` quantities are positive; `sell_orders` quantities are negative.
- `Order` quantity sign: positive = buy, negative = sell.
- `Trader.run` returns `(result, conversions, traderData)`.
- `traderData` string capped at 50,000 chars; AWS Lambda is stateless, so all per-iteration state must round-trip through it.
- Per-call budget: 900 ms hard, ~100 ms target avg.

## Disclaimer

This is a personal repo of competition work. Strategies are tuned to the Prosperity simulator's bots and rules, not to real markets.
