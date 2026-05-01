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
    ACO_ANCHOR = 10000
    ACO_TAKE_THRESHOLD = 1
    ACO_BASE_QUOTE_SIZE = 15
    ACO_AGGRESSIVE_SIZE = 25       # max qty for signal-driven spread crossing
    ACO_WIDE_SPREAD = 4
    ACO_MR_COEF = 0.5              # AC(1) ≈ −0.5 → shift quotes by half the last move
    ACO_IMBALANCE_THRESHOLD = 0.15 # min |imbalance| to generate OB signal

    # IPR parameters
    IPR_SWEEP_OFFSET = 5
    IPR_LARGE_DIP_THRESHOLD = 3
    IPR_LARGE_DIP_OFFSET = 8
    IPR_UP_MOVE_FRACTION = 0.25
    IPR_FLAT_FRACTION = 0.50

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
                best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
                best_ask = min(order_depth.sell_orders)
                mid = ((best_bid + best_ask) / 2.0) if best_bid else float(best_ask)
                ipr_prev = prev.get("ipr_prev_mid")
                orders = self.ipr_orders(product, order_depth, position, limit, ipr_prev)
                next_state["ipr_prev_mid"] = mid

            elif product == "ASH_COATED_OSMIUM":
                if not order_depth.buy_orders or not order_depth.sell_orders:
                    result[product] = orders
                    continue
                best_bid = max(order_depth.buy_orders)
                best_ask = min(order_depth.sell_orders)
                aco_prev = prev.get("aco_prev_mid")
                orders, mid = self.aco_orders(
                    product, order_depth, best_bid, best_ask, position, limit, aco_prev
                )
                next_state["aco_prev_mid"] = mid

            result[product] = orders

        trader_data = json.dumps(next_state)
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    # ── state persistence ──────────────────────────────────────────────

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

    # ── ACO signals ────────────────────────────────────────────────────

    @staticmethod
    def _aco_return_signal(mid: float, prev_mid: float | None) -> int:
        """Lag-1 return reversal. AC(1) ≈ -0.49 → bet against last move."""
        if prev_mid is None:
            return 0
        last_return = mid - prev_mid
        if last_return > 0:
            return -1  # was up → expect down
        elif last_return < 0:
            return +1  # was down → expect up
        return 0

    @classmethod
    def _aco_imbalance_signal(cls, order_depth: OrderDepth) -> int:
        """OB imbalance at best level. Corr ≈ -0.66 (counter-intuitive)."""
        best_bid = max(order_depth.buy_orders)
        best_ask = min(order_depth.sell_orders)
        bid_vol = order_depth.buy_orders[best_bid]
        ask_vol = -order_depth.sell_orders[best_ask]
        total = bid_vol + ask_vol
        if total == 0:
            return 0
        imbalance = (bid_vol - ask_vol) / total
        if imbalance < -cls.ACO_IMBALANCE_THRESHOLD:
            return +1  # ask-heavy → price goes UP
        elif imbalance > cls.ACO_IMBALANCE_THRESHOLD:
            return -1  # bid-heavy → price goes DOWN
        return 0

    @staticmethod
    def _aco_combined(ret_sig: int, imb_sig: int) -> tuple[int, float]:
        """Combine signals into (direction, confidence)."""
        if ret_sig == 0 and imb_sig == 0:
            return 0, 0.0
        if ret_sig != 0 and imb_sig != 0:
            if ret_sig == imb_sig:
                return ret_sig, 1.0   # both agree → high confidence
            else:
                return 0, 0.0         # conflicting → stay neutral
        if ret_sig != 0:
            return ret_sig, 0.6       # return signal alone
        return imb_sig, 0.5           # imbalance alone

    # ── ACO order generation ───────────────────────────────────────────

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

        anchor = cls.ACO_ANCHOR
        mid = (best_bid + best_ask) / 2.0
        fair_int = int(round(mid))

        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)
        remaining_buy = buy_capacity
        remaining_sell = sell_capacity

        # ── 1) Aggressive take at anchor ───────────────────────────────
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

        # ── 2) Signal-driven aggressive crossing ──────────────────────
        ret_sig = cls._aco_return_signal(mid, prev_mid)
        imb_sig = cls._aco_imbalance_signal(order_depth)
        direction, confidence = cls._aco_combined(ret_sig, imb_sig)

        effective_position = position + sum(o.quantity for o in orders)

        # Signal-driven crossing disabled: ACO spread (~16 ticks) exceeds the
        # expected reversal magnitude (~5 ticks), so crossing is net negative.
        # The signal is still used below to bias passive quote sizing and placement.

        # ── 3) Flatten at anchor ──────────────────────────────────────
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

        # ── 4) Recompute effective top-of-book ────────────────────────
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

        # ── 5) Inventory-aware passive sizing with signal bias ────────
        pos_ratio = abs(effective_position) / limit
        dampened = max(0.0, 1.0 - pos_ratio * 1.25)

        if effective_position > 0:
            base_buy = int(cls.ACO_BASE_QUOTE_SIZE * dampened)
            base_sell = cls.ACO_BASE_QUOTE_SIZE
        elif effective_position < 0:
            base_buy = cls.ACO_BASE_QUOTE_SIZE
            base_sell = int(cls.ACO_BASE_QUOTE_SIZE * dampened)
        else:
            base_buy = cls.ACO_BASE_QUOTE_SIZE
            base_sell = cls.ACO_BASE_QUOTE_SIZE

        # Bias sizing toward predicted direction
        if direction == +1 and confidence > 0:
            passive_buy_qty = int(base_buy * (1.0 + confidence * 0.5))
            passive_sell_qty = int(base_sell * (1.0 - confidence * 0.5))
        elif direction == -1 and confidence > 0:
            passive_buy_qty = int(base_buy * (1.0 - confidence * 0.5))
            passive_sell_qty = int(base_sell * (1.0 + confidence * 0.5))
        else:
            passive_buy_qty = base_buy
            passive_sell_qty = base_sell

        passive_buy_qty = min(passive_buy_qty, remaining_buy)
        passive_sell_qty = min(passive_sell_qty, remaining_sell)

        # ── 6) Quote placement ────────────────────────────────────────
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

        # Inventory skew
        skew = round(effective_position / limit * 2)
        bid_price -= skew
        ask_price -= skew

        # Mean-reversion shift from last tick
        if prev_mid is not None:
            mr_shift = round(cls.ACO_MR_COEF * (mid - prev_mid))
            bid_price -= mr_shift
            ask_price -= mr_shift

        # Safety clamps
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

    # ── IPR order generation ───────────────────────────────────────────

    @classmethod
    def ipr_orders(
        cls,
        product: str,
        order_depth: OrderDepth,
        position: int,
        limit: int,
        prev_mid: float | None,
    ) -> List[Order]:
        orders: List[Order] = []
        buy_capacity = limit - position
        if buy_capacity <= 0:
            return orders

        best_ask = min(order_depth.sell_orders)
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else best_ask - 1

        # First tick — no signal, buy aggressively (don't miss the uptrend)
        if prev_mid is None:
            orders.append(Order(product, best_ask + cls.IPR_SWEEP_OFFSET, buy_capacity))
            return orders

        mid = ((best_bid + best_ask) / 2.0) if order_depth.buy_orders else float(best_ask)
        last_return = mid - prev_mid

        if last_return < -cls.IPR_LARGE_DIP_THRESHOLD:
            # Large dip — sweep extra wide, full capacity
            orders.append(Order(product, best_ask + cls.IPR_LARGE_DIP_OFFSET, buy_capacity))

        elif last_return < 0:
            # Normal dip — sweep aggressively, full capacity
            orders.append(Order(product, best_ask + cls.IPR_SWEEP_OFFSET, buy_capacity))

        elif last_return == 0:
            # Flat — buy at ask with half capacity
            qty = max(1, int(buy_capacity * cls.IPR_FLAT_FRACTION))
            orders.append(Order(product, best_ask, qty))

        else:
            # Up move — passive bid with quarter capacity (expect pullback)
            qty = max(1, int(buy_capacity * cls.IPR_UP_MOVE_FRACTION))
            orders.append(Order(product, best_bid + 1, qty))

        return orders
