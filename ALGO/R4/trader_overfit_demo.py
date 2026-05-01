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
    """SKEPTIC variant.

    Identical to baseline `trader.py` except for ONE narrow guard:
    a generic informed-counterparty filter that DAMPENS aggressive
    short-premium TAKE-fills on vouchers when the counterparty we'd
    be hitting has shown an extreme directional-flow profile in that
    product across the session so far (>=MIN_OBS observations and
    |net|/total >= IMBALANCE_TH). Names are NOT hardcoded.

    Specifically: when we initiate a short-premium SELL via crossing
    the best bid on a voucher, if the dominant counterparty placing
    bids in that product has a strongly NET-SELL profile (i.e. their
    one-sided flow is to sell — they win when the underlying stays
    OTM), we skip the take. Otherwise we behave exactly like baseline.

    This is a SAFETY filter, not an aggression multiplier.
    """

    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300,
        "VEV_5300": 300,
        "VEV_5400": 300,
        "VEV_5500": 300,
        "VEV_6000": 300,
        "VEV_6500": 300,
    }

    HYDROGEL = "HYDROGEL_PACK"
    HYDROGEL_BASE_FAIR = 9992
    HYDROGEL_QUOTE_SIZE = 25
    HYDROGEL_TAKE_SIZE = 25
    HYDROGEL_TAKE_WIDTH = 8
    HYDROGEL_PASSIVE_EDGE = 1
    HYDROGEL_INVENTORY_SKEW = 23
    HYDROGEL_IMBALANCE_SKEW = 32
    HYDROGEL_INV_TAKE_THROTTLE_EXP = 2
    HYDROGEL_INVENTORY_SKEW_QUAD = 12
    HYDROGEL_NEAR_FAIR_ZONE = 4
    HYDROGEL_NEAR_FAIR_PASSIVE_EDGE = 2
    HYDROGEL_FLATTEN_THRESHOLD = 182
    HYDROGEL_FLATTEN_SIZE = 8
    HYDROGEL_EXTREME_DISTANCE = 50
    HYDROGEL_NORMAL_BASE_WEIGHT = 0.75
    HYDROGEL_NORMAL_MID_WEIGHT = 0.25
    HYDROGEL_EXTREME_BASE_WEIGHT = 0.65
    HYDROGEL_EXTREME_MID_WEIGHT = 0.35

    EXTRACT = "VELVETFRUIT_EXTRACT"
    EXTRACT_BASE_FAIR = 5250
    EXTRACT_QUOTE_SIZE = 20
    EXTRACT_TAKE_SIZE = 6
    EXTRACT_TAKE_WIDTH = 6
    EXTRACT_PASSIVE_EDGE = 1
    EXTRACT_INVENTORY_SKEW = 10
    EXTRACT_IMBALANCE_SKEW = -5
    EXTRACT_NEAR_FAIR_ZONE = 6
    EXTRACT_NEAR_FAIR_PASSIVE_EDGE = 4
    EXTRACT_FLATTEN_THRESHOLD = 180
    EXTRACT_FLATTEN_SIZE = 5
    EXTRACT_EXTREME_DISTANCE = 35
    EXTRACT_NORMAL_BASE_WEIGHT = 0.70
    EXTRACT_NORMAL_MID_WEIGHT = 0.30
    EXTRACT_EXTREME_BASE_WEIGHT = 0.80
    EXTRACT_EXTREME_MID_WEIGHT = 0.20

    VEV4000 = "VEV_4000"
    VEV4000_STRIKE = 4000
    PREMIUM_ALPHA_4000 = 0.10
    V4000_MIN_SPREAD = 8
    V4000_QUOTE_EDGE = 2
    V4000_TAKE_EDGE = 5
    V4000_BASE_QTY = 10
    V4000_TAKE_QTY = 12
    V4000_SKEW_START = 25
    V4000_SKEW_FULL = 65

    OPTION = "VEV_5300"
    STRIKE = 5300
    SELL_THRESHOLD = 53.0
    STRONG_SELL_THRESHOLD = 59.0
    COVER_THRESHOLD = 43.0
    NORMAL_SELL_SIZE = 25
    STRONG_SELL_SIZE = 50
    COVER_SIZE = 25
    MAX_SHORT_5300 = -300
    BLOCK_SELL_IMBALANCE = 0.20

    V5400 = "VEV_5400"
    V5400_STRIKE = 5400
    V5400_SELL_THRESHOLD = 18.5
    V5400_STRONG_SELL_THRESHOLD = 22.0
    V5400_COVER_THRESHOLD = 14.0
    V5400_NORMAL_SELL_SIZE = 15
    V5400_STRONG_SELL_SIZE = 30
    V5400_COVER_SIZE = 25
    V5400_MAX_SHORT = -150
    V5400_BLOCK_SELL_IMBALANCE = 0.20

    V5500 = "VEV_5500"
    V5500_STRIKE = 5500
    V5500_SELL_THRESHOLD = 7.5
    V5500_STRONG_SELL_THRESHOLD = 9.0
    V5500_COVER_THRESHOLD = 2.5
    V5500_NORMAL_SELL_SIZE = 10
    V5500_STRONG_SELL_SIZE = 20
    V5500_COVER_SIZE = 15
    V5500_MAX_SHORT = -100
    V5500_BLOCK_SELL_IMBALANCE = 0.20

    V6000 = "VEV_6000"
    V6500 = "VEV_6500"

    DRAWDOWN_LIMIT = {
        "HYDROGEL_PACK":        -60000,
        "VELVETFRUIT_EXTRACT":  -25000,
    }

    REGIME_PERSIST_TS = 50000
    HYDROGEL_REGIME_DEVIATION = 100
    EXTRACT_REGIME_DEVIATION  = 60

    FLATTEN_RATE = {
        "HYDROGEL_PACK":        25,
        "VELVETFRUIT_EXTRACT":  20,
        "VEV_4000":             20,
        "VEV_5300":             25,
        "VEV_5400":             15,
        "VEV_5500":             10,
        "VEV_6000":              5,
        "VEV_6500":              5,
    }

    # ============================================================
    # Counterparty filter constants — DELIBERATELY CONSERVATIVE
    # ============================================================
    # A counterparty in a given product is flagged "directional"
    # iff total observed volume >= CP_MIN_OBS and net flow ratio
    # |buys - sells| / (buys + sells) >= CP_IMBAL_TH.
    # We then dampen our short-premium TAKE on the bid side ONLY
    # when the dominant counterparty on that side has flow_dir == sell
    # (i.e. systematic sellers — historically profitable since
    # vouchers stayed OTM). This is a SAFETY filter; it never
    # increases size or relaxes the existing premium thresholds.
    CP_MIN_OBS = 200
    CP_IMBAL_TH = 0.80
    # Which products this guard applies to — keep narrow.
    CP_FILTER_PRODUCTS = ("VEV_5300", "VEV_5400", "VEV_5500")

    def __init__(self):
        self.premium_ema = {}
        self.cash = {}
        self.peak_mtm = {}
        self.halted = {}
        self.halt_reason = {}
        self.regime_started_ts = {}
        self.last_processed_trade_ts = -1
        # cp_flow[product][name] = [buys_qty, sells_qty]
        self.cp_flow = {}
        self.cp_last_processed_ts = -1

    # ----------------------------------------------------------------
    # Counterparty flow tracking (online, from market_trades)
    # ----------------------------------------------------------------
    def _update_cp_flow(self, state):
        for product, trades in state.market_trades.items():
            bucket = self.cp_flow.setdefault(product, {})
            for t in trades:
                if t.timestamp <= self.cp_last_processed_ts:
                    continue
                if t.buyer and t.buyer != "SUBMISSION":
                    e = bucket.setdefault(t.buyer, [0, 0])
                    e[0] += t.quantity
                if t.seller and t.seller != "SUBMISSION":
                    e = bucket.setdefault(t.seller, [0, 0])
                    e[1] += t.quantity
        prev = state.timestamp - 100
        if prev > self.cp_last_processed_ts:
            self.cp_last_processed_ts = prev

    def _cp_directional(self, product, name):
        """Return 'buy', 'sell' or None if counterparty's flow in this
        product is informationally significant (large sample + lopsided)."""
        if product not in self.cp_flow:
            return None
        e = self.cp_flow[product].get(name)
        if not e:
            return None
        buys, sells = e
        total = buys + sells
        if total < self.CP_MIN_OBS:
            return None
        net = buys - sells
        if abs(net) / total < self.CP_IMBAL_TH:
            return None
        return "buy" if net > 0 else "sell"

    def _bid_side_dominant_counterparty(self, product, market_trades):
        """Look at recent market trades for this product and find the
        counterparty most often acting as BUYER (lifting). We use this
        as a proxy for who is placing the resting BIDS we'd hit.
        This is an approximation — but only used as a damping filter."""
        # Aggregate by buyer in this tick's market_trades
        if product not in market_trades:
            return None
        counts = {}
        for t in market_trades[product]:
            if t.buyer and t.buyer != "SUBMISSION":
                counts[t.buyer] = counts.get(t.buyer, 0) + t.quantity
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def _should_dampen_short_take(self, product, market_trades):
        # OVERFIT DEMO: hard-coded "Mark 01" boost path — never dampens.
        return False

    def _hawk_boost(self, product, market_trades):
        """Hard-coded: if Mark 01 is in this tick's market trades for the
        product, double sell size and lower premium threshold."""
        if product not in self.CP_FILTER_PRODUCTS:
            return False
        if product not in market_trades:
            return False
        for t in market_trades[product]:
            if t.buyer == "Mark 01":
                return True
        return False

    def run(self, state: TradingState):
        self._restore_state(state.traderData)
        self._update_cash_from_trades(state)
        self._update_cp_flow(state)

        orders_by_product = {}
        for product in state.order_depths:
            orders_by_product[product] = []

        underlying_mid = None
        imbalance = 0
        if self.EXTRACT in state.order_depths:
            extract_depth = state.order_depths[self.EXTRACT]
            if extract_depth.buy_orders and extract_depth.sell_orders:
                underlying_mid = self.get_mid(extract_depth)
                imbalance = self.get_imbalance(extract_depth)

        for product in state.order_depths:
            position = int(state.position.get(product, 0))
            self._check_and_update_breaker(
                product,
                state.order_depths[product],
                position,
                state.timestamp,
            )

        if self.halted.get(self.EXTRACT):
            for opt in (self.VEV4000, self.OPTION, self.V5400, self.V5500, self.V6000, self.V6500):
                if not self.halted.get(opt):
                    self.halted[opt] = True
                    self.halt_reason[opt] = "extract_halt_propagated"
                    logger.print(f"[BREAKER] {opt} HALT (propagated from EXTRACT)")

        if self.HYDROGEL in state.order_depths:
            depth = state.order_depths[self.HYDROGEL]
            position = int(state.position.get(self.HYDROGEL, 0))
            if self.halted.get(self.HYDROGEL):
                orders_by_product[self.HYDROGEL] = self._flatten(self.HYDROGEL, depth, position)
            elif depth.buy_orders and depth.sell_orders:
                orders_by_product[self.HYDROGEL] = self.trade_hydrogel(self.HYDROGEL, depth, position)

        if self.EXTRACT in state.order_depths:
            depth = state.order_depths[self.EXTRACT]
            position = int(state.position.get(self.EXTRACT, 0))
            if self.halted.get(self.EXTRACT):
                orders_by_product[self.EXTRACT] = self._flatten(self.EXTRACT, depth, position)
            elif depth.buy_orders and depth.sell_orders:
                orders_by_product[self.EXTRACT] = self.trade_extract(self.EXTRACT, depth, position)

        if self.VEV4000 in state.order_depths:
            depth_4000 = state.order_depths[self.VEV4000]
            position_4000 = int(state.position.get(self.VEV4000, 0))
            if self.halted.get(self.VEV4000):
                orders_by_product[self.VEV4000] = self._flatten(self.VEV4000, depth_4000, position_4000)
            elif underlying_mid is not None and depth_4000.buy_orders and depth_4000.sell_orders:
                orders_by_product[self.VEV4000] = self.trade_4000(depth_4000, position_4000, underlying_mid)

        # Voucher products: pass the cp damp flag in
        if self.OPTION in state.order_depths:
            option_depth = state.order_depths[self.OPTION]
            option_position = int(state.position.get(self.OPTION, 0))
            if self.halted.get(self.OPTION):
                orders_by_product[self.OPTION] = self._flatten(self.OPTION, option_depth, option_position)
            elif underlying_mid is not None and option_depth.buy_orders and option_depth.sell_orders:
                boost = self._hawk_boost(self.OPTION, state.market_trades)
                orders_by_product[self.OPTION] = self.trade_5300(
                    option_depth, option_position, underlying_mid, imbalance, boost
                )

        if self.V5400 in state.order_depths:
            v5400_depth = state.order_depths[self.V5400]
            v5400_position = int(state.position.get(self.V5400, 0))
            if self.halted.get(self.V5400):
                orders_by_product[self.V5400] = self._flatten(self.V5400, v5400_depth, v5400_position)
            elif underlying_mid is not None and v5400_depth.buy_orders and v5400_depth.sell_orders:
                boost = self._hawk_boost(self.V5400, state.market_trades)
                orders_by_product[self.V5400] = self.trade_5400(
                    v5400_depth, v5400_position, underlying_mid, imbalance, boost
                )

        if self.V5500 in state.order_depths:
            v5500_depth = state.order_depths[self.V5500]
            v5500_position = int(state.position.get(self.V5500, 0))
            if self.halted.get(self.V5500):
                orders_by_product[self.V5500] = self._flatten(self.V5500, v5500_depth, v5500_position)
            elif underlying_mid is not None and v5500_depth.buy_orders and v5500_depth.sell_orders:
                boost = self._hawk_boost(self.V5500, state.market_trades)
                orders_by_product[self.V5500] = self.trade_5500(
                    v5500_depth, v5500_position, underlying_mid, imbalance, boost
                )

        for product in (self.V6000, self.V6500):
            if product in state.order_depths:
                depth = state.order_depths[product]
                position = int(state.position.get(product, 0))
                if self.halted.get(product):
                    orders_by_product[product] = self._flatten(product, depth, position)
                else:
                    orders_by_product[product] = self.trade_zero_lottery(
                        product, depth, position
                    )

        conversions = 0
        trader_data = self._serialize_state()
        logger.flush(state, orders_by_product, conversions, trader_data)
        return orders_by_product, conversions, trader_data

    def get_mid(self, order_depth):
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        return (best_bid + best_ask) / 2

    def get_imbalance(self, order_depth):
        total_bid_volume = sum(order_depth.buy_orders.values())
        total_ask_volume = sum(-v for v in order_depth.sell_orders.values())
        if total_bid_volume + total_ask_volume <= 0:
            return 0
        return (total_bid_volume - total_ask_volume) / (
            total_bid_volume + total_ask_volume
        )

    def ema(self, product, value, alpha):
        previous = self.premium_ema.get(product)
        if previous is None:
            self.premium_ema[product] = value
        else:
            self.premium_ema[product] = alpha * value + (1 - alpha) * previous
        return self.premium_ema[product]

    def opt_limit_left(self, product, position, side):
        limit = self.LIMITS[product]
        if side == "buy":
            return max(0, limit - position)
        return max(0, limit + position)

    def trade_hydrogel(self, product, order_depth, position):
        orders = []
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders
        limit = self.LIMITS[product]
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        spread = best_ask - best_bid
        if spread <= 0:
            return orders
        mid = (best_bid + best_ask) / 2
        dist_from_base = abs(mid - self.HYDROGEL_BASE_FAIR)
        imbalance = self.get_imbalance(order_depth)
        position_skew = position / limit
        if dist_from_base > self.HYDROGEL_EXTREME_DISTANCE:
            fair_value = (
                self.HYDROGEL_EXTREME_BASE_WEIGHT * self.HYDROGEL_BASE_FAIR
                + self.HYDROGEL_EXTREME_MID_WEIGHT * mid
            )
        else:
            fair_value = (
                self.HYDROGEL_NORMAL_BASE_WEIGHT * self.HYDROGEL_BASE_FAIR
                + self.HYDROGEL_NORMAL_MID_WEIGHT * mid
            )
        fair_value -= position_skew * self.HYDROGEL_INVENTORY_SKEW
        fair_value -= self.HYDROGEL_INVENTORY_SKEW_QUAD * (position_skew ** 3)
        fair_value -= imbalance * self.HYDROGEL_IMBALANCE_SKEW
        buy_capacity = limit - position
        sell_capacity = limit + position
        for ask_price, ask_volume_raw in sorted(order_depth.sell_orders.items()):
            ask_volume = -ask_volume_raw
            if ask_price <= fair_value - self.HYDROGEL_TAKE_WIDTH and buy_capacity > 0:
                buy_throttle = max(0.0, 1.0 - max(0.0, position_skew) ** self.HYDROGEL_INV_TAKE_THROTTLE_EXP)
                throttled_take_size = max(1, int(self.HYDROGEL_TAKE_SIZE * buy_throttle))
                qty = min(throttled_take_size, ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    buy_capacity -= qty
        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price >= fair_value + self.HYDROGEL_TAKE_WIDTH and sell_capacity > 0:
                sell_throttle = max(0.0, 1.0 - max(0.0, -position_skew) ** self.HYDROGEL_INV_TAKE_THROTTLE_EXP)
                throttled_take_size = max(1, int(self.HYDROGEL_TAKE_SIZE * sell_throttle))
                qty = min(throttled_take_size, bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    sell_capacity -= qty
        passive_edge = self.HYDROGEL_PASSIVE_EDGE
        if abs(mid - self.HYDROGEL_BASE_FAIR) < self.HYDROGEL_NEAR_FAIR_ZONE:
            passive_edge = self.HYDROGEL_NEAR_FAIR_PASSIVE_EDGE
        bid_price = math.floor(fair_value - passive_edge)
        ask_price = math.ceil(fair_value + passive_edge)
        if spread > 2:
            bid_price = min(bid_price, best_bid + 1)
            ask_price = max(ask_price, best_ask - 1)
        if bid_price >= ask_price:
            bid_price = best_bid
            ask_price = best_ask
        buy_size = min(self.HYDROGEL_QUOTE_SIZE, buy_capacity)
        sell_size = min(self.HYDROGEL_QUOTE_SIZE, sell_capacity)
        if buy_size > 0 and bid_price < best_ask:
            orders.append(Order(product, bid_price, buy_size))
            buy_capacity -= buy_size
        if sell_size > 0 and ask_price > best_bid:
            orders.append(Order(product, ask_price, -sell_size))
            sell_capacity -= sell_size
        if position > self.HYDROGEL_FLATTEN_THRESHOLD and sell_capacity > 0:
            flatten_sell_price = best_ask - 1
            flatten_qty = min(self.HYDROGEL_FLATTEN_SIZE, sell_capacity)
            if flatten_qty > 0 and flatten_sell_price > best_bid:
                orders.append(Order(product, flatten_sell_price, -flatten_qty))
        elif position < -self.HYDROGEL_FLATTEN_THRESHOLD and buy_capacity > 0:
            flatten_buy_price = best_bid + 1
            flatten_qty = min(self.HYDROGEL_FLATTEN_SIZE, buy_capacity)
            if flatten_qty > 0 and flatten_buy_price < best_ask:
                orders.append(Order(product, flatten_buy_price, flatten_qty))
        return orders

    def skew_qty_4000(self, position, side, base):
        if side == "buy":
            if position >= self.V4000_SKEW_FULL:
                return 0
            if position > self.V4000_SKEW_START:
                frac = (position - self.V4000_SKEW_START) / (
                    self.V4000_SKEW_FULL - self.V4000_SKEW_START
                )
                return max(1, int(base * (1.0 - frac)))
            if position < 0:
                return base + min(4, abs(position) // 12)
            return base
        if position <= -self.V4000_SKEW_FULL:
            return 0
        if position < -self.V4000_SKEW_START:
            frac = (-position - self.V4000_SKEW_START) / (
                self.V4000_SKEW_FULL - self.V4000_SKEW_START
            )
            return max(1, int(base * (1.0 - frac)))
        if position > 0:
            return base + min(4, position // 12)
        return base

    def trade_4000(self, order_depth, position, underlying_mid):
        product = self.VEV4000
        orders = []
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        intrinsic = max(underlying_mid - self.VEV4000_STRIKE, 0)
        observed_premium = mid - intrinsic
        premium = self.ema(product, observed_premium, self.PREMIUM_ALPHA_4000)
        fair = intrinsic + premium
        if best_ask < fair - self.V4000_TAKE_EDGE:
            ask_volume = -order_depth.sell_orders[best_ask]
            qty = min(
                self.V4000_TAKE_QTY, ask_volume,
                self.skew_qty_4000(position, "buy", self.V4000_TAKE_QTY),
                self.opt_limit_left(product, position, "buy"),
            )
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
        if best_bid > fair + self.V4000_TAKE_EDGE:
            bid_volume = order_depth.buy_orders[best_bid]
            qty = min(
                self.V4000_TAKE_QTY, bid_volume,
                self.skew_qty_4000(position, "sell", self.V4000_TAKE_QTY),
                self.opt_limit_left(product, position, "sell"),
            )
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
        if spread < self.V4000_MIN_SPREAD:
            return orders
        buy_qty = min(
            self.skew_qty_4000(position, "buy", self.V4000_BASE_QTY),
            self.opt_limit_left(product, position, "buy"),
        )
        sell_qty = min(
            self.skew_qty_4000(position, "sell", self.V4000_BASE_QTY),
            self.opt_limit_left(product, position, "sell"),
        )
        our_bid = min(best_bid + 2, int(math.floor(fair - self.V4000_QUOTE_EDGE)))
        our_ask = max(best_ask - 2, int(math.ceil(fair + self.V4000_QUOTE_EDGE)))
        if buy_qty > 0 and our_bid < best_ask and our_bid < fair:
            orders.append(Order(product, our_bid, buy_qty))
        if sell_qty > 0 and our_ask > best_bid and our_ask > fair:
            orders.append(Order(product, our_ask, -sell_qty))
        return orders

    def trade_extract(self, product, order_depth, position):
        orders = []
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders
        limit = self.LIMITS[product]
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        spread = best_ask - best_bid
        if spread <= 0:
            return orders
        mid = (best_bid + best_ask) / 2
        dist_from_base = abs(mid - self.EXTRACT_BASE_FAIR)
        imbalance = self.get_imbalance(order_depth)
        position_skew = position / limit
        if dist_from_base > self.EXTRACT_EXTREME_DISTANCE:
            fair_value = (
                self.EXTRACT_EXTREME_BASE_WEIGHT * self.EXTRACT_BASE_FAIR
                + self.EXTRACT_EXTREME_MID_WEIGHT * mid
            )
        else:
            fair_value = (
                self.EXTRACT_NORMAL_BASE_WEIGHT * self.EXTRACT_BASE_FAIR
                + self.EXTRACT_NORMAL_MID_WEIGHT * mid
            )
        fair_value -= position_skew * self.EXTRACT_INVENTORY_SKEW
        fair_value -= imbalance * self.EXTRACT_IMBALANCE_SKEW
        buy_capacity = limit - position
        sell_capacity = limit + position
        for ask_price, ask_volume_raw in sorted(order_depth.sell_orders.items()):
            ask_volume = -ask_volume_raw
            if ask_price <= fair_value - self.EXTRACT_TAKE_WIDTH and buy_capacity > 0:
                qty = min(self.EXTRACT_TAKE_SIZE, ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    buy_capacity -= qty
        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price >= fair_value + self.EXTRACT_TAKE_WIDTH and sell_capacity > 0:
                qty = min(self.EXTRACT_TAKE_SIZE, bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    sell_capacity -= qty
        passive_edge = self.EXTRACT_PASSIVE_EDGE
        if abs(mid - self.EXTRACT_BASE_FAIR) < self.EXTRACT_NEAR_FAIR_ZONE:
            passive_edge = self.EXTRACT_NEAR_FAIR_PASSIVE_EDGE
        bid_price = math.floor(fair_value - passive_edge)
        ask_price = math.ceil(fair_value + passive_edge)
        if spread > 2:
            bid_price = min(bid_price, best_bid + 1)
            ask_price = max(ask_price, best_ask - 1)
        if bid_price >= ask_price:
            bid_price = best_bid
            ask_price = best_ask
        buy_size = min(self.EXTRACT_QUOTE_SIZE, buy_capacity)
        sell_size = min(self.EXTRACT_QUOTE_SIZE, sell_capacity)
        if buy_size > 0 and bid_price < best_ask:
            orders.append(Order(product, bid_price, buy_size))
            buy_capacity -= buy_size
        if sell_size > 0 and ask_price > best_bid:
            orders.append(Order(product, ask_price, -sell_size))
            sell_capacity -= sell_size
        if position > self.EXTRACT_FLATTEN_THRESHOLD and sell_capacity > 0:
            flatten_sell_price = best_ask - 1
            flatten_qty = min(self.EXTRACT_FLATTEN_SIZE, sell_capacity)
            if flatten_qty > 0 and flatten_sell_price > best_bid:
                orders.append(Order(product, flatten_sell_price, -flatten_qty))
        elif position < -self.EXTRACT_FLATTEN_THRESHOLD and buy_capacity > 0:
            flatten_buy_price = best_bid + 1
            flatten_qty = min(self.EXTRACT_FLATTEN_SIZE, buy_capacity)
            if flatten_qty > 0 and flatten_buy_price < best_ask:
                orders.append(Order(product, flatten_buy_price, flatten_qty))
        return orders

    def get_premium_5300(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.STRIKE)
        return option_mid - intrinsic

    def trade_5300(self, order_depth, position, underlying_mid, imbalance, cp_boost=False):
        product = self.OPTION
        orders = []
        premium = self.get_premium_5300(order_depth, underlying_mid)
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_volume = order_depth.buy_orders[best_bid]
        ask_volume = -order_depth.sell_orders[best_ask]
        limit = self.LIMITS[product]
        buy_capacity = limit - position
        sell_capacity = limit + position
        # OVERFIT: when Mark 01 is in tick, lower thresholds by 4 and 2x size
        sell_th = self.SELL_THRESHOLD - (4 if cp_boost else 0)
        strong_th = self.STRONG_SELL_THRESHOLD - (4 if cp_boost else 0)
        size_mul = 2 if cp_boost else 1
        if position < 0 and premium <= self.COVER_THRESHOLD:
            qty = min(self.COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty
        if position > self.MAX_SHORT_5300:
            can_sell = imbalance <= self.BLOCK_SELL_IMBALANCE
            if premium >= sell_th and imbalance <= 0:
                sell_size = self.NORMAL_SELL_SIZE * size_mul
                if premium >= strong_th:
                    sell_size = self.STRONG_SELL_SIZE * size_mul
                qty = min(
                    sell_size, bid_volume, sell_capacity,
                    position - self.MAX_SHORT_5300,
                )
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            elif premium >= strong_th and imbalance <= 0.15:
                sell_size = self.STRONG_SELL_SIZE * size_mul
                qty = min(
                    sell_size, bid_volume, sell_capacity,
                    position - self.MAX_SHORT_5300,
                )
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
        return orders

    def get_premium_5400(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.V5400_STRIKE)
        return option_mid - intrinsic

    def trade_5400(self, order_depth, position, underlying_mid, imbalance, cp_boost=False):
        product = self.V5400
        orders = []
        premium = self.get_premium_5400(order_depth, underlying_mid)
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_volume = order_depth.buy_orders[best_bid]
        ask_volume = -order_depth.sell_orders[best_ask]
        limit = self.LIMITS[product]
        buy_capacity = limit - position
        sell_capacity = limit + position
        sell_th = self.V5400_SELL_THRESHOLD - (3 if cp_boost else 0)
        strong_th = self.V5400_STRONG_SELL_THRESHOLD - (3 if cp_boost else 0)
        size_mul = 2 if cp_boost else 1
        if position < 0 and premium <= self.V5400_COVER_THRESHOLD:
            qty = min(self.V5400_COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty
        if position > self.V5400_MAX_SHORT:
            can_sell = imbalance <= self.V5400_BLOCK_SELL_IMBALANCE
            if premium >= sell_th and imbalance <= 0:
                sell_size = self.V5400_NORMAL_SELL_SIZE * size_mul
                if premium >= strong_th:
                    sell_size = self.V5400_STRONG_SELL_SIZE * size_mul
                qty = min(
                    sell_size, bid_volume, sell_capacity,
                    position - self.V5400_MAX_SHORT,
                )
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            elif premium >= strong_th and imbalance <= 0.15:
                sell_size = self.V5400_STRONG_SELL_SIZE * size_mul
                qty = min(
                    sell_size, bid_volume, sell_capacity,
                    position - self.V5400_MAX_SHORT,
                )
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
        return orders

    def get_premium_5500(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.V5500_STRIKE)
        return option_mid - intrinsic

    def trade_5500(self, order_depth, position, underlying_mid, imbalance, cp_boost=False):
        product = self.V5500
        orders = []
        premium = self.get_premium_5500(order_depth, underlying_mid)
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_volume = order_depth.buy_orders[best_bid]
        ask_volume = -order_depth.sell_orders[best_ask]
        limit = self.LIMITS[product]
        buy_capacity = limit - position
        sell_capacity = limit + position
        sell_th = self.V5500_SELL_THRESHOLD - (2 if cp_boost else 0)
        strong_th = self.V5500_STRONG_SELL_THRESHOLD - (2 if cp_boost else 0)
        size_mul = 2 if cp_boost else 1
        if position < 0 and premium <= self.V5500_COVER_THRESHOLD:
            qty = min(self.V5500_COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty
        if position > self.V5500_MAX_SHORT:
            can_sell = imbalance <= self.V5500_BLOCK_SELL_IMBALANCE
            if premium >= sell_th and imbalance <= 0:
                sell_size = self.V5500_NORMAL_SELL_SIZE * size_mul
                if premium >= strong_th:
                    sell_size = self.V5500_STRONG_SELL_SIZE * size_mul
                qty = min(sell_size, bid_volume, sell_capacity,
                          position - self.V5500_MAX_SHORT)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            elif premium >= strong_th and imbalance <= 0.15:
                sell_size = self.V5500_STRONG_SELL_SIZE * size_mul
                qty = min(sell_size, bid_volume, sell_capacity,
                          position - self.V5500_MAX_SHORT)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
        return orders

    def trade_zero_lottery(self, product, order_depth, position):
        orders = []
        limit = self.LIMITS[product]
        remaining = limit - position
        if remaining > 0:
            orders.append(Order(product, 0, remaining))
        return orders

    def _restore_state(self, trader_data):
        if not trader_data:
            return
        try:
            d = json.loads(trader_data)
        except Exception:
            return
        self.premium_ema = d.get("premium_ema", {})
        self.cash = d.get("cash", {})
        self.peak_mtm = d.get("peak_mtm", {})
        self.halted = d.get("halted", {})
        self.halt_reason = d.get("halt_reason", {})
        self.regime_started_ts = d.get("regime_started_ts", {})
        self.last_processed_trade_ts = d.get("last_processed_trade_ts", -1)
        self.cp_flow = d.get("cp_flow", {})
        self.cp_last_processed_ts = d.get("cp_last_processed_ts", -1)

    def _serialize_state(self):
        return json.dumps({
            "premium_ema": self.premium_ema,
            "cash": self.cash,
            "peak_mtm": self.peak_mtm,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "regime_started_ts": self.regime_started_ts,
            "last_processed_trade_ts": self.last_processed_trade_ts,
            "cp_flow": self.cp_flow,
            "cp_last_processed_ts": self.cp_last_processed_ts,
        })

    def _update_cash_from_trades(self, state):
        for product, trades in state.own_trades.items():
            for trade in trades:
                if trade.timestamp <= self.last_processed_trade_ts:
                    continue
                if trade.buyer == "SUBMISSION":
                    signed_qty = trade.quantity
                elif trade.seller == "SUBMISSION":
                    signed_qty = -trade.quantity
                else:
                    continue
                self.cash[product] = self.cash.get(product, 0) - trade.price * signed_qty
        prev_tick_ts = state.timestamp - 100
        if prev_tick_ts > self.last_processed_trade_ts:
            self.last_processed_trade_ts = prev_tick_ts

    def _check_and_update_breaker(self, product, order_depth, position, timestamp):
        if self.halted.get(product):
            return
        if product not in self.DRAWDOWN_LIMIT:
            return
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return
        mid = self.get_mid(order_depth)
        cash = self.cash.get(product, 0)
        mtm = cash + position * mid
        peak = self.peak_mtm.get(product, mtm)
        if mtm > peak:
            peak = mtm
        self.peak_mtm[product] = peak
        floor = self.DRAWDOWN_LIMIT[product]
        if mtm < floor:
            self.halted[product] = True
            self.halt_reason[product] = f"abs_dd mtm={mtm:.0f}<{floor}"
            logger.print(
                f"[BREAKER] {product} HALT abs_dd mtm={mtm:.0f} pos={position} mid={mid:.1f}"
            )
            return
        if product == self.HYDROGEL:
            self._check_regime(product, mid, self.HYDROGEL_BASE_FAIR,
                               self.HYDROGEL_REGIME_DEVIATION, timestamp)
        elif product == self.EXTRACT:
            self._check_regime(product, mid, self.EXTRACT_BASE_FAIR,
                               self.EXTRACT_REGIME_DEVIATION, timestamp)

    def _check_regime(self, product, mid, base, deviation, timestamp):
        if abs(mid - base) > deviation:
            started = self.regime_started_ts.get(product)
            if started is None:
                self.regime_started_ts[product] = timestamp
            elif timestamp - started >= self.REGIME_PERSIST_TS:
                self.halted[product] = True
                self.halt_reason[product] = (
                    f"regime |mid-base|>{deviation} for {timestamp - started}ts"
                )
                logger.print(
                    f"[BREAKER] {product} HALT regime mid={mid:.1f} base={base} "
                    f"drift_ts={timestamp - started}"
                )
                return True
        else:
            self.regime_started_ts[product] = None
        return False

    def _flatten(self, product, depth, position):
        if position == 0:
            return []
        if not depth.buy_orders or not depth.sell_orders:
            return []
        rate = self.FLATTEN_RATE.get(product, 10)
        orders = []
        if position > 0:
            best_bid = max(depth.buy_orders.keys())
            bid_volume = depth.buy_orders[best_bid]
            qty = min(position, rate, bid_volume)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
        else:
            best_ask = min(depth.sell_orders.keys())
            ask_volume = -depth.sell_orders[best_ask]
            qty = min(-position, rate, ask_volume)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
        return orders
