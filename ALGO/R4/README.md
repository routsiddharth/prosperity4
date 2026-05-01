# Round 4 — "Hello, I'm Mark"

Second round of the Great Orbital Ascension Trials. Same instruments as Round 3, but
counterparty identities are now disclosed in trade data, and a separate manual-trading
opportunity on Aether Crystal options runs alongside the algo challenge.

## What's in this folder

```
R4/
├── README.md              this file
├── trader.py              working algo for the round
├── ROUND_4/               historical market data (days 1, 2, 3)
│   ├── prices_round_4_day_{1,2,3}.csv
│   └── trades_round_4_day_{1,2,3}.csv     ← buyer/seller fields populated
├── ROUND_4.zip            zipped copy of ROUND_4/
├── 496712/                a submission run (algo + log + visualizer json)
│   ├── 496712.py
│   ├── 496712.log
│   └── 496712.json
└── 496712.zip
```

## Instruments (unchanged from R3)

| Product                       | Type         | Position limit |
|-------------------------------|--------------|----------------|
| `HYDROGEL_PACK`               | delta-1      | 200            |
| `VELVETFRUIT_EXTRACT` (VEV)   | delta-1      | 200            |
| `VEV_4000` … `VEV_6500` (×10) | call options | 300 each       |

Voucher strikes: 4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500.
All vouchers expire on the same date — 7 days from the start of Round 1.

### Time to expiry

| Round / day              | TTE   |
|--------------------------|-------|
| Hist. day 0 (tutorial)   | 8d    |
| Hist. day 1 (R1)         | 7d    |
| Hist. day 2 (R2)         | 6d    |
| Hist. day 3 / R3 start   | 5d    |
| **R4 start**             | **4d**|

Vouchers cannot be exercised early. Inventory does not carry between rounds; any open
position at round end is liquidated against a hidden fair value.

## Difference vs. Round 3

1. **Counterparty IDs** — `Trade.buyer` / `Trade.seller` are no longer `None`. Names
   like `Mark 01`, `Mark 14`, `Mark 22`, `Mark 38`, `Mark 49`, `Mark 55`, `Mark 67`
   appear in `trades_round_4_day_*.csv`. You can profile each counterparty's behavior
   and condition your strategy on who you're trading against.
2. **Day window shifted forward by one day.** Days 1–2 are byte-identical to R3's
   days 1–2 (verified by md5); day 3 is new out-of-sample data. TTE drops from 5d
   (R3 start) to 4d (R4 start).
3. **Manual-trading side game** — Aether Crystal + a set of option contracts on it.
   This is one-shot, completely separate from the algo, and does not affect positions
   or PnL on the algo side.

## Round objective

- **Algo:** Optimize `trader.py` to trade `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and
  the 10 `VEV_*` vouchers, using counterparty identity as an additional signal.
- **Manual:** Pick from the offered Aether Crystal / option menu and submit orders
  for extra one-time profit.

## References

- `../algo_trading_reference.md` — Trader class, TradingState, OrderDepth, datamodel
- `../../backtester_reference.md` — local backtester CLI
- `../R3/` — prior-round algo and data; R4 days 1–2 = R3 days 1–2
