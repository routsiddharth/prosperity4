import json
import math
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
        orders: Dict[Symbol, List[Order]],
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
                        state, self.truncate(state.traderData, max_item_length)
                    ),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> List[Any]:
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

    def compress_listings(self, listings: Dict[Symbol, Listing]) -> List[List[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(
        self, order_depths: Dict[Symbol, OrderDepth]
    ) -> Dict[Symbol, List[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: Dict[Symbol, List[Trade]]) -> List[List[Any]]:
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

    def compress_observations(self, observations: Observation) -> List[Any]:
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

    def compress_orders(
        self, orders: Dict[Symbol, List[Order]]
    ) -> List[List[Any]]:
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
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    DEFAULT_HISTORY_WINDOW = 20
    TOMATO_WINDOW = 8

    # EMERALDS = v2 logic
    EMERALDS_PASSIVE_SIZE = 12
    EMERALDS_TAKE_WIDTH = 0.5
    EMERALDS_SKEW = 0.10

    # TOMATOES = original v1 logic
    TOMATOES_PASSIVE_SIZE = 10
    TOMATOES_ALPHA = 0.45
    TOMATOES_SKEW = 0.18

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}
        history = self.load_history(state.traderData)

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)

            history.setdefault(product, [])

            if order_depth.buy_orders and order_depth.sell_orders:
                mid_price = self.get_mid_price(order_depth)
                history[product].append(mid_price)
                history[product] = history[product][-self.get_history_window(product):]

                orders = self.trade_product(
                    product=product,
                    order_depth=order_depth,
                    position=position,
                    history=history,
                )

            result[product] = orders

        trader_data = json.dumps(history)
        conversions = 0

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def trade_product(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        history: Dict[str, List[float]],
    ) -> List[Order]:
        if product == "EMERALDS":
            fair_value = 10000.0

            passive_size = self.EMERALDS_PASSIVE_SIZE
            take_width = self.EMERALDS_TAKE_WIDTH

            # v2 EMERALDS logic: slightly more aggressive near flat
            if abs(position) <= 20:
                passive_size += 2
                take_width += 0.1

            return self.market_make_around_fair_value(
                product=product,
                order_depth=order_depth,
                fair_value=fair_value,
                position=position,
                limit=self.POSITION_LIMITS[product],
                passive_size=passive_size,
                take_width=take_width,
                inventory_skew_strength=self.EMERALDS_SKEW,
            )

        if product == "TOMATOES":
            mids = history.get(product, [])

            # v1 TOMATOES logic
            fair_value = self.ema(mids, alpha=self.TOMATOES_ALPHA)

            vol = self.rolling_vol(mids)
            take_width = max(0.5, min(2.0, 0.5 + 0.35 * vol))

            return self.market_make_around_fair_value(
                product=product,
                order_depth=order_depth,
                fair_value=fair_value,
                position=position,
                limit=self.POSITION_LIMITS[product],
                passive_size=self.TOMATOES_PASSIVE_SIZE,
                take_width=take_width,
                inventory_skew_strength=self.TOMATOES_SKEW,
            )

        return []

    def market_make_around_fair_value(
        self,
        product: str,
        order_depth: OrderDepth,
        fair_value: float,
        position: int,
        limit: int,
        passive_size: int = 5,
        take_width: float = 0.0,
        inventory_skew_strength: float = 0.1,
    ) -> List[Order]:
        orders: List[Order] = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        current_position = position

        buy_capacity = limit - current_position
        for ask_price in sorted(order_depth.sell_orders.keys()):
            if ask_price > fair_value - take_width:
                break

            available = -order_depth.sell_orders[ask_price]
            qty = min(available, buy_capacity)

            if qty > 0:
                orders.append(Order(product, ask_price, qty))
                current_position += qty
                buy_capacity -= qty

        sell_capacity = limit + current_position
        for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
            if bid_price < fair_value + take_width:
                break

            available = order_depth.buy_orders[bid_price]
            qty = min(available, sell_capacity)

            if qty > 0:
                orders.append(Order(product, bid_price, -qty))
                current_position -= qty
                sell_capacity -= qty

        buy_capacity = limit - current_position
        sell_capacity = limit + current_position

        skew = inventory_skew_strength * current_position
        reservation_price = fair_value - skew

        bid_quote = min(best_bid + 1, math.floor(reservation_price))
        ask_quote = max(best_ask - 1, math.ceil(reservation_price))

        if bid_quote >= ask_quote:
            bid_quote = min(best_bid, math.floor(fair_value))
            ask_quote = max(best_ask, math.ceil(fair_value))

        if buy_capacity > 0 and bid_quote < best_ask:
            qty = min(passive_size, buy_capacity)
            if qty > 0:
                orders.append(Order(product, bid_quote, qty))

        if sell_capacity > 0 and ask_quote > best_bid:
            qty = min(passive_size, sell_capacity)
            if qty > 0:
                orders.append(Order(product, ask_quote, -qty))

        return orders

    def get_history_window(self, product: str) -> int:
        if product == "TOMATOES":
            return self.TOMATO_WINDOW
        return self.DEFAULT_HISTORY_WINDOW

    def get_mid_price(self, order_depth: OrderDepth) -> float:
        return (
            max(order_depth.buy_orders.keys()) + min(order_depth.sell_orders.keys())
        ) / 2

    def ema(self, values: List[float], alpha: float = 0.4) -> float:
        if not values:
            return 0.0
        estimate = values[0]
        for v in values[1:]:
            estimate = alpha * v + (1 - alpha) * estimate
        return estimate

    def rolling_vol(self, values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
        mean_diff = sum(diffs) / len(diffs)
        var = sum((x - mean_diff) ** 2 for x in diffs) / len(diffs)
        return math.sqrt(var)

    def load_history(self, trader_data: str) -> Dict[str, List[float]]:
        if not trader_data:
            return {}

        try:
            loaded = json.loads(trader_data)
            if isinstance(loaded, dict):
                return loaded
            return {}
        except Exception:
            return {}