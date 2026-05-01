"""
translator_trader.py — Round 5 deployment.

Strategy: passive 5-product market maker on the TRANSLATORS, derived from
`translator_strategy.md` and `translator_strategy_analysis.ipynb`.

Mechanics (per tick, per translator):
  1. Read order book; require both sides of the BBO present and spread >= 3
     (we need room for the +1-tick BBO improvement on each side without
     crossing our own quotes).
  2. bid_quote = best_bid + IMPROVE  (=best_bid + 1)
     ask_quote = best_ask - IMPROVE  (=best_ask - 1)
  3. Apply hard inventory cutoff (THRESH = 3):
       - inv >= +THRESH  : suppress bid (no buys); only post ask.
       - inv <= -THRESH  : suppress ask (no sells); only post bid.
       - else            : post both sides.
  4. Quote size capped at MAX_QUOTE per side, further capped by remaining
     position-limit headroom so the exchange does not reject the order list.

Removed (per round-5 deployment notes):
  - Halt-on-drawdown logic.
  - End-of-day flatten (round runs a single day).

Parameters (from `translator_strategy.md` §2.2 with THRESH overridden to 3 per
the §3a-bis sweep recommendation in `translator_strategy_analysis.ipynb`):
  POS_LIMIT  = 10  (round-5 brief)
  THRESH     = 3   (best worst-day PnL; ~5% below peak total at THRESH=5)
  IMPROVE    = 1   (smallest BBO undercut that keeps strict price priority)
  MAX_QUOTE  = 5   (>= max observed bundle qty; bounded by pos-limit headroom)
  MIN_SPREAD = 3   (need spread > 2*IMPROVE to avoid crossing our own quotes)
"""

import json
from typing import Any, Dict, List

from datamodel import (
    Listing,
    Observation,
    Order,
    OrderDepth,
    ProsperityEncoder,
    Symbol,
    Trade,
    TradingState,
)


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: dict[Symbol, list[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
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

        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(
                        state,
                        self.truncate(state.traderData, max_item_length),
                    ),
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

    def compress_order_depths(
        self,
        order_depths: dict[Symbol, OrderDepth],
    ) -> dict[Symbol, list[Any]]:
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


class Trader:
    TRANSLATORS = [
        "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL",
        "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_SPACE_GRAY",
        "TRANSLATOR_VOID_BLUE",
    ]

    POS_LIMIT = 10
    THRESH = 3
    IMPROVE = 1
    MAX_QUOTE = 5
    MIN_SPREAD = 3  # need (best_ask - best_bid) >= 3 to safely improve both sides

    def run(self, state: TradingState):
        orders_by_product: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            orders_by_product[product] = []
            if product not in self.TRANSLATORS:
                continue

            depth = state.order_depths[product]
            position = int(state.position.get(product, 0))
            orders_by_product[product] = self.market_make(product, depth, position)

        conversions = 0
        trader_data = ""

        logger.flush(state, orders_by_product, conversions, trader_data)
        return orders_by_product, conversions, trader_data

    def market_make(
        self, product: str, depth: OrderDepth, position: int
    ) -> List[Order]:
        orders: List[Order] = []

        if not depth.buy_orders or not depth.sell_orders:
            return orders

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        spread = best_ask - best_bid

        if spread < self.MIN_SPREAD:
            return orders

        bid_quote = best_bid + self.IMPROVE
        ask_quote = best_ask - self.IMPROVE

        if bid_quote >= ask_quote:
            return orders

        # Hard cutoffs on inventory (the binding controller per analysis).
        suppress_bid = position >= self.THRESH
        suppress_ask = position <= -self.THRESH

        # Capacity left to each side; respects exchange position limit.
        buy_capacity = self.POS_LIMIT - position
        sell_capacity = self.POS_LIMIT + position

        if not suppress_bid and buy_capacity > 0:
            bid_size = min(self.MAX_QUOTE, buy_capacity)
            if bid_size > 0:
                orders.append(Order(product, bid_quote, bid_size))

        if not suppress_ask and sell_capacity > 0:
            ask_size = min(self.MAX_QUOTE, sell_capacity)
            if ask_size > 0:
                orders.append(Order(product, ask_quote, -ask_size))

        return orders