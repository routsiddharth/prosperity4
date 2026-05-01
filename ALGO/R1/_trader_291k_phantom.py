import json
from typing import Any, Dict, List

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


class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # ACO parameters
    ACO_ANCHOR = 10000           # known long-term fair — used for take + flatten
    ACO_TAKE_THRESHOLD = 999     # disabled — ladder captures equivalent real-book fills
    ACO_UNWIND_AT_FAIR_POS = 30  # when |pos| ≥ this, allow flattening quote at anchor
    ACO_BASE_QUOTE_SIZE = 15     # passive quote size at neutral inventory
    ACO_DEEP_QUOTE_SIZE = 20     # size at deeper tier
    ACO_WIDE_SPREAD = 4          # spread ≥ this → post at anchor ± tight_offset
    ACO_TIGHT_OFFSET = 1         # tight tier offset from anchor
    ACO_LADDER_OFFSETS = (7,)   # deep tier offsets (each a distinct price level)
    # Pyramid ladder: deeper tiers (higher edge) slightly smaller, shallower
    # tiers larger (where more market-trade volume is). Deepest first.
    ACO_LADDER_TIERS = (
        (15, 3), (14, 3), (13, 3), (12, 3), (11, 4), (10, 4), (9, 4),
        (8, 5), (7, 5), (6, 6), (5, 6), (4, 7), (3, 8), (2, 9), (1, 10),
    )
    ACO_MR_COEF = 0            # AC(1) ≈ −0.5 → shift quotes by half the last-tick move
    ACO_DRIFT_COEF = 0.5         # shift quotes toward anchor when mid drifts

    # IPR parameters
    IPR_SWEEP_OFFSET = 5         # post buy at best_ask + this to sweep depth 2/3
    IPR_PASSIVE_BID_OFFSET = 5   # passive bid = best_bid + this (single-tier fallback)
    IPR_LADDER_TIERS = ((1, 40),(3, 30),(5, 10))

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}
        conversions = 0

        prev = self._load_prev(state.traderData)
        next_state: Dict[str, float] = {}

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 80)

            if product == "INTARIAN_PEPPER_ROOT":
                if not order_depth.sell_orders:
                    result[product] = orders
                    continue
                orders = self.ipr_orders(product, order_depth, position, limit)
            elif product == "ASH_COATED_OSMIUM":
                if not order_depth.buy_orders or not order_depth.sell_orders:
                    result[product] = orders
                    continue
                best_bid = max(order_depth.buy_orders)
                best_ask = min(order_depth.sell_orders)
                prev_mid = prev.get("ACO_last_mid")
                orders, mid = self.aco_orders(
                    product, order_depth, best_bid, best_ask, position, limit, prev_mid
                )
                next_state["ACO_last_mid"] = mid

            result[product] = orders

        trader_data = json.dumps(next_state)
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    @staticmethod
    def _load_prev(trader_data: str) -> Dict[str, float]:
        if not trader_data:
            return {}
        try:
            parsed = json.loads(trader_data)
            if isinstance(parsed, dict):
                return {k: float(v) for k, v in parsed.items()}
        except Exception:
            pass
        return {}

    @classmethod
    def ipr_orders(
        cls, product: str, order_depth: OrderDepth, position: int, limit: int
    ) -> List[Order]:
        orders: List[Order] = []
        best_ask = min(order_depth.sell_orders)
        buy_qty = limit - position
        if buy_qty <= 0:
            return orders
        if not order_depth.buy_orders:
            sweep_price = best_ask + cls.IPR_SWEEP_OFFSET
            orders.append(Order(product, sweep_price, buy_qty))
            return orders
        best_bid = max(order_depth.buy_orders)
        # Multi-tier IPR bids. Post deepest (best_bid+1) first so it grabs the
        # best-priced trades; shallower tiers catch trades that skip deeper bids.
        posted = 0
        for off, size in cls.IPR_LADDER_TIERS:
            bp = best_bid + off
            q = min(size, buy_qty - posted)
            if q > 0:
                orders.append(Order(product, bp, q))
                posted += q
        return orders

    @classmethod
    def aco_orders(
        cls,
        product: str,
        order_depth: OrderDepth,
        best_bid: int,
        best_ask: int,
        position: int,
        limit: int,
        prev_mid: float | None,
    ) -> tuple[List[Order], float]:
        orders: List[Order] = []

        # Two fairs (mid_fair pattern):
        #   anchor   = long-term true value, used where correctness matters (take/flatten)
        #   fair_int = live mid, used as the clamp for passive quotes so they track action
        anchor = cls.ACO_ANCHOR
        mid = (best_bid + best_ask) / 2.0
        fair_int = int(round(mid))

        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)
        remaining_buy = buy_capacity
        remaining_sell = sell_capacity

        # --- 1) Aggressive take at anchor ---
        for ask_price in sorted(order_depth.sell_orders):
            if ask_price > anchor - cls.ACO_TAKE_THRESHOLD or remaining_buy <= 0:
                break
            ask_volume = -order_depth.sell_orders[ask_price]
            qty = min(remaining_buy, ask_volume)
            if qty > 0:
                orders.append(Order(product, ask_price, qty))
                remaining_buy -= qty

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if bid_price < anchor + cls.ACO_TAKE_THRESHOLD or remaining_sell <= 0:
                break
            bid_volume = order_depth.buy_orders[bid_price]
            qty = min(remaining_sell, bid_volume)
            if qty > 0:
                orders.append(Order(product, bid_price, -qty))
                remaining_sell -= qty

        # Ladder: deepest first. Each tier posts at (anchor ± off), processes against
        # market trades in order — deeper bids/asks grab higher-edge fills first.
        buy_posted = 0
        sell_posted = 0
        posted_bids = set()
        posted_asks = set()
        for off, size in cls.ACO_LADDER_TIERS:
            bp = anchor - off
            ap = anchor + off
            q = min(size, remaining_buy - buy_posted)
            if q > 0 and bp not in posted_bids and bp < anchor:
                orders.append(Order(product, bp, q))
                posted_bids.add(bp)
                buy_posted += q
            q = min(size, remaining_sell - sell_posted)
            if q > 0 and ap not in posted_asks and ap > anchor:
                orders.append(Order(product, ap, -q))
                posted_asks.add(ap)
                sell_posted += q

        return orders, mid
