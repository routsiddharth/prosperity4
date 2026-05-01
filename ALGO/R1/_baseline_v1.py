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
    ACO_TAKE_THRESHOLD = 1       # cross spread only when ≥ 1 tick of edge vs anchor
    ACO_BASE_QUOTE_SIZE = 15     # passive quote size at neutral inventory
    ACO_WIDE_SPREAD = 4          # spread ≥ this → post tight (fair ± 1), not penny-inside
    ACO_MR_COEF = 0.5            # AC(1) ≈ −0.5 → shift quotes by half the last-tick move

    # IPR parameters
    IPR_SWEEP_OFFSET = 5         # post buy at best_ask + this to sweep depth 2/3

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
        buy_qty = limit - position
        if buy_qty <= 0:
            return orders
        best_ask = min(order_depth.sell_orders)
        sweep_price = best_ask + cls.IPR_SWEEP_OFFSET
        orders.append(Order(product, sweep_price, buy_qty))
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

        # --- 2) Flatten at anchor if counterparty is sitting there ---
        effective_position = position + sum(o.quantity for o in orders)

        if effective_position < 0 and remaining_buy > 0 and anchor in order_depth.sell_orders:
            ask_volume = -order_depth.sell_orders[anchor]
            qty = min(remaining_buy, ask_volume, abs(effective_position))
            if qty > 0:
                orders.append(Order(product, anchor, qty))
                remaining_buy -= qty
                effective_position += qty
        elif effective_position > 0 and remaining_sell > 0 and anchor in order_depth.buy_orders:
            bid_volume = order_depth.buy_orders[anchor]
            qty = min(remaining_sell, bid_volume, abs(effective_position))
            if qty > 0:
                orders.append(Order(product, anchor, -qty))
                remaining_sell -= qty
                effective_position -= qty

        # --- 3) Recompute effective top-of-book (asks/bids we already consumed) ---
        effective_best_bid = best_bid
        effective_best_ask = best_ask

        if anchor >= best_ask:
            for ask_lvl in sorted(order_depth.sell_orders):
                book_vol = -order_depth.sell_orders[ask_lvl]
                bought_at_lvl = sum(o.quantity for o in orders if o.quantity > 0 and o.price == ask_lvl)
                if bought_at_lvl < book_vol:
                    effective_best_ask = ask_lvl
                    break
            else:
                effective_best_ask = anchor + 1

        if anchor <= best_bid:
            for bid_lvl in sorted(order_depth.buy_orders, reverse=True):
                book_vol = order_depth.buy_orders[bid_lvl]
                sold_at_lvl = sum(-o.quantity for o in orders if o.quantity < 0 and o.price == bid_lvl)
                if sold_at_lvl < book_vol:
                    effective_best_bid = bid_lvl
                    break
            else:
                effective_best_bid = anchor - 1

        # --- 4) Inventory-aware sizing: shrink the side that would add to inventory ---
        pos_ratio = abs(effective_position) / limit       # 0.0 → 1.0
        dampened = max(0.0, 1.0 - pos_ratio * 1.25)       # hits 0 at 80% of limit

        if effective_position > 0:
            passive_buy_qty = int(cls.ACO_BASE_QUOTE_SIZE * dampened)
            passive_sell_qty = cls.ACO_BASE_QUOTE_SIZE
        elif effective_position < 0:
            passive_buy_qty = cls.ACO_BASE_QUOTE_SIZE
            passive_sell_qty = int(cls.ACO_BASE_QUOTE_SIZE * dampened)
        else:
            passive_buy_qty = cls.ACO_BASE_QUOTE_SIZE
            passive_sell_qty = cls.ACO_BASE_QUOTE_SIZE

        passive_buy_qty = min(passive_buy_qty, remaining_buy)
        passive_sell_qty = min(passive_sell_qty, remaining_sell)

        # --- 5) Quote placement ---
        # THE KEY CHANGE vs mid_fair:
        # In a wide book (e.g. 9992/10008), penny-inside gives 9993/10007 — quotes
        # buried 7 ticks from fair that almost never fill. Instead, target fair ± 1
        # directly: same positive edge, but now best bid and best ask in the book.
        spread = effective_best_ask - effective_best_bid
        if spread >= cls.ACO_WIDE_SPREAD:
            bid_price = fair_int - 1
            ask_price = fair_int + 1
        elif spread >= 2:
            bid_price = effective_best_bid + 1
            ask_price = effective_best_ask - 1
        else:
            bid_price = effective_best_bid
            ask_price = effective_best_ask

        # Inventory skew: shift both quotes to encourage mean-reversion of our position.
        # If long, shift down: bid less attractive (less buying), ask more attractive
        # (more filling, faster unwind). Mirror when short.
        skew = round(effective_position / limit * 2)
        bid_price -= skew
        ask_price -= skew

        # Short-memory mean reversion: AC(1) ≈ −0.5 → last tick's move is expected to
        # partially reverse. Shift both quotes against the last move.
        if prev_mid is not None:
            mr_shift = round(cls.ACO_MR_COEF * (mid - prev_mid))
            bid_price -= mr_shift
            ask_price -= mr_shift

        # Safety clamps — bid must stay ≤ live mid, ask must stay ≥ live mid
        bid_price = min(bid_price, effective_best_ask - 1, fair_int)
        ask_price = max(ask_price, effective_best_bid + 1, fair_int)

        if bid_price >= ask_price:
            bid_price = fair_int - 1
            ask_price = fair_int + 1

        if passive_buy_qty > 0 and bid_price < fair_int:
            orders.append(Order(product, bid_price, passive_buy_qty))
        if passive_sell_qty > 0 and ask_price > fair_int:
            orders.append(Order(product, ask_price, -passive_sell_qty))

        return orders, mid
