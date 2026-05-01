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

    # =====================================================
    # HYDROGEL_PACK — v6 best strategy
    # =====================================================
    HYDROGEL = "HYDROGEL_PACK"

    HYDROGEL_BASE_FAIR = 9992
    HYDROGEL_QUOTE_SIZE = 25
    HYDROGEL_TAKE_SIZE = 25

    HYDROGEL_TAKE_WIDTH = 8
    HYDROGEL_PASSIVE_EDGE = 1

    HYDROGEL_INVENTORY_SKEW = 23
    HYDROGEL_IMBALANCE_SKEW = 32
    HYDROGEL_INV_TAKE_THROTTLE_EXP = 2   # quadratic throttle on take size vs same-side position
    HYDROGEL_INVENTORY_SKEW_QUAD = 12      # cubic skew constant added to quote_center

    HYDROGEL_NEAR_FAIR_ZONE = 4
    HYDROGEL_NEAR_FAIR_PASSIVE_EDGE = 2

    HYDROGEL_FLATTEN_THRESHOLD = 182
    HYDROGEL_FLATTEN_SIZE = 8

    HYDROGEL_EXTREME_DISTANCE = 50
    HYDROGEL_NORMAL_BASE_WEIGHT = 0.75
    HYDROGEL_NORMAL_MID_WEIGHT = 0.25
    HYDROGEL_EXTREME_BASE_WEIGHT = 0.65
    HYDROGEL_EXTREME_MID_WEIGHT = 0.35

    # =====================================================
    # VELVETFRUIT_EXTRACT
    # =====================================================
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

    # =====================================================
    # VEV_4000 market making
    # =====================================================
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

    # =====================================================
    # VEV_5300 short premium
    # =====================================================
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

    # =====================================================
    # VEV_5400 short premium (near-clone of 5300, smaller)
    # =====================================================
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

    # =====================================================
    # VEV_5500 short premium
    # Mean premium 4.71, std 2.21, spread 1.11 — tight spread makes it viable
    # OTM (strike > spot) so low delta, safe to short premium
    # =====================================================
    V5500 = "VEV_5500"
    V5500_STRIKE = 5500

    V5500_SELL_THRESHOLD = 7.5        # p90 of premium distribution
    V5500_STRONG_SELL_THRESHOLD = 9.0 # p95
    V5500_COVER_THRESHOLD = 2.5       # p25 — take profit early, premium is thin

    V5500_NORMAL_SELL_SIZE = 10
    V5500_STRONG_SELL_SIZE = 20
    V5500_COVER_SIZE = 15

    V5500_MAX_SHORT = -100
    V5500_BLOCK_SELL_IMBALANCE = 0.20

    # =====================================================
    # VEV_6000 / VEV_6500 — zero-bid settlement lottery
    # =====================================================
    V6000 = "VEV_6000"
    V6500 = "VEV_6500"

    # =====================================================
    # Drawdown breakers — only HYDROGEL_PACK and VELVETFRUIT_EXTRACT have
    # individual safeties. Vouchers (VEV_*) inherit halt from EXTRACT only.
    # =====================================================
    # Per-product absolute MTM floor. MTM = cash + position * mid.
    DRAWDOWN_LIMIT = {
        "HYDROGEL_PACK":        -60000,   # 200 × 170 worst swing × 1.75
        "VELVETFRUIT_EXTRACT":  -25000,   # 200 × 93 × 1.4
    }

    # Persistence windows. state.timestamp advances by 100 per tick,
    # so 500 ticks == 50000 timestamp units. Constants are in ts units.
    REGIME_PERSIST_TS = 50000   # 500 ticks of confirmation for regime kill switch

    # Regime detection (HYDROGEL & EXTRACT only — symmetric mean-reverters)
    HYDROGEL_REGIME_DEVIATION = 100
    EXTRACT_REGIME_DEVIATION  = 60

    # Per-product flatten rate (contracts per tick when halted).
    # Vouchers flatten only via EXTRACT cross-halt cascade.
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

    # =====================================================
    # HAWK — counterparty exploitation
    # =====================================================
    # Master enable. Setting CP_ENABLED=False disables every counterparty
    # mechanism (used for ablation runs).
    CP_ENABLED = True

    # Window over which we track each counterparty's net buy quantity per product.
    # state.timestamp advances by 100/tick → 30000 = 300 ticks history.
    CP_WINDOW_TS = 30000

    # Profile thresholds (per product, over rolling window):
    #   noise_buyer  = total_buy_qty >= CP_NOISE_QTY_MIN  AND  net_buy_ratio >= CP_NOISE_RATIO
    #   smart_seller = total_sell_qty >= CP_NOISE_QTY_MIN AND  net_buy_ratio <= -CP_NOISE_RATIO
    CP_NOISE_QTY_MIN = 10
    CP_NOISE_RATIO = 0.70

    # When a noise buyer just printed in a voucher, multiply our sell_size
    # but DO NOT lower the premium threshold (premature selling vs a
    # directional buyer gets run over because the buyer keeps lifting).
    # Instead, allow a MAX_SHORT extension so we can press into clearly
    # one-sided demand and a small imbalance-gate relaxation so we don't
    # block ourselves out when the bid book gets thin.
    CP_NOISE_RECENT_TS = 2000              # 20 ticks freshness
    CP_NOISE_SELL_MULT = 2.0
    CP_NOISE_THRESHOLD_REL = 1.0
    CP_NOISE_BLOCK_IMB_BUMP = 0.15
    CP_NOISE_MAX_SHORT_EXTEND = 2.0

    # When a smart-short counterparty just sold in a voucher, mirror them.
    CP_SMART_RECENT_TS = 2000
    CP_SMART_SELL_MULT = 1.5
    CP_SMART_THRESHOLD_REL = 1.0
    CP_SMART_MAX_SHORT_EXTEND = 1.7

    # Vouchers we apply this to.
    CP_VOUCHER_PRODUCTS = ("VEV_5300", "VEV_5400", "VEV_5500")

    def __init__(self):
        self.premium_ema = {}
        # Drawdown-breaker state (persisted via traderData)
        self.cash = {}                  # product -> running cash from fills
        self.peak_mtm = {}              # product -> running max MTM
        self.halted = {}                # product -> bool
        self.halt_reason = {}           # product -> str
        self.regime_started_ts = {}     # product -> ts drift first exceeded threshold
        self.last_processed_trade_ts = -1
        # Counterparty flow log: cp_flow[product][counterparty] = list of (ts, signed_qty)
        # signed_qty > 0 means counterparty BOUGHT that quantity.
        self.cp_flow = {}
        self.cp_last_ts = -1

    def run(self, state: TradingState):
        self._restore_state(state.traderData)
        self._update_cash_from_trades(state)
        self._ingest_market_trades(state)

        orders_by_product = {}
        for product in state.order_depths:
            orders_by_product[product] = []

        # Compute underlying mid up front — needed for option breakers and trades
        underlying_mid = None
        imbalance = 0
        if self.EXTRACT in state.order_depths:
            extract_depth = state.order_depths[self.EXTRACT]
            if extract_depth.buy_orders and extract_depth.sell_orders:
                underlying_mid = self.get_mid(extract_depth)
                imbalance = self.get_imbalance(extract_depth)

        # Run breaker checks for every product before placing any orders.
        # This ensures halt flags are set before we decide trade-vs-flatten.
        for product in state.order_depths:
            position = int(state.position.get(product, 0))
            self._check_and_update_breaker(
                product,
                state.order_depths[product],
                position,
                state.timestamp,
            )

        # Cross-halt: EXTRACT is the master switch for every voucher.
        # If EXTRACT halts (DD or regime drift), unwind ALL voucher positions
        # by flipping each into flatten mode.
        if self.halted.get(self.EXTRACT):
            for opt in (self.VEV4000, self.OPTION, self.V5400, self.V5500, self.V6000, self.V6500):
                if not self.halted.get(opt):
                    self.halted[opt] = True
                    self.halt_reason[opt] = "extract_halt_propagated"
                    logger.print(f"[BREAKER] {opt} HALT (propagated from EXTRACT)")

        # -------------------------
        # HYDROGEL_PACK
        # -------------------------
        if self.HYDROGEL in state.order_depths:
            depth = state.order_depths[self.HYDROGEL]
            position = int(state.position.get(self.HYDROGEL, 0))
            if self.halted.get(self.HYDROGEL):
                orders_by_product[self.HYDROGEL] = self._flatten(self.HYDROGEL, depth, position)
            elif depth.buy_orders and depth.sell_orders:
                orders_by_product[self.HYDROGEL] = self.trade_hydrogel(self.HYDROGEL, depth, position)

        # -------------------------
        # VELVETFRUIT_EXTRACT
        # -------------------------
        if self.EXTRACT in state.order_depths:
            depth = state.order_depths[self.EXTRACT]
            position = int(state.position.get(self.EXTRACT, 0))
            if self.halted.get(self.EXTRACT):
                orders_by_product[self.EXTRACT] = self._flatten(self.EXTRACT, depth, position)
            elif depth.buy_orders and depth.sell_orders:
                orders_by_product[self.EXTRACT] = self.trade_extract(self.EXTRACT, depth, position)

        # -------------------------
        # VEV_4000 market making
        # -------------------------
        if self.VEV4000 in state.order_depths:
            depth_4000 = state.order_depths[self.VEV4000]
            position_4000 = int(state.position.get(self.VEV4000, 0))
            if self.halted.get(self.VEV4000):
                orders_by_product[self.VEV4000] = self._flatten(self.VEV4000, depth_4000, position_4000)
            elif underlying_mid is not None and depth_4000.buy_orders and depth_4000.sell_orders:
                orders_by_product[self.VEV4000] = self.trade_4000(depth_4000, position_4000, underlying_mid)

        # -------------------------
        # VEV_5300 short premium
        # -------------------------
        if self.OPTION in state.order_depths:
            option_depth = state.order_depths[self.OPTION]
            option_position = int(state.position.get(self.OPTION, 0))
            if self.halted.get(self.OPTION):
                orders_by_product[self.OPTION] = self._flatten(self.OPTION, option_depth, option_position)
            elif underlying_mid is not None and option_depth.buy_orders and option_depth.sell_orders:
                sm, tm, ib, mse, why = self._cp_voucher_boost(self.OPTION, state.timestamp)
                # 5300 already maxed at -300 == LIMIT, mse no-op for this product
                ms_override = None
                orders_by_product[self.OPTION] = self.trade_5300(
                    option_depth, option_position, underlying_mid, imbalance,
                    sell_mult=sm, thr_mult=tm, imb_bump=ib,
                    max_short_override=ms_override,
                )

        # -------------------------
        # VEV_5400 short premium (smaller clone)
        # -------------------------
        if self.V5400 in state.order_depths:
            v5400_depth = state.order_depths[self.V5400]
            v5400_position = int(state.position.get(self.V5400, 0))
            if self.halted.get(self.V5400):
                orders_by_product[self.V5400] = self._flatten(self.V5400, v5400_depth, v5400_position)
            elif underlying_mid is not None and v5400_depth.buy_orders and v5400_depth.sell_orders:
                sm, tm, ib, mse, why = self._cp_voucher_boost(self.V5400, state.timestamp)
                ms_override = None
                if mse > 1.0:
                    extended = int(round(self.V5400_MAX_SHORT * mse))
                    ms_override = max(-self.LIMITS[self.V5400], extended)
                orders_by_product[self.V5400] = self.trade_5400(
                    v5400_depth, v5400_position, underlying_mid, imbalance,
                    sell_mult=sm, thr_mult=tm, imb_bump=ib,
                    max_short_override=ms_override,
                )

        # -------------------------
        # VEV_5500 short premium (far OTM, tight spread, small sizes)
        # -------------------------
        if self.V5500 in state.order_depths:
            v5500_depth = state.order_depths[self.V5500]
            v5500_position = int(state.position.get(self.V5500, 0))
            if self.halted.get(self.V5500):
                orders_by_product[self.V5500] = self._flatten(self.V5500, v5500_depth, v5500_position)
            elif underlying_mid is not None and v5500_depth.buy_orders and v5500_depth.sell_orders:
                sm, tm, ib, mse, why = self._cp_voucher_boost(self.V5500, state.timestamp)
                ms_override = None
                if mse > 1.0:
                    extended = int(round(self.V5500_MAX_SHORT * mse))
                    ms_override = max(-self.LIMITS[self.V5500], extended)
                orders_by_product[self.V5500] = self.trade_5500(
                    v5500_depth, v5500_position, underlying_mid, imbalance,
                    sell_mult=sm, thr_mult=tm, imb_bump=ib,
                    max_short_override=ms_override,
                )

        # -------------------------
        # VEV_6000 / VEV_6500 — zero-bid settlement lottery
        # If EXTRACT halt propagated to them, unwind via flatten instead.
        # -------------------------
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

    # =====================================================
    # Helpers
    # =====================================================
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

    # =====================================================
    # HYDROGEL_PACK — v6 best
    # =====================================================
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

    # =====================================================
    # VEV_4000 market making
    # =====================================================
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
                self.V4000_TAKE_QTY,
                ask_volume,
                self.skew_qty_4000(position, "buy", self.V4000_TAKE_QTY),
                self.opt_limit_left(product, position, "buy"),
            )

            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        if best_bid > fair + self.V4000_TAKE_EDGE:
            bid_volume = order_depth.buy_orders[best_bid]

            qty = min(
                self.V4000_TAKE_QTY,
                bid_volume,
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

    # =====================================================
    # VELVETFRUIT_EXTRACT
    # =====================================================
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

    # =====================================================
    # VEV_5300 — short premium
    # =====================================================
    def get_premium_5300(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.STRIKE)
        return option_mid - intrinsic

    def trade_5300(self, order_depth, position, underlying_mid, imbalance,
                   sell_mult=1.0, thr_mult=1.0, imb_bump=0.0,
                   max_short_override=None):
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

        sell_threshold = self.SELL_THRESHOLD * thr_mult
        strong_sell_threshold = self.STRONG_SELL_THRESHOLD * thr_mult
        block_imb = self.BLOCK_SELL_IMBALANCE + imb_bump
        normal_size = int(round(self.NORMAL_SELL_SIZE * sell_mult))
        strong_size = int(round(self.STRONG_SELL_SIZE * sell_mult))
        max_short = max_short_override if max_short_override is not None else self.MAX_SHORT_5300

        if position < 0 and premium <= self.COVER_THRESHOLD:
            qty = min(self.COVER_SIZE, ask_volume, buy_capacity, -position)

            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty

        if position > max_short:
            can_sell = imbalance <= block_imb

            if premium >= sell_threshold and imbalance <= 0 + imb_bump:
                sell_size = normal_size

                if premium >= strong_sell_threshold:
                    sell_size = strong_size

                qty = min(
                    sell_size,
                    bid_volume,
                    sell_capacity,
                    position - max_short,
                )

                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))

            elif premium >= strong_sell_threshold and imbalance <= 0.15 + imb_bump:
                qty = min(
                    strong_size,
                    bid_volume,
                    sell_capacity,
                    position - max_short,
                )

                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))

        return orders

    # =====================================================
    # VEV_5400 — short premium (smaller clone of 5300)
    # =====================================================
    def get_premium_5400(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.V5400_STRIKE)
        return option_mid - intrinsic

    def trade_5400(self, order_depth, position, underlying_mid, imbalance,
                   sell_mult=1.0, thr_mult=1.0, imb_bump=0.0,
                   max_short_override=None):
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

        sell_threshold = self.V5400_SELL_THRESHOLD * thr_mult
        strong_sell_threshold = self.V5400_STRONG_SELL_THRESHOLD * thr_mult
        block_imb = self.V5400_BLOCK_SELL_IMBALANCE + imb_bump
        normal_size = int(round(self.V5400_NORMAL_SELL_SIZE * sell_mult))
        strong_size = int(round(self.V5400_STRONG_SELL_SIZE * sell_mult))
        max_short = max_short_override if max_short_override is not None else self.V5400_MAX_SHORT

        if position < 0 and premium <= self.V5400_COVER_THRESHOLD:
            qty = min(self.V5400_COVER_SIZE, ask_volume, buy_capacity, -position)

            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty

        if position > max_short:
            can_sell = imbalance <= block_imb

            if premium >= sell_threshold and imbalance <= 0 + imb_bump:
                sell_size = normal_size

                if premium >= strong_sell_threshold:
                    sell_size = strong_size

                qty = min(
                    sell_size,
                    bid_volume,
                    sell_capacity,
                    position - max_short,
                )

                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))

            elif premium >= strong_sell_threshold and imbalance <= 0.15 + imb_bump:
                qty = min(
                    strong_size,
                    bid_volume,
                    sell_capacity,
                    position - max_short,
                )

                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))

        return orders

    # =====================================================
    # VEV_5500 — short premium (far OTM, tight spread)
    # Mean premium 4.71, std 2.21, spread 1.11
    # Far OTM → low delta → safe from spot drift unlike ITM options
    # =====================================================
    def get_premium_5500(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.V5500_STRIKE)
        return option_mid - intrinsic

    def trade_5500(self, order_depth, position, underlying_mid, imbalance,
                   sell_mult=1.0, thr_mult=1.0, imb_bump=0.0,
                   max_short_override=None):
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

        sell_threshold = self.V5500_SELL_THRESHOLD * thr_mult
        strong_sell_threshold = self.V5500_STRONG_SELL_THRESHOLD * thr_mult
        block_imb = self.V5500_BLOCK_SELL_IMBALANCE + imb_bump
        normal_size = int(round(self.V5500_NORMAL_SELL_SIZE * sell_mult))
        strong_size = int(round(self.V5500_STRONG_SELL_SIZE * sell_mult))
        max_short = max_short_override if max_short_override is not None else self.V5500_MAX_SHORT

        # Cover short when premium reverts to cheap level
        if position < 0 and premium <= self.V5500_COVER_THRESHOLD:
            qty = min(self.V5500_COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty

        # Sell when premium spikes — same two-threshold gate as 5300/5400
        if position > max_short:
            can_sell = imbalance <= block_imb

            if premium >= sell_threshold and imbalance <= 0 + imb_bump:
                sell_size = normal_size
                if premium >= strong_sell_threshold:
                    sell_size = strong_size
                qty = min(sell_size, bid_volume, sell_capacity,
                          position - max_short)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))

            elif premium >= strong_sell_threshold and imbalance <= 0.15 + imb_bump:
                qty = min(strong_size, bid_volume, sell_capacity,
                          position - max_short)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))

        return orders

    # =====================================================
    # VEV_6000 / VEV_6500 — zero-bid settlement lottery
    # =====================================================
    def trade_zero_lottery(self, product, order_depth, position):
        orders = []
        limit = self.LIMITS[product]
        remaining = limit - position
        if remaining > 0:
            orders.append(Order(product, 0, remaining))
        return orders

    # =====================================================
    # Drawdown breaker — state, MTM, halt logic
    # =====================================================
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
        self.cp_last_ts = d.get("cp_last_ts", -1)

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
            "cp_last_ts": self.cp_last_ts,
        })

    # =====================================================
    # Counterparty flow tracking (HAWK)
    # =====================================================
    def _ingest_market_trades(self, state):
        """Append every NEW market_trade (bot-to-bot) into per-product per-counterparty
        flow log. signed_qty > 0 means the counterparty BOUGHT, < 0 means SOLD.
        We treat trade.buyer as one counterparty (bought +qty) and trade.seller as
        another counterparty (sold -qty)."""
        if not self.CP_ENABLED:
            return
        if not hasattr(state, "market_trades") or state.market_trades is None:
            return

        new_last = self.cp_last_ts
        for product, trades in state.market_trades.items():
            if product not in self.CP_VOUCHER_PRODUCTS:
                # only track flows for products we will act on
                continue
            for trade in trades:
                if trade.timestamp <= self.cp_last_ts:
                    continue
                qty = int(trade.quantity)
                if qty <= 0:
                    continue
                if trade.timestamp > new_last:
                    new_last = trade.timestamp
                buyer = trade.buyer or ""
                seller = trade.seller or ""
                if buyer and buyer != "SUBMISSION":
                    self.cp_flow.setdefault(product, {}).setdefault(buyer, []).append(
                        [trade.timestamp, qty]
                    )
                if seller and seller != "SUBMISSION":
                    self.cp_flow.setdefault(product, {}).setdefault(seller, []).append(
                        [trade.timestamp, -qty]
                    )

        self.cp_last_ts = new_last
        # Garbage-collect entries outside window
        cutoff = state.timestamp - self.CP_WINDOW_TS
        for product, by_cp in list(self.cp_flow.items()):
            for cp, lst in list(by_cp.items()):
                lst[:] = [e for e in lst if e[0] >= cutoff]
                if not lst:
                    del by_cp[cp]
            if not by_cp:
                del self.cp_flow[product]

    def _cp_voucher_boost(self, product, current_ts):
        """Return (sell_size_mult, threshold_mult, imb_bump, max_short_extend, reason)
        based on recent counterparty activity in this voucher.
        max_short_extend is a multiplicative factor on the absolute MAX_SHORT
        (e.g. 1.5 means allow extending by 50%, capped at LIMIT).
        Neutral = (1.0, 1.0, 0.0, 1.0, '').
        Identifies dynamic profiles from the rolling flow log — no hard-coded names.
        """
        if not self.CP_ENABLED:
            return 1.0, 1.0, 0.0, 1.0, ""
        by_cp = self.cp_flow.get(product, {})
        if not by_cp:
            return 1.0, 1.0, 0.0, 1.0, ""

        sell_mult = 1.0
        thr_mult = 1.0
        imb_bump = 0.0
        max_short_extend = 1.0
        reasons = []

        for cp, entries in by_cp.items():
            if not entries:
                continue
            buy_qty = sum(q for _, q in entries if q > 0)
            sell_qty = -sum(q for _, q in entries if q < 0)
            total = buy_qty + sell_qty
            if total < self.CP_NOISE_QTY_MIN:
                continue
            net = buy_qty - sell_qty
            ratio = net / total  # in [-1, +1]

            last_ts = max(e[0] for e in entries)
            fresh = (current_ts - last_ts) <= self.CP_NOISE_RECENT_TS

            if ratio >= self.CP_NOISE_RATIO and fresh and buy_qty >= self.CP_NOISE_QTY_MIN:
                sell_mult = max(sell_mult, self.CP_NOISE_SELL_MULT)
                thr_mult = min(thr_mult, self.CP_NOISE_THRESHOLD_REL)
                imb_bump = max(imb_bump, self.CP_NOISE_BLOCK_IMB_BUMP)
                max_short_extend = max(max_short_extend, self.CP_NOISE_MAX_SHORT_EXTEND)
                reasons.append(f"nb:{cp}({buy_qty}/{total})")

            elif ratio <= -self.CP_NOISE_RATIO and fresh and sell_qty >= self.CP_NOISE_QTY_MIN:
                sell_mult = max(sell_mult, self.CP_SMART_SELL_MULT)
                thr_mult = min(thr_mult, self.CP_SMART_THRESHOLD_REL)
                max_short_extend = max(max_short_extend, self.CP_SMART_MAX_SHORT_EXTEND)
                reasons.append(f"ss:{cp}({sell_qty}/{total})")

        return sell_mult, thr_mult, imb_bump, max_short_extend, ",".join(reasons)

    def _update_cash_from_trades(self, state):
        # Apply every own_trade we haven't already counted.
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
            # Lottery products and anything else are not in the breaker set.
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

        # 1. Absolute MTM floor
        floor = self.DRAWDOWN_LIMIT[product]
        if mtm < floor:
            self.halted[product] = True
            self.halt_reason[product] = f"abs_dd mtm={mtm:.0f}<{floor}"
            logger.print(
                f"[BREAKER] {product} HALT abs_dd mtm={mtm:.0f} pos={position} mid={mid:.1f}"
            )
            return

        # 2. Regime detection (mean-reverters only — HYDROGEL & EXTRACT)
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