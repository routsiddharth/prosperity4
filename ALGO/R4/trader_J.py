import json
import math
import os
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
        orders: dict,
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

    def compress_state(self, state: TradingState, trader_data: str):
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

    def compress_listings(self, listings):
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths):
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades):
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [trade.symbol, trade.price, trade.quantity,
                     trade.buyer, trade.seller, trade.timestamp]
                )
        return compressed

    def compress_observations(self, observations):
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice, observation.askPrice,
                observation.transportFees, observation.exportTariff,
                observation.importTariff, observation.sugarPrice,
                observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders):
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value):
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value, max_length):
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


# Defensive Quote Widener parameters (env-overridable)
THRESHOLD = float(os.environ.get("THRESHOLD", "0.65"))
WIDEN_TICKS = int(os.environ.get("WIDEN_TICKS", "2"))
LOOKBACK_TS = int(os.environ.get("LOOKBACK_TS", "100000"))  # 1000 ticks * 100 ts/tick
MIN_TRADES = int(os.environ.get("MIN_TRADES", "3"))
SKIP_TAKE = int(os.environ.get("SKIP_TAKE", "1"))  # 1 = skip toxic-side take


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

    def __init__(self):
        self.premium_ema = {}
        self.cash = {}
        self.peak_mtm = {}
        self.halted = {}
        self.halt_reason = {}
        self.regime_started_ts = {}
        self.last_processed_trade_ts = -1
        # Counterparty flow window: per-product list of (ts, buyer, seller, qty)
        # We only need recent N ticks; trim each call.
        self.cp_flow = {}  # product -> list[[ts, buyer, seller, qty]]

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
                product, state.order_depths[product], position, state.timestamp,
            )

        if self.halted.get(self.EXTRACT):
            for opt in (self.VEV4000, self.OPTION, self.V5400, self.V5500, self.V6000, self.V6500):
                if not self.halted.get(opt):
                    self.halted[opt] = True
                    self.halt_reason[opt] = "extract_halt_propagated"

        # HYDROGEL
        if self.HYDROGEL in state.order_depths:
            depth = state.order_depths[self.HYDROGEL]
            position = int(state.position.get(self.HYDROGEL, 0))
            if self.halted.get(self.HYDROGEL):
                orders_by_product[self.HYDROGEL] = self._flatten(self.HYDROGEL, depth, position)
            elif depth.buy_orders and depth.sell_orders:
                orders_by_product[self.HYDROGEL] = self.trade_hydrogel(
                    self.HYDROGEL, depth, position, state.timestamp
                )

        # EXTRACT
        if self.EXTRACT in state.order_depths:
            depth = state.order_depths[self.EXTRACT]
            position = int(state.position.get(self.EXTRACT, 0))
            if self.halted.get(self.EXTRACT):
                orders_by_product[self.EXTRACT] = self._flatten(self.EXTRACT, depth, position)
            elif depth.buy_orders and depth.sell_orders:
                orders_by_product[self.EXTRACT] = self.trade_extract(
                    self.EXTRACT, depth, position, state.timestamp
                )

        if self.VEV4000 in state.order_depths:
            depth_4000 = state.order_depths[self.VEV4000]
            position_4000 = int(state.position.get(self.VEV4000, 0))
            if self.halted.get(self.VEV4000):
                orders_by_product[self.VEV4000] = self._flatten(self.VEV4000, depth_4000, position_4000)
            elif underlying_mid is not None and depth_4000.buy_orders and depth_4000.sell_orders:
                orders_by_product[self.VEV4000] = self.trade_4000(depth_4000, position_4000, underlying_mid)

        if self.OPTION in state.order_depths:
            option_depth = state.order_depths[self.OPTION]
            option_position = int(state.position.get(self.OPTION, 0))
            if self.halted.get(self.OPTION):
                orders_by_product[self.OPTION] = self._flatten(self.OPTION, option_depth, option_position)
            elif underlying_mid is not None and option_depth.buy_orders and option_depth.sell_orders:
                orders_by_product[self.OPTION] = self.trade_5300(
                    option_depth, option_position, underlying_mid, imbalance,
                )

        if self.V5400 in state.order_depths:
            v5400_depth = state.order_depths[self.V5400]
            v5400_position = int(state.position.get(self.V5400, 0))
            if self.halted.get(self.V5400):
                orders_by_product[self.V5400] = self._flatten(self.V5400, v5400_depth, v5400_position)
            elif underlying_mid is not None and v5400_depth.buy_orders and v5400_depth.sell_orders:
                orders_by_product[self.V5400] = self.trade_5400(
                    v5400_depth, v5400_position, underlying_mid, imbalance,
                )

        if self.V5500 in state.order_depths:
            v5500_depth = state.order_depths[self.V5500]
            v5500_position = int(state.position.get(self.V5500, 0))
            if self.halted.get(self.V5500):
                orders_by_product[self.V5500] = self._flatten(self.V5500, v5500_depth, v5500_position)
            elif underlying_mid is not None and v5500_depth.buy_orders and v5500_depth.sell_orders:
                orders_by_product[self.V5500] = self.trade_5500(
                    v5500_depth, v5500_position, underlying_mid, imbalance,
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

    # =====================================================
    # Counterparty flow tracking
    # =====================================================
    def _update_cp_flow(self, state):
        """Track recent market_trades; trim outside lookback window."""
        cutoff = state.timestamp - LOOKBACK_TS
        for product, trades in state.market_trades.items():
            buf = self.cp_flow.setdefault(product, [])
            for t in trades:
                # market_trades only — these are bot-to-bot in the live env.
                # Buyer/seller are counterparty names (or "" placeholder).
                buf.append([t.timestamp, t.buyer or "", t.seller or "", int(t.quantity)])
            # Trim
            self.cp_flow[product] = [r for r in buf if r[0] >= cutoff]

    def _toxic_flags(self, product):
        """
        Returns (toxic_buyer, toxic_seller).
        toxic_buyer=True  -> some single name dominates BUY-side volume in window.
                              They are leaning bullish (aggressive on the ask) -> we
                              should widen our ASK and skip ask-take.
        toxic_seller=True -> dominant name on SELL side -> widen BID, skip bid-take.
        """
        rows = self.cp_flow.get(product, [])
        if not rows:
            return False, False

        buy_by_name = {}    # name -> (vol, count)  buyer side
        sell_by_name = {}   # name -> (vol, count)  seller side
        total_buy = 0
        total_sell = 0
        for ts, buyer, seller, qty in rows:
            if buyer:
                v, c = buy_by_name.get(buyer, (0, 0))
                buy_by_name[buyer] = (v + qty, c + 1)
                total_buy += qty
            if seller:
                v, c = sell_by_name.get(seller, (0, 0))
                sell_by_name[seller] = (v + qty, c + 1)
                total_sell += qty

        toxic_buyer = False
        if total_buy > 0 and buy_by_name:
            top_name, (top_vol, top_cnt) = max(buy_by_name.items(), key=lambda kv: kv[1][0])
            if top_cnt >= MIN_TRADES and (top_vol / total_buy) > THRESHOLD:
                toxic_buyer = True

        toxic_seller = False
        if total_sell > 0 and sell_by_name:
            top_name, (top_vol, top_cnt) = max(sell_by_name.items(), key=lambda kv: kv[1][0])
            if top_cnt >= MIN_TRADES and (top_vol / total_sell) > THRESHOLD:
                toxic_seller = True

        return toxic_buyer, toxic_seller

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
    # HYDROGEL_PACK — defensive widener
    # =====================================================
    def trade_hydrogel(self, product, order_depth, position, timestamp):
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

        # NOTE: fair_value is left UNTOUCHED by counterparty info.
        toxic_buyer, toxic_seller = self._toxic_flags(product)

        buy_capacity = limit - position
        sell_capacity = limit + position

        # ---- Take side (with optional defensive skip) ----
        # Toxic buyer = bullish flow concentrated -> they're hitting asks. We
        # are buying when an ask is cheap; if a strong bullish info trader
        # is around, the cheap ask may be stale. Skip our ask-take.
        for ask_price, ask_volume_raw in sorted(order_depth.sell_orders.items()):
            ask_volume = -ask_volume_raw
            if ask_price <= fair_value - self.HYDROGEL_TAKE_WIDTH and buy_capacity > 0:
                if SKIP_TAKE and toxic_buyer:
                    continue
                buy_throttle = max(0.0, 1.0 - max(0.0, position_skew) ** self.HYDROGEL_INV_TAKE_THROTTLE_EXP)
                throttled_take_size = max(1, int(self.HYDROGEL_TAKE_SIZE * buy_throttle))
                qty = min(throttled_take_size, ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    buy_capacity -= qty

        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price >= fair_value + self.HYDROGEL_TAKE_WIDTH and sell_capacity > 0:
                if SKIP_TAKE and toxic_seller:
                    continue
                sell_throttle = max(0.0, 1.0 - max(0.0, -position_skew) ** self.HYDROGEL_INV_TAKE_THROTTLE_EXP)
                throttled_take_size = max(1, int(self.HYDROGEL_TAKE_SIZE * sell_throttle))
                qty = min(throttled_take_size, bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    sell_capacity -= qty

        # ---- Quote side ----
        passive_edge_bid = self.HYDROGEL_PASSIVE_EDGE
        passive_edge_ask = self.HYDROGEL_PASSIVE_EDGE
        if abs(mid - self.HYDROGEL_BASE_FAIR) < self.HYDROGEL_NEAR_FAIR_ZONE:
            passive_edge_bid = self.HYDROGEL_NEAR_FAIR_PASSIVE_EDGE
            passive_edge_ask = self.HYDROGEL_NEAR_FAIR_PASSIVE_EDGE

        # Defensive widener: when toxic flow on a side, pull our quote on the
        # SAME side away (widen). We are SELLing on the ask -> if buyers are
        # leaning informed bullish, widen our ASK so we don't get picked off.
        if toxic_buyer:
            passive_edge_ask += WIDEN_TICKS
        if toxic_seller:
            passive_edge_bid += WIDEN_TICKS

        bid_price = math.floor(fair_value - passive_edge_bid)
        ask_price = math.ceil(fair_value + passive_edge_ask)

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
    # VEV_4000 market making (unchanged)
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

    # =====================================================
    # VELVETFRUIT_EXTRACT — defensive widener
    # =====================================================
    def trade_extract(self, product, order_depth, position, timestamp):
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

        toxic_buyer, toxic_seller = self._toxic_flags(product)

        buy_capacity = limit - position
        sell_capacity = limit + position

        for ask_price, ask_volume_raw in sorted(order_depth.sell_orders.items()):
            ask_volume = -ask_volume_raw
            if ask_price <= fair_value - self.EXTRACT_TAKE_WIDTH and buy_capacity > 0:
                if SKIP_TAKE and toxic_buyer:
                    continue
                qty = min(self.EXTRACT_TAKE_SIZE, ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    buy_capacity -= qty

        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price >= fair_value + self.EXTRACT_TAKE_WIDTH and sell_capacity > 0:
                if SKIP_TAKE and toxic_seller:
                    continue
                qty = min(self.EXTRACT_TAKE_SIZE, bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    sell_capacity -= qty

        passive_edge_bid = self.EXTRACT_PASSIVE_EDGE
        passive_edge_ask = self.EXTRACT_PASSIVE_EDGE
        if abs(mid - self.EXTRACT_BASE_FAIR) < self.EXTRACT_NEAR_FAIR_ZONE:
            passive_edge_bid = self.EXTRACT_NEAR_FAIR_PASSIVE_EDGE
            passive_edge_ask = self.EXTRACT_NEAR_FAIR_PASSIVE_EDGE

        if toxic_buyer:
            passive_edge_ask += WIDEN_TICKS
        if toxic_seller:
            passive_edge_bid += WIDEN_TICKS

        bid_price = math.floor(fair_value - passive_edge_bid)
        ask_price = math.ceil(fair_value + passive_edge_ask)

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

    # ============ unchanged voucher logic ============
    def get_premium_5300(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.STRIKE)
        return option_mid - intrinsic

    def trade_5300(self, order_depth, position, underlying_mid, imbalance):
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

        if position < 0 and premium <= self.COVER_THRESHOLD:
            qty = min(self.COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty

        if position > self.MAX_SHORT_5300:
            can_sell = imbalance <= self.BLOCK_SELL_IMBALANCE
            if premium >= self.SELL_THRESHOLD and imbalance <= 0:
                sell_size = self.NORMAL_SELL_SIZE
                if premium >= self.STRONG_SELL_THRESHOLD:
                    sell_size = self.STRONG_SELL_SIZE
                qty = min(sell_size, bid_volume, sell_capacity,
                          position - self.MAX_SHORT_5300)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            elif premium >= self.STRONG_SELL_THRESHOLD and imbalance <= 0.15:
                qty = min(self.STRONG_SELL_SIZE, bid_volume, sell_capacity,
                          position - self.MAX_SHORT_5300)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
        return orders

    def get_premium_5400(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.V5400_STRIKE)
        return option_mid - intrinsic

    def trade_5400(self, order_depth, position, underlying_mid, imbalance):
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

        if position < 0 and premium <= self.V5400_COVER_THRESHOLD:
            qty = min(self.V5400_COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty

        if position > self.V5400_MAX_SHORT:
            can_sell = imbalance <= self.V5400_BLOCK_SELL_IMBALANCE
            if premium >= self.V5400_SELL_THRESHOLD and imbalance <= 0:
                sell_size = self.V5400_NORMAL_SELL_SIZE
                if premium >= self.V5400_STRONG_SELL_THRESHOLD:
                    sell_size = self.V5400_STRONG_SELL_SIZE
                qty = min(sell_size, bid_volume, sell_capacity,
                          position - self.V5400_MAX_SHORT)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            elif premium >= self.V5400_STRONG_SELL_THRESHOLD and imbalance <= 0.15:
                qty = min(self.V5400_STRONG_SELL_SIZE, bid_volume, sell_capacity,
                          position - self.V5400_MAX_SHORT)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
        return orders

    def get_premium_5500(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.V5500_STRIKE)
        return option_mid - intrinsic

    def trade_5500(self, order_depth, position, underlying_mid, imbalance):
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

        if position < 0 and premium <= self.V5500_COVER_THRESHOLD:
            qty = min(self.V5500_COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty

        if position > self.V5500_MAX_SHORT:
            can_sell = imbalance <= self.V5500_BLOCK_SELL_IMBALANCE
            if premium >= self.V5500_SELL_THRESHOLD and imbalance <= 0:
                sell_size = self.V5500_NORMAL_SELL_SIZE
                if premium >= self.V5500_STRONG_SELL_THRESHOLD:
                    sell_size = self.V5500_STRONG_SELL_SIZE
                qty = min(sell_size, bid_volume, sell_capacity,
                          position - self.V5500_MAX_SHORT)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            elif premium >= self.V5500_STRONG_SELL_THRESHOLD and imbalance <= 0.15:
                qty = min(self.V5500_STRONG_SELL_SIZE, bid_volume, sell_capacity,
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

    # ============ persistence + breaker ============
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
