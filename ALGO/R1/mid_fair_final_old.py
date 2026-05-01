
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
    # ACO_ALPHA = 0.02 
    ACO_QUOTE_SIZE = 20
    ACO_TAKE_THRESHOLD = 1 #take price only if price is at least one better than fair
    ACO_MAX_ANCHOR_DIVERGENCE = 50  # disable aggressive taking if |mid - anchor| exceeds this
    ACO_MAX_MID_JUMP = 10  # disable aggressive taking if mid moves more than this in one tick
    ACO_INVENTORY_SKEW = 0.05  # effective take anchor shifts by this*position (mean-reversion)

    IPR_MAX_SPREAD = 40  # skip ticks where book is abnormally wide
    IPR_MAX_CROSS_COST = 10  # refuse to pay more than best_bid + this

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}
        conversions = 0

        prev_state = self._parse_trader_data(state.traderData)
        next_state: Dict[str, Any] = {}

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
                orders, new_fair = self.aco_orders(
                    product=product,
                    order_depth=order_depth,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    position=position,
                    limit=limit,
                    prev_mid=prev_state.get("aco_mid"),
                )
                next_state["aco_mid"] = new_fair
                logger.print(f"{product} fair={new_fair:.2f}")

            if orders:
                logger.print(
                    f"{product} orders: {[(o.price, o.quantity) for o in orders]}"
                )

            result[product] = orders

        trader_data = json.dumps(next_state, separators=(",", ":"))
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    @staticmethod
    def _parse_trader_data(trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {}
        try:
            parsed = json.loads(trader_data)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {}

    @classmethod
    def ipr_orders(
        cls, product: str, best_bid: int, best_ask: int, position: int, limit: int
    ) -> List[Order]:
        orders: List[Order] = []

        # Crossed/locked book — skip
        if best_bid >= best_ask:
            return orders

        spread = best_ask - best_bid

        # Wide-spread gate — regime too uncertain to trade
        if spread > cls.IPR_MAX_SPREAD:
            return orders

        # Price-chase limiter — don't pay a huge premium over best_bid
        if spread > cls.IPR_MAX_CROSS_COST:
            return orders

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
        prev_mid: Any = None,
    ) -> tuple[List[Order], float]:
        orders: List[Order] = []

        mid_price_full = False

        # --- Fair values ---
        anchor = 10000  # known true value for aggressive taking
        mid = (best_bid + best_ask) / 2.0  # current market mid for quoting/flattening
        fair_int = int(round(mid))

        if mid_price_full:
            anchor = fair_int

        # Divergence guard: if market mid has drifted far from the hard anchor,
        # the anchor is likely stale/wrong — disable aggressive taking this tick.
        anchor_divergence_safe = abs(mid - anchor) <= cls.ACO_MAX_ANCHOR_DIVERGENCE

        # Crossed/locked book: best_bid above/at best_ask is malformed — skip taking.
        book_crossed = best_bid >= best_ask

        # Mid-jump guard: a sudden shift vs last tick signals a regime break.
        mid_jumped = (
            isinstance(prev_mid, (int, float))
            and abs(mid - prev_mid) > cls.ACO_MAX_MID_JUMP
        )

        take_safe = anchor_divergence_safe and not book_crossed and not mid_jumped

        # --- Capacity ---
        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)

        remaining_buy = buy_capacity
        remaining_sell = sell_capacity

        # Inventory skew: shift the effective take anchor against current position so
        # the algo demands more edge to add to an already-loaded side.
        skew = cls.ACO_INVENTORY_SKEW * position
        buy_anchor = anchor - skew   # long → lower → pickier about buying
        sell_anchor = anchor - skew  # long → lower → easier to sell

        # --- 1) Aggressive taking (uses skewed anchor) ---
        if take_safe:
            for ask_price in sorted(order_depth.sell_orders.keys()):
                ask_volume = -order_depth.sell_orders[ask_price]
                if ask_price <= buy_anchor - cls.ACO_TAKE_THRESHOLD and remaining_buy > 0:
                    qty = min(remaining_buy, ask_volume)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        remaining_buy -= qty
                else:
                    break

            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                bid_volume = order_depth.buy_orders[bid_price]
                if bid_price >= sell_anchor + cls.ACO_TAKE_THRESHOLD and remaining_sell > 0:
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

        if effective_position < 0 and remaining_buy > 0:
            if anchor in order_depth.sell_orders:
                ask_volume = -order_depth.sell_orders[anchor]
                qty = min(remaining_buy, ask_volume, abs(effective_position))
                if qty > 0:
                    orders.append(Order(product, anchor, qty))
                    remaining_buy -= qty
                    effective_position += qty

        elif effective_position > 0 and remaining_sell > 0:
            if anchor in order_depth.buy_orders:
                bid_volume = order_depth.buy_orders[anchor]
                qty = min(remaining_sell, bid_volume, abs(effective_position))
                if qty > 0:
                    orders.append(Order(product, anchor, -qty))
                    remaining_sell -= qty
                    effective_position -= qty

        # --- 3) Passive quoting (core MM engine) ---
        # Recompute best bid/ask accounting for any levels consumed by aggressive taking
        effective_best_ask = anchor + 1  # fallback if all asks consumed
        for ask_lvl in sorted(order_depth.sell_orders.keys()):
            book_vol = -order_depth.sell_orders[ask_lvl]
            bought_at_lvl = sum(o.quantity for o in orders if o.quantity > 0 and o.price == ask_lvl)
            if bought_at_lvl < book_vol:
                effective_best_ask = ask_lvl
                break

        effective_best_bid = anchor - 1  # fallback if all bids consumed
        for bid_lvl in sorted(order_depth.buy_orders.keys(), reverse=True):
            book_vol = order_depth.buy_orders[bid_lvl]
            sold_at_lvl = sum(-o.quantity for o in orders if o.quantity < 0 and o.price == bid_lvl)
            if sold_at_lvl < book_vol:
                effective_best_bid = bid_lvl
                break

        buy_size = cls.ACO_QUOTE_SIZE
        sell_size = cls.ACO_QUOTE_SIZE

        passive_buy_qty = min(max(buy_size, 0), remaining_buy)
        passive_sell_qty = min(max(sell_size, 0), remaining_sell)

        spread = effective_best_ask - effective_best_bid

        if spread >= 2:
            bid_price = effective_best_bid + 1
            ask_price = effective_best_ask - 1
        else:
            bid_price = effective_best_bid
            ask_price = effective_best_ask

        # Safety clamps — never buy at/above anchor or sell at/below anchor
        bid_price = min(bid_price, effective_best_ask - 1, anchor - 1)
        ask_price = max(ask_price, effective_best_bid + 1, anchor + 1)

        if bid_price >= ask_price:
            bid_price = anchor - 1
            ask_price = anchor + 1

        if passive_buy_qty > 0 and bid_price < anchor:
            orders.append(Order(product, bid_price, passive_buy_qty))

        if passive_sell_qty > 0 and ask_price > anchor:
            orders.append(Order(product, ask_price, -passive_sell_qty))

        return orders, mid