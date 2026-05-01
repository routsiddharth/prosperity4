"""Shakes basket mean-reversion trader (Round 5).

Basket B = GARLIC + MORNING_BREATH + EVENING_BREATH - CHOCOLATE.
Notebook §11 found this is the most stationary integer-coefficient basket in
the 5-shake group: ADF p=0.0075, half-life ~867 ticks. Unit weights mean a
position cap of MAX_BASKET on every leg with no hedge-ratio rounding error.

Robustness choices:
- mu and sigma are computed online from a rolling window of basket values
  stored in traderData. WINDOW=6,000 (>> half-life) so mu represents the
  equilibrium, not the current excursion.
- Threshold z=2.5 entry / z=0.0 flip-only exit.
- Pure threshold flip (no z-scaled position sizing) avoids whipsaw.
- Confidence-scaled position cap with floor: max position =
  MAX_BASKET * max(SIZE_FLOOR, n / WINDOW). FLOOR=0.7 is the boundary where
  the strategy keeps the fully-protected drawdown while recovering ~82% of
  the no-floor baseline PnL.
- Storage: comma-separated `int(basket * 2)`; ~36k chars at WINDOW=6,000.

Format mirrors trader_snackpacks.py so it works in the official tester:
- No `X | None` PEP 604 type-hint syntax (breaks pre-3.10 import).
- Logger boilerplate emits jmerle-visualizer-format JSON to stdout.
- Full datamodel imports (Listing/Observation/etc.) so ProsperityEncoder
  has every type it needs to serialize.
"""
import json
from typing import Dict, List

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


GARLIC   = "OXYGEN_SHAKE_GARLIC"
MORNING  = "OXYGEN_SHAKE_MORNING_BREATH"
EVENING  = "OXYGEN_SHAKE_EVENING_BREATH"
CHOCO    = "OXYGEN_SHAKE_CHOCOLATE"

BASKET_LEGS = {
    GARLIC:  +1,
    MORNING: +1,
    EVENING: +1,
    CHOCO:   -1,
}


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders, conversions, trader_data: str) -> None:
        base_length = len(
            self.to_json([
                self.compress_state(state, ""),
                self.compress_orders(orders),
                conversions,
                "",
                "",
            ])
        )
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state, trader_data):
        return [
            state.timestamp, trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings):
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths):
        return {s: [d.buy_orders, d.sell_orders] for s, d in order_depths.items()}

    def compress_trades(self, trades):
        out = []
        for arr in trades.values():
            for t in arr:
                out.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return out

    def compress_observations(self, obs):
        co = {}
        for p, o in obs.conversionObservations.items():
            co[p] = [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff,
                     o.importTariff, o.sugarPrice, o.sunlightIndex]
        return [obs.plainValueObservations, co]

    def compress_orders(self, orders):
        out = []
        for arr in orders.values():
            for o in arr:
                out.append([o.symbol, o.price, o.quantity])
        return out

    def to_json(self, value):
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            cand = value[:mid]
            if len(cand) < len(value):
                cand += "..."
            if len(json.dumps(cand)) <= max_length:
                out = cand
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


class Trader:
    LIMIT = 10

    WINDOW = 6000
    WARMUP = 1000

    ENTRY_Z = 2.5
    EXIT_Z = 0.0
    MAX_BASKET = 10

    SIGMA_FLOOR = 50.0

    SIZE_FLOOR = 0.7

    def _mid(self, depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders:
            return None
        return (max(depth.buy_orders.keys()) + min(depth.sell_orders.keys())) / 2.0

    def _send_to_target(
        self,
        symbol: str,
        depth: OrderDepth,
        current_pos: int,
        target_pos: int,
        orders_out: List[Order],
    ) -> None:
        delta = target_pos - current_pos
        if delta == 0:
            return
        if delta > 0:
            if not depth.sell_orders:
                return
            best_ask = min(depth.sell_orders.keys())
            qty_avail = -depth.sell_orders[best_ask]
            qty = min(delta, qty_avail)
            if qty > 0:
                orders_out.append(Order(symbol, best_ask, qty))
        else:
            if not depth.buy_orders:
                return
            best_bid = max(depth.buy_orders.keys())
            qty_avail = depth.buy_orders[best_bid]
            qty = min(-delta, qty_avail)
            if qty > 0:
                orders_out.append(Order(symbol, best_bid, -qty))

    def _decode(self, blob: str) -> List[float]:
        if not blob:
            return []
        try:
            return [int(s) / 2.0 for s in blob.split(",") if s]
        except ValueError:
            return []

    def _encode(self, hist: List[float]) -> str:
        return ",".join(str(int(round(v * 2))) for v in hist)

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        history = self._decode(state.traderData)

        depths = state.order_depths
        position = state.position

        if not all(p in depths for p in BASKET_LEGS):
            trader_data = self._encode(history)
            logger.flush(state, result, 0, trader_data)
            return result, 0, trader_data

        mids = {}
        ok = True
        for p in BASKET_LEGS:
            m = self._mid(depths[p])
            if m is None:
                ok = False
                break
            mids[p] = m

        if not ok:
            trader_data = self._encode(history)
            logger.flush(state, result, 0, trader_data)
            return result, 0, trader_data

        basket = (
            mids[GARLIC] + mids[MORNING] + mids[EVENING] - mids[CHOCO]
        )

        history.append(basket)
        if len(history) > self.WINDOW:
            history = history[-self.WINDOW:]

        cur_basket_pos = position.get(GARLIC, 0)
        target_basket = cur_basket_pos

        if len(history) >= self.WARMUP:
            n = len(history)
            mu = sum(history) / n
            var = sum((x - mu) ** 2 for x in history) / n
            sigma = max(var ** 0.5, self.SIGMA_FLOOR)
            z = (basket - mu) / sigma

            size_fraction = min(1.0, max(self.SIZE_FLOOR, n / self.WINDOW))
            max_pos = int(round(self.MAX_BASKET * size_fraction))

            if z >= self.ENTRY_Z:
                target_basket = -max_pos
            elif z <= -self.ENTRY_Z:
                target_basket = max_pos
            elif abs(z) <= self.EXIT_Z:
                target_basket = 0

        for sym, sign in BASKET_LEGS.items():
            target = target_basket * sign
            cur = position.get(sym, 0)
            orders = result.setdefault(sym, [])
            self._send_to_target(sym, depths[sym], cur, target, orders)

        # Drop empty order lists for cleaner logs.
        result = {k: v for k, v in result.items() if v}

        trader_data = self._encode(history)
        logger.flush(state, result, 0, trader_data)
        return result, 0, trader_data