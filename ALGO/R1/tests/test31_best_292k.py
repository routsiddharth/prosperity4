"""
test31: Best-so-far, 292,099 on backtester.

Strategy:
- IPR: buy best_ask aggressively to max long (hold trend).
- ACO: no aggressive take. Pure ladder passive quotes at every integer offset
  from fair-13..fair-1 and fair+1..fair+13, size 6 per level (78 per side).
  Plus flatten-at-fair when position is non-zero and book has counterparty at 10000.
  List order is DEEPEST-FIRST so market-trade matching captures deep trades
  at deep prices (biggest edge).

Anchor fair = 10000 (ACO is strongly mean-reverting around this).
"""
import json
from typing import Any

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict, conversions: int, trader_data: str) -> None:
        base = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        mil = (self.max_log_length - base) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, mil)),
            self.compress_orders(orders), conversions,
            self.truncate(trader_data, mil), self.truncate(self.logs, mil)]))
        self.logs = ""

    def compress_state(self, s, td):
        return [s.timestamp, td,
                [[l.symbol, l.product, l.denomination] for l in s.listings.values()],
                {k: [v.buy_orders, v.sell_orders] for k, v in s.order_depths.items()},
                [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                 for a in s.own_trades.values() for t in a],
                [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                 for a in s.market_trades.values() for t in a],
                s.position,
                [s.observations.plainValueObservations,
                 {p: [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff,
                      o.importTariff, o.sugarPrice, o.sunlightIndex]
                  for p, o in s.observations.conversionObservations.items()}]]

    def compress_orders(self, orders):
        return [[o.symbol, o.price, o.quantity] for a in orders.values() for o in a]

    def to_json(self, v):
        return json.dumps(v, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, v, m):
        lo, hi = 0, min(len(v), m)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            c = v[:mid]
            if len(c) < len(v):
                c += "..."
            if len(json.dumps(c)) <= m:
                out = c
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


class Trader:
    POSITION_LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
    ACO_FAIR = 10000
    LADDER_DEPTH = 13
    LEVEL_SIZE = 6

    def run(self, state: TradingState):
        result = {}
        for product, od in state.order_depths.items():
            orders = []
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 80)
            if not od.buy_orders or not od.sell_orders:
                result[product] = orders
                continue
            best_bid = max(od.buy_orders)
            best_ask = min(od.sell_orders)

            if product == "INTARIAN_PEPPER_ROOT":
                buy_qty = limit - pos
                if buy_qty > 0:
                    orders.append(Order(product, best_ask, buy_qty))

            elif product == "ASH_COATED_OSMIUM":
                orders = self.aco_orders(product, od, pos, limit)

            result[product] = orders

        logger.flush(state, result, 0, "")
        return result, 0, ""

    @classmethod
    def aco_orders(cls, product, od, pos, limit):
        orders = []
        fair = cls.ACO_FAIR
        remaining_buy = max(0, limit - pos)
        remaining_sell = max(0, limit + pos)

        # Flatten at fair when position is non-zero and counterparty exists at fair.
        if pos < 0 and remaining_buy > 0 and fair in od.sell_orders:
            qty = min(remaining_buy, -od.sell_orders[fair], abs(pos))
            if qty > 0:
                orders.append(Order(product, fair, qty))
                remaining_buy -= qty
        elif pos > 0 and remaining_sell > 0 and fair in od.buy_orders:
            qty = min(remaining_sell, od.buy_orders[fair], abs(pos))
            if qty > 0:
                orders.append(Order(product, fair, -qty))
                remaining_sell -= qty

        # Passive ladder: deepest offset first in list.
        # Deep-first ordering means a market trade at a deep price (e.g. 9985)
        # matches our deepest bid (e.g. 9987) at that bid's price — saving ticks
        # versus matching a shallower bid (which would fill at a price closer to fair).
        for offset in range(cls.LADDER_DEPTH, 0, -1):
            if remaining_buy <= 0:
                break
            qty = min(cls.LEVEL_SIZE, remaining_buy)
            if qty > 0:
                orders.append(Order(product, fair - offset, qty))
                remaining_buy -= qty

        for offset in range(cls.LADDER_DEPTH, 0, -1):
            if remaining_sell <= 0:
                break
            qty = min(cls.LEVEL_SIZE, remaining_sell)
            if qty > 0:
                orders.append(Order(product, fair + offset, -qty))
                remaining_sell -= qty

        return orders
