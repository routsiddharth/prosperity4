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
        return 1500

    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # Tuned (safe) parameters
    ACO_QUOTE_SIZE = 20
    ACO_TAKE_THRESHOLD = 5 #take price only if price is at least one better than fair
    ACO_MAX_ANCHOR_DIVERGENCE = 50  # disable aggressive taking if |mid - anchor| exceeds this
    ACO_MAX_MID_JUMP = 15  # disable aggressive taking if mid moves more than this in one tick
    ACO_PASSIVE_DIVERGENCE = 50  # disable passive quoting when |mid - anchor| exceeds this
    ACO_CRASH_DIVERGENCE = 100  # |mid - anchor| beyond which anchor is broken → emergency flatten

    # IPR parameters
    IPR_RAMP_START = 4  # offset when on/ahead of position-vs-time schedule
    IPR_RAMP_MAX = 15  # offset when fully behind schedule
    IPR_RAMP_FULL_BY = 1000  # timestamp by which we expect position = limit
    IPR_TREND_PER_TICK = 0.001  # linear price trend
    IPR_MAX_SPREAD = 40  # skip ticks where book is abnormally wide
    IPR_DRAWDOWN_HALT = 50  # halt buying if mid drops more than this below predicted fair
    IPR_TRAILING_STOP = 300  # flatten position if mid falls this far below session high
    IPR_MAX_DOWN_JUMP = 25  # skip buying this tick if mid drops more than this in one tick (upward jumps are fine — we buy-and-hold)

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        try:
            return self._run(state)
        except Exception as e:
            # Absolute last resort: preserve prior traderData so state isn't lost.
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

        # Load persisted state
        saved = self._parse_trader_data(state.traderData)
        ipr_base = saved.get("ipr_base", None)
        ipr_hwm = saved.get("ipr_hwm", None)
        ipr_stop_triggered = bool(saved.get("ipr_stop_triggered", False))
        ipr_prev_mid = saved.get("ipr_mid", None)
        aco_prev_mid = saved.get("aco_mid", None)

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 80)

            try:
                if not order_depth.buy_orders or not order_depth.sell_orders:
                    result[product] = orders
                    continue

                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())

                logger.print(
                    f"{product} | pos={position} | best_bid={best_bid} | best_ask={best_ask}"
                )

                if product == "INTARIAN_PEPPER_ROOT":
                    mid = (best_bid + best_ask) / 2.0
                    if ipr_base is None:
                        ipr_base = mid - state.timestamp * self.IPR_TREND_PER_TICK

                    # Trailing-stop machinery. HWM only ratchets up; stop is sticky
                    # once fired so a dead-cat bounce can't re-arm accumulation.
                    if ipr_hwm is None or mid > ipr_hwm:
                        ipr_hwm = mid
                    if (
                        not ipr_stop_triggered
                        and ipr_hwm - mid > self.IPR_TRAILING_STOP
                    ):
                        ipr_stop_triggered = True
                        logger.print(
                            f"{product} TRAILING STOP TRIGGERED | hwm={ipr_hwm} mid={mid}"
                        )

                    # Single-tick downward-jump gate. Upward jumps are fine — we
                    # buy-and-hold, so a rally is good news. A sudden drop below
                    # the drawdown-halt threshold would miss the halt entirely
                    # for one tick, so catch it here.
                    down_jumped = (
                        isinstance(ipr_prev_mid, (int, float))
                        and (ipr_prev_mid - mid) > self.IPR_MAX_DOWN_JUMP
                    )
                    if down_jumped:
                        logger.print(
                            f"{product} DOWN JUMP | prev_mid={ipr_prev_mid} mid={mid}"
                        )

                    ipr_fair = ipr_base + state.timestamp * self.IPR_TREND_PER_TICK
                    orders, ipr_deficit = self.ipr_orders(
                        product, order_depth, best_bid, position, limit, ipr_fair,
                        state.timestamp, ipr_stop_triggered, down_jumped,
                    )
                    ipr_prev_mid = mid
                    logger.print(
                        f"{product} fair={ipr_fair:.2f} deficit={ipr_deficit:.2f} "
                        f"hwm={ipr_hwm} stop={ipr_stop_triggered}"
                    )

                elif product == "ASH_COATED_OSMIUM":
                    orders, new_fair = self.aco_orders(
                        product=product,
                        order_depth=order_depth,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        position=position,
                        limit=limit,
                        prev_mid=aco_prev_mid,
                    )
                    aco_prev_mid = new_fair
                    logger.print(f"{product} fair={new_fair:.2f}")
            except Exception as e:
                logger.print(f"ERROR in {product}: {e}")
                orders = []

            # Defensive: guarantee we never exceed position limits regardless of bugs.
            orders = self._clamp_to_position_limit(orders, position, limit)

            if orders:
                logger.print(
                    f"{product} orders: {[(o.price, o.quantity) for o in orders]}"
                )

            result[product] = orders

        trader_data = json.dumps({
            "ipr_base": ipr_base,
            "ipr_hwm": ipr_hwm,
            "ipr_stop_triggered": ipr_stop_triggered,
            "ipr_mid": ipr_prev_mid,
            "aco_mid": aco_prev_mid,
        })
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

    @staticmethod
    def _clamp_to_position_limit(
        orders: List[Order], position: int, limit: int
    ) -> List[Order]:
        # Independently truncate buy and sell sides so a bug upstream cannot
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
    def ipr_orders(
        cls,
        product: str,
        order_depth: OrderDepth,
        best_bid: int,
        position: int,
        limit: int,
        fair: float,
        timestamp: int,
        stop_triggered: bool = False,
        down_jumped: bool = False,
    ) -> tuple[List[Order], float]:
        orders: List[Order] = []

        target = min(limit, limit * timestamp / cls.IPR_RAMP_FULL_BY)
        deficit = max(0.0, target - position)

        best_ask = min(order_depth.sell_orders.keys())

        # Crossed/locked book — malformed, skip
        if best_bid >= best_ask:
            return orders, deficit

        # Emergency flatten: trailing stop fired. Cross the spread to exit long
        # regardless of spread width or drawdown — getting out dominates edge.
        if stop_triggered:
            if position > 0:
                remaining_sell = position
                for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if remaining_sell <= 0:
                        break
                    bid_vol = order_depth.buy_orders[bid_price]
                    qty = min(remaining_sell, bid_vol)
                    if qty > 0:
                        orders.append(Order(product, bid_price, -qty))
                        remaining_sell -= qty
            return orders, deficit

        # Single-tick downward-jump gate: skip all buying this tick (both ask
        # lifting and the passive resting bid). Hold current position — don't
        # flatten — since we're a buy-and-hold strategy and the drop may be noise.
        if down_jumped:
            return orders, deficit

        spread = best_ask - best_bid

        # Wide-spread gate — regime too uncertain to trade
        if spread > cls.IPR_MAX_SPREAD:
            return orders, deficit

        # Drawdown halt — stop accumulating if market has fallen materially below fair
        mid = (best_bid + best_ask) / 2.0
        if mid < fair - cls.IPR_DRAWDOWN_HALT:
            return orders, deficit

        remaining = limit - position

        offset = cls.IPR_RAMP_START + deficit * (cls.IPR_RAMP_MAX - cls.IPR_RAMP_START) / limit
        threshold = fair + offset

        # Lift asks that are at or below fair + offset
        for ask_price in sorted(order_depth.sell_orders.keys()):
            if remaining <= 0:
                break
            if ask_price > threshold:
                break
            ask_vol = -order_depth.sell_orders[ask_price]
            qty = min(remaining, ask_vol)
            if qty > 0:
                orders.append(Order(product, ask_price, qty))
                remaining -= qty

        # Passive resting bid at floor(fair) for any leftover buy capacity
        if remaining > 0:
            orders.append(Order(product, int(fair), remaining))

        return orders, deficit

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

        # --- Fair values ---
        anchor = 10001 # known true value for aggressive taking
        mid = (best_bid + best_ask) / 2.0  # current market mid for quoting/flattening
        fair_int = int(round(mid))

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

        # --- Emergency flatten: anchor is broken. Stop all MM activity and exit. ---
        # When |mid - anchor| exceeds the crash threshold, the anchor is no longer
        # a trustworthy fair value. Cross the spread aggressively to exit inventory
        # in whichever direction reduces position, and skip both the anchor-based
        # flatten and passive quoting for this tick.
        if abs(mid - anchor) > cls.ACO_CRASH_DIVERGENCE and position != 0:
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
            return orders, mid

        # --- 1) Aggressive taking (uses anchor) ---
        if take_safe:
            for ask_price in sorted(order_depth.sell_orders.keys()):
                ask_volume = -order_depth.sell_orders[ask_price]
                if ask_price <= anchor - cls.ACO_TAKE_THRESHOLD and remaining_buy > 0:
                    qty = min(remaining_buy, ask_volume)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        remaining_buy -= qty
                else:
                    break

            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                bid_volume = order_depth.buy_orders[bid_price]
                if bid_price >= anchor + cls.ACO_TAKE_THRESHOLD and remaining_sell > 0:
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
        effective_best_ask = fair_int + 1  # fallback if all asks consumed
        for ask_lvl in sorted(order_depth.sell_orders.keys()):
            book_vol = -order_depth.sell_orders[ask_lvl]
            bought_at_lvl = sum(o.quantity for o in orders if o.quantity > 0 and o.price == ask_lvl)
            if bought_at_lvl < book_vol:
                effective_best_ask = ask_lvl
                break

        effective_best_bid = fair_int - 1  # fallback if all bids consumed
        for bid_lvl in sorted(order_depth.buy_orders.keys(), reverse=True):
            book_vol = order_depth.buy_orders[bid_lvl]
            sold_at_lvl = sum(-o.quantity for o in orders if o.quantity < 0 and o.price == bid_lvl)
            if sold_at_lvl < book_vol:
                effective_best_bid = bid_lvl
                break

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

        # Divergence gate on passive quoting: if anchor divergence is severe
        # enough to disable taking, also suppress liquidity provision — otherwise
        # we become the only counterparty into a dislocating market.
        passive_safe = abs(mid - anchor) <= cls.ACO_PASSIVE_DIVERGENCE

        if passive_safe and passive_buy_qty > 0 and bid_price < fair_int:
            orders.append(Order(product, bid_price, passive_buy_qty))

        if passive_safe and passive_sell_qty > 0 and ask_price > fair_int:
            orders.append(Order(product, ask_price, -passive_sell_qty))

        return orders, mid