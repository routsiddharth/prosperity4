# Prosperity 4 — Algorithmic Trading Reference

## The Challenge

Write a `Trader` class in Python that trades on Prosperity's exchange against bots to earn XIRECs. The algo challenge has several rounds on different days. Each round discloses new tradable products with sample data.

- **Testing**: 1,000 iterations on historical data
- **Final simulation**: 10,000 iterations
- **Execution**: AWS Lambda (stateless) — class/global variables are NOT guaranteed to persist between calls
- **Time limit**: 900ms per `run()` call (avg should be <= 100ms)
- **State persistence**: Use `traderData` string (serialized via jsonpickle). Capped at 50,000 characters.
- **Round 2 only — `bid()` method**: Round 2 also requires a `bid()` method on `Trader` returning an `int`. It is safe to leave a `bid()` method in submissions for every round — it is ignored outside Round 2.

## Trader Class Structure

```python
from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List

class Trader:

    def bid(self):
        # Only used in Algo Round 2; ignored in all other rounds
        return 15

    def run(self, state: TradingState):
        result = {}  # Dict[str, List[Order]]

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            # ... trading logic ...
            result[product] = orders

        traderData = ""   # Serialized state string for next iteration
        conversions = 0   # Conversion request (int); 0 or None if not needed
        return result, conversions, traderData
```

### Return value: `(result, conversions, traderData)`
- **result**: `Dict[str, List[Order]]` — orders keyed by product
- **conversions**: `int` — conversion request count (see Conversions section)
- **traderData**: `str` — serialized state carried to next iteration

## TradingState

```python
class TradingState:
    traderData: str                          # State string from previous iteration
    timestamp: int                           # Current timestamp
    listings: Dict[Symbol, Listing]          # Product listings
    order_depths: Dict[Symbol, OrderDepth]   # Current order book per product
    own_trades: Dict[Symbol, List[Trade]]    # Your trades since last iteration
    market_trades: Dict[Symbol, List[Trade]] # Other participants' trades since last iteration
    position: Dict[Product, int]             # Current position per product
    observations: Observation                # External observations
```

### Key properties
- **order_depths**: Outstanding buy/sell orders from bots that you can trade against
- **own_trades**: Your fills since last `TradingState`. Buyer/seller = `"SUBMISSION"` when it's you
- **market_trades**: Bot-to-bot trades since last state. Counterparty info is hidden (empty strings)
- **position**: Signed integer per product (positive = long, negative = short)

## OrderDepth

```python
class OrderDepth:
    buy_orders: Dict[int, int] = {}   # price -> positive quantity
    sell_orders: Dict[int, int] = {}  # price -> NEGATIVE quantity
```

- Buy orders: `{10: 7, 9: 5}` means qty 7 at price 10, qty 5 at price 9
- Sell orders: `{11: -4, 12: -8}` means qty 4 offered at 11, qty 8 at 12 (values are negative)
- All buy prices are strictly below all sell prices (no crossed book)

## Order

```python
class Order:
    symbol: str    # Product name
    price: int     # Max buy price or min sell price
    quantity: int  # Positive = BUY, Negative = SELL
```

- Orders that cross the spread execute immediately against bot orders
- Remaining unfilled quantity sits as a quote; bots may trade against it
- Unmatched quotes are cancelled at end of iteration
- **No latency disadvantage**: any order that *could* match a bot quote in the current state *will* match — bots cannot front-run you within an iteration

## Trade

```python
class Trade:
    symbol: str
    price: int
    quantity: int
    buyer: str    # "SUBMISSION" if you bought, else "" (hidden)
    seller: str   # "SUBMISSION" if you sold, else "" (hidden)
    timestamp: int
```

## Position Limits

- Defined per product per round (check round-specific wiki)
- Absolute limit: position cannot exceed +limit or -limit
- **Enforcement**: If aggregated buy (sell) order quantity would push position past the limit assuming all fill, ALL orders for that product are rejected
- **Example**: limit=30, position=-5 -> max buy quantity = 30 - (-5) = 35

## Conversions (via Observation)

```python
class ConversionObservation:
    bidPrice: float
    askPrice: float
    transportFees: float
    exportTariff: float
    importTariff: float
    sugarPrice: float       # Note: the published datamodel.py has a bug here —
    sunlightIndex: float    # the __init__ params are named `sunlight, humidity`
                            # but the attributes are assigned `sugarPrice, sunlightIndex`.
                            # Read these attributes; don't rely on the constructor signature.
```

### Conversion rules
- Must already hold a position (long or short) to convert
- Request cannot exceed your held quantity
- Example: position = -10 -> can request 1 to 10 only; 11+ is fully ignored
- Covers transport + import/export tariff costs
- Return 0 or None if no conversion needed

## Observation

```python
class Observation:
    plainValueObservations: Dict[Product, int]                    # Simple product -> value
    conversionObservations: Dict[Product, ConversionObservation]  # Complex observations
```

## Order Execution Mechanics

1. Orders execute **instantaneously** — no latency disadvantage vs bots
2. Your buy orders match against sell_orders at prices <= your price (best price first)
3. Your sell orders match against buy_orders at prices >= your price (best price first)
4. Partial fills are possible; remainder becomes a standing quote
5. Bots may trade against your standing quote before next iteration
6. If no bot trades against it, the quote is auto-cancelled
7. Between cancellation and next state, bots may also trade with each other

## Worked Example: Two Iterations

Assume PRODUCT1 limit=10, PRODUCT2 limit=20. At `timestamp=1000`:

```python
order_depths = {
    "PRODUCT1": OrderDepth(buy_orders={10: 7, 9: 5}, sell_orders={11: -4, 12: -8}),
    "PRODUCT2": OrderDepth(buy_orders={142: 3, 141: 5}, sell_orders={144: -5, 145: -8}),
}
position = {"PRODUCT1": 3, "PRODUCT2": -5}
```

Algorithm believes PRODUCT1 fair=13, PRODUCT2 fair=142. It decides:
- PRODUCT1: Both asks (11, 12) are below fair value. Position 3, limit 10 → max buy = 7.
  Send `Order("PRODUCT1", 12, 7)` — a buy of 7 at price 12 (crosses both levels).
- PRODUCT2: Neither side is profitable vs fair. Post a sell quote above the book:
  `Order("PRODUCT2", 143, -5)`.

At `timestamp=1100` the next state shows:

```python
order_depths["PRODUCT1"] = OrderDepth(buy_orders={10: 7, 9: 5}, sell_orders={12: -5, 13: -3})
own_trades["PRODUCT1"] = [
    Trade("PRODUCT1", 11, 4, buyer="SUBMISSION", ...),   # full fill at 11
    Trade("PRODUCT1", 12, 3, buyer="SUBMISSION", ...),   # partial fill at 12
]
own_trades["PRODUCT2"] = [Trade("PRODUCT2", 143, 2, seller="SUBMISSION", ...)]
position = {"PRODUCT1": 10, "PRODUCT2": -7}
```

Key observations:
- The buy crossed the 11 level entirely, then 3 of the 8 at 12 (remaining 5 still visible).
- On PRODUCT2, one bot took 2 of the 5 posted at 143; the other 3 were **auto-cancelled** (no longer a standing quote in the new state).
- Positions updated accordingly.

## Order Rejection on Position Limit

The exchange rejects orders **per side, per product** if the aggregated quantity would breach the limit assuming all orders fill:

- Aggregated BUY quantity > `LIMIT - position` → all BUY orders for that product rejected
- Aggregated SELL quantity > `LIMIT + position` → all SELL orders for that product rejected

Buy and sell sides are evaluated independently. A single order exactly at the max allowed size is legal.

## Submission Format Gotchas (silent profit=0 failures)

Symptoms: official tester reports `profit: 0` even though the same `Trader` runs fine in the local `prosperity4btest` backtester. These are the failure modes that have actually bitten this project:

### 1. PEP 604 union syntax (`X | None`) breaks the import

The official tester's Python runtime appears to **not support** PEP 604 `X | None` annotations. If a `Trader.py` uses `def _mid(self, depth: OrderDepth) -> float | None:`, the import fails, the class never instantiates, `run()` is never called, and the submission silently posts zero trades. The local backtester (Python 3.13) accepts the syntax fine, so the bug only shows up after submission.

**Use `Optional[X]` (with `from typing import Optional`) or omit the return annotation entirely.** Mirror `trader_snackpacks.py` / `549866.py` style:

```python
def _mid(self, depth: OrderDepth):    # no -> annotation
    if not depth.buy_orders or not depth.sell_orders:
        return None
    return (max(depth.buy_orders.keys()) + min(depth.sell_orders.keys())) / 2.0
```

Quick guard: `python -c "import ast; ast.parse(open('trader.py').read(), feature_version=(3, 9))"` should succeed.

### 2. Logger import must include every datamodel class it serializes

The `Logger.flush` boilerplate uses `ProsperityEncoder`, which calls `__dict__` on each object it sees. If any class instance reaching the encoder is unimported (e.g. `Listing`, `Trade`, `Observation`), Python doesn't error but the submission environment may behave unexpectedly. Always import the full set:

```python
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
```

### 3. `traderData` 50,000-char cap is hard

Naive `json.dumps` of a 6,000-element list of floats produces ~72k chars and exceeds the cap. Compact encoding tricks that have worked in this project:

- Multiply by 2 and round: `int(round(x * 2))`. Mids are half-integers, so basket sums are also half-integers; `*2` makes them exact ints.
- Comma-separated ints, no JSON wrapper: `",".join(str(int(round(v*2))) for v in history)`. ~6 chars × 6,000 ≈ 36k.
- Multiple histories: pipe-separate them: `enc(hist_a) + "|" + enc(hist_b)`.

Decode with a `try/except ValueError` around `int(s)` so a corrupted blob doesn't crash `run()`.

### 4. Local backtester is more forgiving than the submission environment

The local backtester (`prosperity4btest`) does NOT enforce the 50k traderData cap, doesn't reject PEP 604 syntax, and tolerates a few format quirks the official tester rejects. **Local pass ≠ submission pass.** When stuck, diff your file structure against a known-working submission file (e.g. `ALGO/R5/549866.py`).

### Working template structure (matches `trader_snackpacks.py`)

```
import json
from typing import Dict, List, Tuple

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState

# ---- Logger boilerplate (see Logging section below) ----

logger = Logger()

class Trader:
    # ... constants ...

    def _mid(self, depth: OrderDepth):           # NO -> float | None
        ...

    def _encode(self, hist: List[float]) -> str:
        return ",".join(str(int(round(v * 2))) for v in hist)

    def _decode(self, blob: str) -> List[float]:
        if not blob:
            return []
        try:
            return [int(s) / 2.0 for s in blob.split(",") if s]
        except ValueError:
            return []

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        # ... trading logic ...
        trader_data = self._encode(history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data
```

## Submissions & Debugging

- Every uploaded submission generates a **submission UUID** (e.g. `59f81e67-f6c6-4254-b61e-39661eac6141`) and a **runID** (e.g. `"498"`). Include these when asking Prosperity staff / Discord for help.
- **Sample data**: Each round ships per-day CSVs for new products — one with all trades, one with market orders at every timestep.
- **Platform log**: After upload, the algorithm runs 1,000 iterations on a sample day (different from the scoring day). A log file with debug output (including `print`/`logger.print`) is provided for inspection.

## Supported Libraries

All Python 3.12 standard libraries plus:
- pandas
- NumPy
- statistics
- math
- typing
- jsonpickle

No other external libraries are supported.

## datamodel.py (full reference)

```python
import json
from typing import Dict, List
from json import JSONEncoder
import jsonpickle

Time = int
Symbol = str
Product = str
Position = int
UserId = str
ObservationValue = int

class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: Product):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination

class ConversionObservation:
    def __init__(self, bidPrice: float, askPrice: float, transportFees: float,
                 exportTariff: float, importTariff: float, sunlight: float, humidity: float):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sugarPrice = sugarPrice
        self.sunlightIndex = sunlightIndex

class Observation:
    def __init__(self, plainValueObservations: Dict[Product, ObservationValue],
                 conversionObservations: Dict[Product, ConversionObservation]) -> None:
        self.plainValueObservations = plainValueObservations
        self.conversionObservations = conversionObservations

class Order:
    def __init__(self, symbol: Symbol, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}
        self.sell_orders: Dict[int, int] = {}

class Trade:
    def __init__(self, symbol: Symbol, price: int, quantity: int,
                 buyer: UserId = None, seller: UserId = None, timestamp: int = 0) -> None:
        self.symbol = symbol
        self.price: int = price
        self.quantity: int = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp

class TradingState(object):
    def __init__(self, traderData: str, timestamp: Time,
                 listings: Dict[Symbol, Listing],
                 order_depths: Dict[Symbol, OrderDepth],
                 own_trades: Dict[Symbol, List[Trade]],
                 market_trades: Dict[Symbol, List[Trade]],
                 position: Dict[Product, Position],
                 observations: Observation):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations

    def toJSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)

class ProsperityEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__
```

## Quick Reference: Common Patterns

### Getting best bid/ask
```python
best_bid = max(order_depth.buy_orders.keys())
best_ask = min(order_depth.sell_orders.keys())
mid_price = (best_bid + best_ask) / 2
```

### Safe position check
```python
current_pos = state.position.get(product, 0)
```

### Respecting position limits
```python
pos = state.position.get(product, 0)
max_buy_qty = LIMIT - pos       # Max you can buy without exceeding +LIMIT
max_sell_qty = LIMIT + pos      # Max you can sell without exceeding -LIMIT
```

### Serializing state with jsonpickle
```python
import jsonpickle

# Save
traderData = jsonpickle.encode(my_state_dict)

# Restore
if state.traderData:
    my_state_dict = jsonpickle.decode(state.traderData)
```

## Logging (IMC Prosperity Visualizer Format)

The IMC Prosperity 3 Visualizer expects logs in a specific compressed JSON format. Algorithms that use a different logging format will cause unexpected errors when opened in the visualizer. **Use the `Logger` class below** and call `logger.print()` instead of Python's built-in `print()`.

### Requirements
- Your code contains the `Logger` class shown below
- Your code calls `logger.flush()` at the end of `Trader.run()`
- Your code does **not** call Python's built-in `print()` — use `logger.print()` instead

### Logger boilerplate

```python
import json
from typing import Any

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]

        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])

        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2

            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."

            encoded_candidate = json.dumps(candidate)

            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out


logger = Logger()
```

### Usage in Trader class

```python
class Trader:
    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        result = {}
        conversions = 0
        trader_data = ""

        # Use logger.print() instead of print()
        logger.print("timestamp:", state.timestamp)

        # ... trading logic ...

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
```
