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
    ACO_QUOTE_SIZE = 20
    ACO_ALPHA = 0.01          # EMA smoothing factor for dynamic fair value anchor
    ACO_TAKE_THRESHOLD = 3    # take only if price is at least this many ticks better than anchor
    ACO_MAX_ANCHOR_DIVERGENCE = 50  # disable aggressive taking if |mid - anchor| exceeds this
    ACO_MAX_MID_JUMP = 100    # (effectively disabled — σ=5, so jump>10 happens only during real alpha)
    # Two indicators from 6-day R1+R2 regression (joint R²=0.44 predicting Δmid@+5):
    #   OFI_top  (corr +0.65 → coef ~+4.1)
    #   Raw mid deviation from μ_eq=10000  (corr -0.62 → coef ~-0.17 in raw scale)
    ACO_OFI_COEF = 1.0
    ACO_MR_COEF = 0.25
    ACO_TILT_CLIP = 3

    # IPR parameters
    IPR_RAMP_START = 4        # offset when on/ahead of position-vs-time schedule
    IPR_RAMP_MAX = 15         # offset when fully behind schedule
    IPR_RAMP_FULL_BY = 1000   # timestamp by which we expect position = limit
    IPR_TREND_PER_TICK = 0.001  # linear price trend
    IPR_MAX_SPREAD = 40       # skip ticks where book is abnormally wide
    IPR_DRAWDOWN_HALT = 50    # halt buying if mid drops more than this below predicted fair
    IPR_TRAILING_STOP = 300   # flatten position if mid falls this far below session high

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

        # Load persisted state
        saved = self._parse_trader_data(state.traderData)
        ipr_base = saved.get("ipr_base", None)
        aco_prev_mid = saved.get("aco_mid", None)
        aco_ema = saved.get("aco_ema", None)  # EMA-based dynamic anchor

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

                    ipr_fair = ipr_base + state.timestamp * self.IPR_TREND_PER_TICK
                    orders = self.ipr_orders(
                        product, order_depth, best_bid, position, limit, ipr_fair, state.timestamp
                    )
                    logger.print(f"{product} fair={ipr_fair:.2f}")

                elif product == "ASH_COATED_OSMIUM":
                    orders, new_fair, aco_ema = self.aco_orders(
                        product=product,
                        order_depth=order_depth,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        position=position,
                        limit=limit,
                        prev_mid=aco_prev_mid,
                        ema=aco_ema,
                    )
                    aco_prev_mid = new_fair
                    logger.print(f"{product} fair={new_fair:.2f} ema={aco_ema:.2f}")
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

        trader_data = json.dumps({"ipr_base": ipr_base, "aco_mid": aco_prev_mid, "aco_ema": aco_ema})
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
    ) -> List[Order]:
        orders: List[Order] = []

        best_ask = min(order_depth.sell_orders.keys())

        if best_bid >= best_ask:
            return orders

        spread = best_ask - best_bid

        if spread > cls.IPR_MAX_SPREAD:
            return orders

        mid = (best_bid + best_ask) / 2.0
        if mid < fair - cls.IPR_DRAWDOWN_HALT:
            return orders

        remaining = limit - position

        target = min(limit, limit * timestamp / cls.IPR_RAMP_FULL_BY)
        deficit = max(0, target - position)
        offset = cls.IPR_RAMP_START + deficit * (cls.IPR_RAMP_MAX - cls.IPR_RAMP_START) / limit
        threshold = fair + offset

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
        ema: Any = None,
    ) -> tuple[List[Order], float, float]:
        orders: List[Order] = []

        # --- Fair values ---
        mid = (best_bid + best_ask) / 2.0
        # EMA-based anchor: slow-moving fair value, persisted across ticks
        if ema is None:
            ema = mid
        ema = cls.ACO_ALPHA * mid + (1.0 - cls.ACO_ALPHA) * ema

        # Two-indicator forecast tilt (OFI + mean-reversion to μ_eq=10000)
        bv1 = order_depth.buy_orders.get(best_bid, 0)
        av1 = -order_depth.sell_orders.get(best_ask, 0)
        tot = bv1 + av1
        ofi = (bv1 - av1) / tot if tot > 0 else 0.0
        tilt = cls.ACO_OFI_COEF * ofi - cls.ACO_MR_COEF * (mid - 10000)
        if tilt > cls.ACO_TILT_CLIP: tilt = cls.ACO_TILT_CLIP
        elif tilt < -cls.ACO_TILT_CLIP: tilt = -cls.ACO_TILT_CLIP

        anchor = int(round(ema + tilt))
        fair_int = int(round(mid + tilt))

        anchor_divergence_safe = abs(mid - anchor) <= cls.ACO_MAX_ANCHOR_DIVERGENCE
        book_crossed = best_bid >= best_ask
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

        # --- 1) Aggressive taking (uses EMA anchor) ---
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

        # --- 2) Inventory flattening at anchor (extended to anchor±1) ---
        effective_position = position
        for o in orders:
            effective_position += o.quantity

        if effective_position < 0 and remaining_buy > 0:
            # Short: buy back at anchor, then anchor-1 (cheaper)
            for buy_lvl in [anchor, anchor - 1]:
                if remaining_buy <= 0 or effective_position >= 0:
                    break
                if buy_lvl in order_depth.sell_orders:
                    ask_volume = -order_depth.sell_orders[buy_lvl]
                    qty = min(remaining_buy, ask_volume, abs(effective_position))
                    if qty > 0:
                        orders.append(Order(product, buy_lvl, qty))
                        remaining_buy -= qty
                        effective_position += qty

        elif effective_position > 0 and remaining_sell > 0:
            # Long: sell at anchor, then anchor+1 (better price)
            for sell_lvl in [anchor, anchor + 1]:
                if remaining_sell <= 0 or effective_position <= 0:
                    break
                if sell_lvl in order_depth.buy_orders:
                    bid_volume = order_depth.buy_orders[sell_lvl]
                    qty = min(remaining_sell, bid_volume, abs(effective_position))
                    if qty > 0:
                        orders.append(Order(product, sell_lvl, -qty))
                        remaining_sell -= qty
                        effective_position -= qty

        # --- 3) Passive quoting (core MM engine) ---
        effective_best_ask = fair_int + 1
        for ask_lvl in sorted(order_depth.sell_orders.keys()):
            book_vol = -order_depth.sell_orders[ask_lvl]
            bought_at_lvl = sum(o.quantity for o in orders if o.quantity > 0 and o.price == ask_lvl)
            if bought_at_lvl < book_vol:
                effective_best_ask = ask_lvl
                break

        effective_best_bid = fair_int - 1
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

        if passive_buy_qty > 0 and bid_price < fair_int:
            orders.append(Order(product, bid_price, passive_buy_qty))

        if passive_sell_qty > 0 and ask_price > fair_int:
            orders.append(Order(product, ask_price, -passive_sell_qty))

        return orders, mid, ema