# Prosperity 4 Backtester Reference

## Package Info
- **PyPI name**: `prosperity4btest` (install: `pip install -U prosperity4btest`)
- **Python package dir**: `prosperity4bt` (at `/opt/miniconda3/lib/python3.13/site-packages/prosperity4bt/`)
- **Version installed**: 1.0.1
- **Based on**: jmerle's Prosperity 3 backtester, adapted by Nabayan Saha

## CLI Usage

```
prosperity4btest <algorithm.py> <days...> [options]
```

### Day specifiers
- `0` — all days in round 0
- `1-0` — round 1, day 0 only
- `1--1` — round 1, day -1
- Multiple: `1--1 1-0` or `1 2`

### Key flags
| Flag | Effect |
|---|---|
| `--merge-pnl` | Merge PnL across days |
| `--vis` | Open results in jmerle's visualizer |
| `--out FILE` | Custom output path (default: `backtests/<timestamp>.log`) |
| `--no-out` | Skip saving output log |
| `--data DIR` | Custom data directory (must mirror resources structure) |
| `--print` | Print trader stdout while running |
| `--match-trades all\|worse\|none` | Trade matching mode (default: `all`) |
| `--no-progress` | Hide progress bars |
| `--original-timestamps` | Don't renumber timestamps across days |
| `--limit PRODUCT:NUM` | Override position limit (repeatable) |

## Bundled Data (as of v1.0.1)
- **Round 0**: days -2, -1 (TOMATOES, EMERALDS)
- **Round 1**: days -2, -1, 0 (ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT)
- No observations files bundled for these rounds

Data lives under `prosperity4bt/resources/roundN/`:
- `prices_round_N_day_D.csv` (semicolon-delimited: day;timestamp;product;bid1;vol1;bid2;vol2;bid3;vol3;ask1;vol1;ask2;vol2;ask3;vol3;mid_price;pnl)
- `trades_round_N_day_D.csv` (semicolon-delimited: timestamp;buyer;seller;symbol;currency;price;quantity)
- `observations_round_N_day_D.csv` (comma-delimited, optional)

## Position Limits (hardcoded in `data.py`)
- EMERALDS: 80
- TOMATOES: 80
- ASH_COATED_OSMIUM: 80
- INTARIAN_PEPPER_ROOT: 80
- Any unlisted product: default 50
- Override via `--limit PRODUCT:NUM`

## Order Matching Logic
1. **Limits enforced first**: if total potential fills would exceed limit, ALL orders for that product are canceled
2. **Order depth matching**: buy orders matched against sell_orders at prices <= order price (best first); sell orders matched against buy_orders at prices >= order price (best first)
3. **Market trade matching** (if order depth didn't fully fill): depends on `--match-trades`:
   - `all`: match trades at prices equal to or worse than your quote
   - `worse`: match trades at prices strictly worse than your quote
   - `none`: skip market trade matching
4. Market trades match at YOUR order price (not the trade price)
5. Each fill is clamped to stay within position limits

## Algorithm Requirements
The algorithm file must expose a `Trader` class with a `run(self, state: TradingState)` method that returns:
```python
(orders: dict[Symbol, list[Order]], conversions: int, traderData: str)
```

The file can `from datamodel import ...` — the backtester aliases `prosperity4bt.datamodel` as `datamodel`.

## Key Datamodel Classes
- **TradingState**: traderData, timestamp, listings, order_depths, own_trades, market_trades, position, observations
- **Order(symbol, price, quantity)**: price must be int, quantity positive=buy / negative=sell
- **OrderDepth**: buy_orders (dict[int,int] price->volume positive), sell_orders (dict[int,int] price->volume negative)
- **Trade(symbol, price, quantity, buyer, seller, timestamp)**
- **Observation**: plainValueObservations, conversionObservations
- **ConversionObservation**: bidPrice, askPrice, transportFees, exportTariff, importTariff, sugarPrice, sunlightIndex

## Risk Metrics (printed after each run)
- final_pnl, sharpe_ratio, annualized_sharpe, sortino_ratio
- max_drawdown_abs, max_drawdown_pct, calmar_ratio
- Uses 252 trading days/year for annualization

## Output Log Format
The `.log` file has 3 sections:
1. **Sandbox logs** — JSON per timestamp with sandboxLog, lambdaLog, timestamp
2. **Activities log** — semicolon-separated CSV (same format as prices CSV)
3. **Trade History** — JSON array of trade objects

## Environment Variables (set during backtest only)
- `PROSPERITY4BT_ROUND` — round number
- `PROSPERITY4BT_DAY` — day number
- These do NOT exist in the real submission environment

## parse_submission_logs utility
Can extract prices/trades CSVs from official submission logs:
```
python -m prosperity4bt.parse_submission_logs <logfile> <round> <day>
```
Writes to `prosperity4bt/resources/roundN/`.

## Visualizer
`--vis` flag opens results at `https://jmerle.github.io/imc-prosperity-3-visualizer/` via a local HTTP server. Requires algorithm to log in the visualizer's expected format.

## Conversions
Not supported by this backtester.
