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

    def bid(self):
        # Ignored outside Round 2
        return 0

    # NOTE: verify these against the Round 3 position-limits page before the
    # final submission. These are educated guesses based on comparable rounds.
    POSITION_LIMITS: Dict[str, int] = {
        "HYDROGEL_PACK": 50,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 200,
        "VEV_5200": 200,
        "VEV_5300": 200,
        "VEV_5400": 200,
        "VEV_5500": 200,
        "VEV_6000": 200,
        "VEV_6500": 200,
    }

    ACTIVE_PRODUCTS = set(POSITION_LIMITS.keys())

    # Strategy E: which vouchers to systematically short (deep OTM).
    THETA_TARGETS = {"VEV_5500", "VEV_6000", "VEV_6500"}
    # Stop: if current mid exceeds entry mid + THETA_STOP, buy to cover.
    THETA_STOP_PRICE = 15  # cover if voucher mid above this

    # Per-product MM parameters. Fixed-price commodities tolerate more
    # aggressive taking and wider quotes; voucher markets are quieter so
    # we quote smaller and cross less.
    PARAMS: Dict[str, Dict[str, Any]] = {
        "HYDROGEL_PACK": {
            "ema_alpha": 0.40,        # responsive — 16-pt spread jitters
            "quote_size": 15,
            "take_threshold": 3,      # take only when edge ≥ 3
            "max_divergence": 40,     # disable taking if |mid−EMA| > 40
            "crash_divergence": 120,  # flatten if anchor truly breaks
        },
        "VELVETFRUIT_EXTRACT": {
            "ema_alpha": 0.40,
            "quote_size": 20,       # was 25 — smaller passive quote wins on
                                    # trending days (less adverse selection)
            "take_threshold": 1,    # was 2 — tighter take captures more edge
            "max_divergence": 20,
            "crash_divergence": 80,
        },
        # Voucher defaults (any VEV_* that isn't overridden)
        "_VOUCHER": {
            "ema_alpha": 0.40,
            "quote_size": 5,        # was 10 — tight 1–2-wide voucher books
                                    # punish large passive quotes via pickoffs
            "take_threshold": 2,    # was 1 — taking at edge=1 was net-negative
                                    # across days 0/1 on VEV_5200
            "max_divergence": 8,
            "crash_divergence": 30,
        },
    }

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        try:
            return self._run(state)
        except Exception as e:
            logger.print(f"FATAL run() error: {e}")
            try:
                logger.flush(state, {}, 0, state.traderData or "")
            except Exception:
                pass
            return {}, 0, state.traderData or ""

    def _run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}
        conversions = 0

        saved = self._parse_trader_data(state.traderData)
        ema_state: Dict[str, float] = dict(saved.get("ema", {}))
        prev_mid_state: Dict[str, float] = dict(saved.get("prev_mid", {}))

        for product, order_depth in state.order_depths.items():
            if product not in self.ACTIVE_PRODUCTS:
                result[product] = []
                continue

            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS[product]
            params = self._params_for(product)

            # Strategy E: theta-harvest override for deep-OTM vouchers
            if product in self.THETA_TARGETS:
                orders: List[Order] = []
                if order_depth.sell_orders:
                    best_ask = min(order_depth.sell_orders.keys())
                    ask_vol = -order_depth.sell_orders[best_ask]
                    mid_est = best_ask - 0.5  # approx
                    if order_depth.buy_orders:
                        best_bid = max(order_depth.buy_orders.keys())
                        mid_est = (best_bid + best_ask) / 2.0
                    # Panic cover if mid has blown through stop
                    if mid_est > self.THETA_STOP_PRICE and position < 0 and order_depth.sell_orders:
                        remaining = -position
                        for p in sorted(order_depth.sell_orders.keys()):
                            if remaining <= 0:
                                break
                            v = -order_depth.sell_orders[p]
                            q = min(remaining, v)
                            if q > 0:
                                orders.append(Order(product, p, q))
                                remaining -= q
                    else:
                        # Sell at best ask if not at limit (short side of position)
                        sell_capacity = max(0, limit + position)
                        if sell_capacity > 0 and ask_vol > 0:
                            # Sell aggressively against any bid >= 1 to capture premium
                            # Also rest at best ask to harvest pickoffs
                            if order_depth.buy_orders:
                                best_bid = max(order_depth.buy_orders.keys())
                                if best_bid >= 1:
                                    bid_vol = order_depth.buy_orders[best_bid]
                                    q = min(sell_capacity, bid_vol)
                                    if q > 0:
                                        orders.append(Order(product, best_bid, -q))
                                        sell_capacity -= q
                            # Post a sell at best_ask (join the queue)
                            if sell_capacity > 0:
                                orders.append(Order(product, best_ask, -sell_capacity))
                orders = self._clamp_to_position_limit(orders, position, limit)
                result[product] = orders
                continue

            try:
                if not order_depth.buy_orders or not order_depth.sell_orders:
                    result[product] = []
                    continue

                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())
                if best_bid >= best_ask:
                    result[product] = []
                    continue

                mid = (best_bid + best_ask) / 2.0

                # EMA anchor update
                prev_ema = ema_state.get(product)
                alpha = params["ema_alpha"]
                anchor = mid if prev_ema is None else alpha * mid + (1 - alpha) * prev_ema
                ema_state[product] = anchor

                prev_mid = prev_mid_state.get(product)
                prev_mid_state[product] = mid

                logger.print(
                    f"{product} | pos={position} bid={best_bid} ask={best_ask} "
                    f"mid={mid:.2f} ema={anchor:.2f} div={mid-anchor:+.2f}"
                )

                orders = self.mm_orders(
                    product=product,
                    order_depth=order_depth,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    mid=mid,
                    position=position,
                    limit=limit,
                    anchor=anchor,
                    prev_mid=prev_mid,
                    params=params,
                )
            except Exception as e:
                logger.print(f"ERROR in {product}: {e}")
                orders = []

            orders = self._clamp_to_position_limit(orders, position, limit)
            if orders:
                logger.print(
                    f"{product} orders: {[(o.price, o.quantity) for o in orders]}"
                )
            result[product] = orders

        trader_data = json.dumps({
            "ema": ema_state,
            "prev_mid": prev_mid_state,
        })
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    @classmethod
    def _params_for(cls, product: str) -> Dict[str, Any]:
        if product in cls.PARAMS:
            return cls.PARAMS[product]
        return cls.PARAMS["_VOUCHER"]

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

    @staticmethod
    def _clamp_to_position_limit(
        orders: List[Order], position: int, limit: int
    ) -> List[Order]:
        # Independently truncate buy and sell sides so nothing upstream can
        # push net position past ±limit.
        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)
        clamped: List[Order] = []
        remaining_buy = buy_capacity
        remaining_sell = sell_capacity
        for o in orders:
            if o.quantity > 0:
                qty = min(o.quantity, remaining_buy)
                if qty > 0:
                    clamped.append(Order(o.symbol, o.price, qty))
                    remaining_buy -= qty
            elif o.quantity < 0:
                qty = min(-o.quantity, remaining_sell)
                if qty > 0:
                    clamped.append(Order(o.symbol, o.price, -qty))
                    remaining_sell -= qty
        return clamped

    @classmethod
    def mm_orders(
        cls,
        product: str,
        order_depth: OrderDepth,
        best_bid: int,
        best_ask: int,
        mid: float,
        position: int,
        limit: int,
        anchor: float,
        prev_mid: Any,
        params: Dict[str, Any],
    ) -> List[Order]:
        """Fixed-price-style MM with a dynamic EMA anchor instead of a hard-coded one.
        Same three-stage shape as the R2 ASH_COATED_OSMIUM engine:
          1) aggressive taking when prices are past anchor ± threshold
          2) flatten inventory at the anchor
          3) passive quoting inside the effective spread
        """
        orders: List[Order] = []

        take_threshold = params["take_threshold"]
        quote_size = params["quote_size"]
        max_divergence = params["max_divergence"]
        crash_divergence = params["crash_divergence"]

        fair_int = int(round(anchor))

        # Guards
        anchor_divergence_safe = abs(mid - anchor) <= max_divergence
        mid_jumped = (
            isinstance(prev_mid, (int, float))
            and abs(mid - prev_mid) > max(max_divergence, 10)
        )
        take_safe = anchor_divergence_safe and not mid_jumped

        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)
        remaining_buy = buy_capacity
        remaining_sell = sell_capacity

        # Emergency flatten: if the anchor is very wrong, scramble out of
        # inventory and skip new quoting this tick.
        if abs(mid - anchor) > crash_divergence and position != 0:
            if position > 0:
                remaining = min(remaining_sell, position)
                for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if remaining <= 0:
                        break
                    bid_vol = order_depth.buy_orders[bid_price]
                    qty = min(remaining, bid_vol)
                    if qty > 0:
                        orders.append(Order(product, bid_price, -qty))
                        remaining -= qty
            else:
                remaining = min(remaining_buy, -position)
                for ask_price in sorted(order_depth.sell_orders.keys()):
                    if remaining <= 0:
                        break
                    ask_vol = -order_depth.sell_orders[ask_price]
                    qty = min(remaining, ask_vol)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        remaining -= qty
            return orders

        # 1) Aggressive take against the EMA anchor
        if take_safe:
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if remaining_buy <= 0:
                    break
                if ask_price <= anchor - take_threshold:
                    ask_vol = -order_depth.sell_orders[ask_price]
                    qty = min(remaining_buy, ask_vol)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        remaining_buy -= qty
                else:
                    break

            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if remaining_sell <= 0:
                    break
                if bid_price >= anchor + take_threshold:
                    bid_vol = order_depth.buy_orders[bid_price]
                    qty = min(remaining_sell, bid_vol)
                    if qty > 0:
                        orders.append(Order(product, bid_price, -qty))
                        remaining_sell -= qty
                else:
                    break

        # 2) Flatten residual inventory at the anchor if a resting counterparty
        #    is sitting exactly at fair_int.
        effective_position = position + sum(o.quantity for o in orders)
        if effective_position < 0 and remaining_buy > 0:
            if fair_int in order_depth.sell_orders:
                ask_vol = -order_depth.sell_orders[fair_int]
                qty = min(remaining_buy, ask_vol, abs(effective_position))
                if qty > 0:
                    orders.append(Order(product, fair_int, qty))
                    remaining_buy -= qty
                    effective_position += qty
        elif effective_position > 0 and remaining_sell > 0:
            if fair_int in order_depth.buy_orders:
                bid_vol = order_depth.buy_orders[fair_int]
                qty = min(remaining_sell, bid_vol, abs(effective_position))
                if qty > 0:
                    orders.append(Order(product, fair_int, -qty))
                    remaining_sell -= qty
                    effective_position -= qty

        # 3) Passive quoting inside the effective spread.
        # Recompute effective best bid/ask after the taking pass, since levels
        # we lifted are no longer available to rest against.
        effective_best_ask = fair_int + 1
        for ask_lvl in sorted(order_depth.sell_orders.keys()):
            book_vol = -order_depth.sell_orders[ask_lvl]
            bought_at_lvl = sum(
                o.quantity for o in orders if o.quantity > 0 and o.price == ask_lvl
            )
            if bought_at_lvl < book_vol:
                effective_best_ask = ask_lvl
                break

        effective_best_bid = fair_int - 1
        for bid_lvl in sorted(order_depth.buy_orders.keys(), reverse=True):
            book_vol = order_depth.buy_orders[bid_lvl]
            sold_at_lvl = sum(
                -o.quantity for o in orders if o.quantity < 0 and o.price == bid_lvl
            )
            if sold_at_lvl < book_vol:
                effective_best_bid = bid_lvl
                break

        spread = effective_best_ask - effective_best_bid
        if spread >= 2:
            bid_price = effective_best_bid + 1
            ask_price = effective_best_ask - 1
        else:
            bid_price = effective_best_bid
            ask_price = effective_best_ask

        # Never buy above fair or sell below fair.
        bid_price = min(bid_price, effective_best_ask - 1, fair_int)
        ask_price = max(ask_price, effective_best_bid + 1, fair_int)
        if bid_price >= ask_price:
            bid_price = fair_int - 1
            ask_price = fair_int + 1

        passive_safe = anchor_divergence_safe
        passive_buy_qty = min(quote_size, remaining_buy)
        passive_sell_qty = min(quote_size, remaining_sell)

        if passive_safe and passive_buy_qty > 0 and bid_price < fair_int:
            orders.append(Order(product, bid_price, passive_buy_qty))
        if passive_safe and passive_sell_qty > 0 and ask_price > fair_int:
            orders.append(Order(product, ask_price, -passive_sell_qty))

        return orders
