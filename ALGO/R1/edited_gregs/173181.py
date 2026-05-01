# Greg most recent, Nicholas update/testing
'''
EDITS made:
1. Only take from the market when we are actually making money compared to the fair (1)
2. If we are tilted toward a certain position (long, short) - unwind by taking fair value.
3. Even once we take a good bid, still passively quote.
+ 3k PNL



'''


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
        self, order_depths: dict[Symbol, OrderDepth]
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
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # Tuned (safe) parameters
    ACO_ALPHA = 0.02 
    ACO_QUOTE_SIZE = 15
    ACO_TAKE_THRESHOLD = 1 #take price only if price is at least one better than fair

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}
        conversions = 0

        fair_values = self.load_fair_values(state.traderData)

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 80)

            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())

            logger.print(
                f"{product} | pos={position} | best_bid={best_bid} | best_ask={best_ask}"
            )

            if product == "INTARIAN_PEPPER_ROOT":
                orders = self.ipr_orders(product, best_bid, best_ask, position, limit)

            elif product == "ASH_COATED_OSMIUM":
                prev_fair = fair_values.get(product)
                orders, new_fair = self.aco_orders(
                    product=product,
                    order_depth=order_depth,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    position=position,
                    limit=limit,
                    prev_fair=prev_fair,
                )
                fair_values[product] = new_fair
                logger.print(f"{product} fair={new_fair:.2f}")

            if orders:
                logger.print(
                    f"{product} orders: {[(o.price, o.quantity) for o in orders]}"
                )

            result[product] = orders

        trader_data = json.dumps(fair_values)
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    @staticmethod
    def load_fair_values(trader_data: str) -> Dict[str, float]:
        if not trader_data:
            return {}
        try:
            parsed = json.loads(trader_data)
            if isinstance(parsed, dict):
                return {k: float(v) for k, v in parsed.items()}
        except Exception:
            pass
        return {}

    @staticmethod
    def ipr_orders(
        product: str, best_bid: int, best_ask: int, position: int, limit: int
    ) -> List[Order]:
        orders: List[Order] = []
        buy_qty = limit - position

        if buy_qty > 0:
            orders.append(Order(product, best_ask, buy_qty))

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
        prev_fair: float | None,
    ) -> tuple[List[Order], float]:
        orders: List[Order] = []
        # --- Fair value (EMA) ---
        mid = (best_bid + best_ask) / 2.0
        if prev_fair is None:
            fair = mid
        else:
            fair = cls.ACO_ALPHA * mid + (1.0 - cls.ACO_ALPHA) * prev_fair

        # --- Capacity ---
        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)

        remaining_buy = buy_capacity
        remaining_sell = sell_capacity

        # --- 1) Aggressive taking (core alpha) ---
        for ask_price in sorted(order_depth.sell_orders.keys()):
            ask_volume = -order_depth.sell_orders[ask_price]
            if ask_price <= fair - cls.ACO_TAKE_THRESHOLD and remaining_buy > 0:
                qty = min(remaining_buy, ask_volume)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    remaining_buy -= qty
            else:
                break

        for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
            bid_volume = order_depth.buy_orders[bid_price]
            if bid_price >= fair + cls.ACO_TAKE_THRESHOLD and remaining_sell > 0:
                qty = min(remaining_sell, bid_volume)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    remaining_sell -= qty
            else:
                break

        # --- 2) Inventory flattening at fair value ---
        effective_position = position
        for o in orders:
            effective_position += o.quantity

        fair_int = int(round(fair))

        if effective_position < 0 and remaining_buy > 0:
            if fair_int in order_depth.sell_orders:
                ask_volume = -order_depth.sell_orders[fair_int]
                qty = min(remaining_buy, ask_volume, abs(effective_position))
                if qty > 0:
                    orders.append(Order(product, fair_int, qty))
                    remaining_buy -= qty
                    effective_position += qty

        elif effective_position > 0 and remaining_sell > 0:
            if fair_int in order_depth.buy_orders:
                bid_volume = order_depth.buy_orders[fair_int]
                qty = min(remaining_sell, bid_volume, abs(effective_position))
                if qty > 0:
                    orders.append(Order(product, fair_int, -qty))
                    remaining_sell -= qty
                    effective_position -= qty

        # --- 3) Passive quoting (core MM engine) ---
        # Recompute best bid/ask in case we consumed the level at fair
        effective_best_bid = best_bid
        effective_best_ask = best_ask

        if fair_int >= best_ask:
            for ask_lvl in sorted(order_depth.sell_orders.keys()):
                book_vol = -order_depth.sell_orders[ask_lvl]
                bought_at_lvl = sum(o.quantity for o in orders if o.quantity > 0 and o.price == ask_lvl)
                if bought_at_lvl < book_vol:
                    effective_best_ask = ask_lvl
                    break
            else:
                # All ask levels fully consumed — fall back to fair + 1 so passive quote has room
                effective_best_ask = fair_int + 1

        if fair_int <= best_bid:
            for bid_lvl in sorted(order_depth.buy_orders.keys(), reverse=True):
                book_vol = order_depth.buy_orders[bid_lvl]
                sold_at_lvl = sum(-o.quantity for o in orders if o.quantity < 0 and o.price == bid_lvl)
                if sold_at_lvl < book_vol:
                    effective_best_bid = bid_lvl
                    break
            else:
                effective_best_bid = fair_int - 1

        passive_buy_qty = min(cls.ACO_QUOTE_SIZE, remaining_buy)
        passive_sell_qty = min(cls.ACO_QUOTE_SIZE, remaining_sell)

        spread = effective_best_ask - effective_best_bid

        if spread >= 2:
            bid_price = effective_best_bid + 1
            ask_price = effective_best_ask - 1
        else:
            bid_price = effective_best_bid
            ask_price = effective_best_ask

        # Safety clamps — never buy above fair or sell below fair
        bid_price = min(bid_price, effective_best_ask - 1, fair_int)
        ask_price = max(ask_price, effective_best_bid + 1, fair_int)

        if bid_price >= ask_price:
            bid_price = fair_int - 1
            ask_price = fair_int + 1

        # --- Place orders — skip any side that lands at fair (no edge) ---
        if passive_buy_qty > 0 and bid_price < fair_int:
            orders.append(Order(product, bid_price, passive_buy_qty))

        if passive_sell_qty > 0 and ask_price > fair_int:
            orders.append(Order(product, ask_price, -passive_sell_qty))

        return orders, fair