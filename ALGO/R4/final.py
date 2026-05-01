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
    # HYDROGEL_PACK
    # =====================================================
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
    # VEV_5400 short premium
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
    # =====================================================
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

    # =====================================================
    # VEV_6000 / VEV_6500
    # =====================================================
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

    # =====================================================
    # Counterparty role detection (the EXPLOIT)
    # =====================================================
    # Products on which we run role detection + exploit.
    EXPLOIT_PRODUCTS = ("VEV_5300", "VEV_5400", "VEV_5500")

    # Minimum trades observed before we trust a (name, product) classification.
    ROLE_MIN_SAMPLES = 20
    # Buy-share threshold above which a name is labeled noise_buyer.
    ROLE_BUY_THRESHOLD = 0.85
    # How recent the noise-buyer activity must be to fire the exploit, in ts units.
    # state.timestamp advances by 100 per tick; 5000 = 50 ticks lookback.
    ROLE_RECENT_TS = 5000

    # When noise buyer detected on this product:
    # Post extra resting SELL orders one tick INSIDE/ABOVE the best ask, at a
    # size proportional to remaining short capacity. The noise buyer crosses
    # the spread to lift offers, so we want our quotes sitting on the offer
    # rather than hitting their bid at a lower price. We *add* this on top of
    # baseline behavior — baseline still fires when premium thresholds break.
    EXPLOIT_QUOTE_OFFSET = {     # ticks ABOVE best_ask to rest (0 = at best_ask)
        "VEV_5300": 0,
        "VEV_5400": 0,
        "VEV_5500": 0,
    }
    EXPLOIT_QUOTE_SIZE = {       # base size of opportunistic offer
        "VEV_5300": 200,
        "VEV_5400": 100,
        "VEV_5500": 60,
    }
    # Minimum premium to consider posting an opportunistic offer.
    # Below cover threshold so we never sell into mean reversion; above 0
    # so the offer is always at premium > 0.
    EXPLOIT_MIN_PREMIUM = {
        "VEV_5300": 25.0,
        "VEV_5400": 6.0,
        "VEV_5500": 2.0,
    }

    # ---- Master toggle for the counterparty exploit ----
    # When False, _noise_buyer_active() always returns False so the exploit
    # add-on at the end of trade_5300 / trade_5400 / trade_5500 never fires
    # and the trader degrades to baseline behavior.
    CP_EXPLOIT_ENABLED = True

    # Diagnostic-only: if True, only treat the literal name "Mark 01" as the
    # noise buyer (used during the debate to verify name-agnostic detection
    # produces the same PnL as hard-coded). Default False — the edge is
    # structural, not name-specific. Do NOT enable for live submission.
    EXPLOIT_HARDCODE_NAME = False
    EXPLOIT_HARDCODE_LABEL = "Mark 01"

    # =====================================================
    # Insider-bot detector + conditional copy-trader
    # =====================================================
    # General-purpose detector: any counterparty whose trades systematically
    # precede favorable mid-price moves becomes "insider" once stats clear a
    # confidence bar. Mirrors a fraction of their flow when they trade.
    # Name-agnostic: keyed by whatever string appears in Trade.buyer/seller.
    #
    # Forward edge for a trade at ts in product p by counterparty c, side s
    # (+1 buy, -1 sell):
    #
    #     forward_edge(t, K) = s * (mid[t + K] - mid[t])
    #
    # Using mid drift rather than (mid - trade_price) strips out the
    # half-spread bias from market-makers — only directional alpha shows up.

    INSIDER_MIRROR_ENABLED = True

    INSIDER_PRODUCTS = (
        "HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_4000",
        "VEV_5300", "VEV_5400", "VEV_5500",
    )
    # Forward horizons in ts units (state.timestamp steps by 100).
    INSIDER_HORIZONS_TS = (500, 2000, 10000)   # = 5 / 20 / 100 ticks
    # Min observations on a (name, product, K) before we trust the t-stat.
    INSIDER_N_MIN = 30
    # Min mean forward_edge per unit. A practical floor — statistical
    # significance alone isn't enough if the magnitude is microscopic.
    INSIDER_EDGE_MIN = 1.0
    # One-sided z threshold. 2.33 ≈ α = 0.01.
    INSIDER_T_THRESHOLD = 2.33
    # Number of horizons that must independently cross the threshold for
    # the (name, product) to be flagged. Multi-horizon stability rejects
    # single-K cherry-picks.
    INSIDER_HORIZONS_REQUIRED = 2

    # Mirror sizing: never copy 100% — we don't want our blow-up correlated
    # with a single bot's losing day if the regime flips.
    INSIDER_PROPORTION = 0.30
    # Mirror only if insider's most recent trade is within this many ts.
    INSIDER_K_RECENT_TS = 500   # 5 ticks
    # Hard per-tick mirror cap regardless of insider's trade size.
    INSIDER_MAX_PER_TICK = 25
    # Skip mirroring if book is wider than this (pricing too uncertain).
    INSIDER_MAX_SPREAD = {
        "HYDROGEL_PACK":       50,
        "VELVETFRUIT_EXTRACT": 50,
        "VEV_4000":            40,
        "VEV_5300":            40,
        "VEV_5400":            30,
        "VEV_5500":            25,
    }
    # Bound on persisted state to keep traderData small.
    INSIDER_MID_HISTORY_MAX = 200       # entries per product
    INSIDER_PENDING_QUEUE_MAX = 200     # entries per product

    def __init__(self):
        self.premium_ema = {}
        self.cash = {}
        self.peak_mtm = {}
        self.halted = {}
        self.halt_reason = {}
        self.regime_started_ts = {}
        self.last_processed_trade_ts = -1

        # counterparty stats: {product: {name: [buy_qty, sell_qty]}}
        self.cp_stats = {}
        # last ts a name appeared as buyer on a product: {product: {name: ts}}
        self.cp_last_buy_ts = {}
        # dedup market trade ids — store by (sym, ts, price, qty, buyer, seller)
        self.cp_seen_ts = {}  # product -> last seen market trade ts processed

        # Insider tracker state.
        # mid_history[product] = list[(ts, mid)] — chronological, bounded.
        self.mid_history = {}
        # pending_trades[product] = list[[ts, name, side, price, qty, eval_mask]]
        # eval_mask is an int bit per horizon index in INSIDER_HORIZONS_TS.
        # When all bits set, trade is fully evaluated and may be evicted.
        self.pending_trades = {}
        # insider_edge[product][name][str(K)] = [count, sum_edge, sum_edge_sq]
        self.insider_edge = {}
        # insider_seen_ts[product] = highest market-trade ts ingested by tracker
        self.insider_seen_ts = {}
        # insider_last_trade[product] = (ts, name, side, qty, price)
        # — most recent ingested market trade per product, used as the mirror trigger.
        self.insider_last_trade = {}

    def run(self, state: TradingState):
        self._restore_state(state.traderData)
        self._update_cash_from_trades(state)
        self._update_counterparty_stats(state)
        self._update_insider_state(state)

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

        # HYDROGEL
        if self.HYDROGEL in state.order_depths:
            depth = state.order_depths[self.HYDROGEL]
            position = int(state.position.get(self.HYDROGEL, 0))
            if self.halted.get(self.HYDROGEL):
                orders_by_product[self.HYDROGEL] = self._flatten(self.HYDROGEL, depth, position)
            elif depth.buy_orders and depth.sell_orders:
                orders_by_product[self.HYDROGEL] = self.trade_hydrogel(self.HYDROGEL, depth, position)

        # EXTRACT
        if self.EXTRACT in state.order_depths:
            depth = state.order_depths[self.EXTRACT]
            position = int(state.position.get(self.EXTRACT, 0))
            if self.halted.get(self.EXTRACT):
                orders_by_product[self.EXTRACT] = self._flatten(self.EXTRACT, depth, position)
            elif depth.buy_orders and depth.sell_orders:
                orders_by_product[self.EXTRACT] = self.trade_extract(self.EXTRACT, depth, position)

        # VEV_4000
        if self.VEV4000 in state.order_depths:
            depth_4000 = state.order_depths[self.VEV4000]
            position_4000 = int(state.position.get(self.VEV4000, 0))
            if self.halted.get(self.VEV4000):
                orders_by_product[self.VEV4000] = self._flatten(self.VEV4000, depth_4000, position_4000)
            elif underlying_mid is not None and depth_4000.buy_orders and depth_4000.sell_orders:
                orders_by_product[self.VEV4000] = self.trade_4000(depth_4000, position_4000, underlying_mid)

        # VEV_5300
        if self.OPTION in state.order_depths:
            option_depth = state.order_depths[self.OPTION]
            option_position = int(state.position.get(self.OPTION, 0))
            if self.halted.get(self.OPTION):
                orders_by_product[self.OPTION] = self._flatten(self.OPTION, option_depth, option_position)
            elif underlying_mid is not None and option_depth.buy_orders and option_depth.sell_orders:
                orders_by_product[self.OPTION] = self.trade_5300(
                    option_depth, option_position, underlying_mid, imbalance, state.timestamp,
                )

        # VEV_5400
        if self.V5400 in state.order_depths:
            v5400_depth = state.order_depths[self.V5400]
            v5400_position = int(state.position.get(self.V5400, 0))
            if self.halted.get(self.V5400):
                orders_by_product[self.V5400] = self._flatten(self.V5400, v5400_depth, v5400_position)
            elif underlying_mid is not None and v5400_depth.buy_orders and v5400_depth.sell_orders:
                orders_by_product[self.V5400] = self.trade_5400(
                    v5400_depth, v5400_position, underlying_mid, imbalance, state.timestamp,
                )

        # VEV_5500
        if self.V5500 in state.order_depths:
            v5500_depth = state.order_depths[self.V5500]
            v5500_position = int(state.position.get(self.V5500, 0))
            if self.halted.get(self.V5500):
                orders_by_product[self.V5500] = self._flatten(self.V5500, v5500_depth, v5500_position)
            elif underlying_mid is not None and v5500_depth.buy_orders and v5500_depth.sell_orders:
                orders_by_product[self.V5500] = self.trade_5500(
                    v5500_depth, v5500_position, underlying_mid, imbalance, state.timestamp,
                )

        # 6000/6500
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

        # Insider mirror — additive on top of every product's baseline orders.
        # Skipped silently if INSIDER_MIRROR_ENABLED is False or no signal fired.
        if self.INSIDER_MIRROR_ENABLED:
            for product in self.INSIDER_PRODUCTS:
                if product not in state.order_depths:
                    continue
                if self.halted.get(product):
                    continue
                depth = state.order_depths[product]
                if not depth.buy_orders or not depth.sell_orders:
                    continue
                position = int(state.position.get(product, 0))
                existing = orders_by_product.get(product, [])
                mirror = self._compute_insider_mirror(
                    product, depth, position, state.timestamp, existing
                )
                if mirror:
                    orders_by_product.setdefault(product, []).extend(mirror)

        # Diagnostic: emit insider scores periodically (every 50000 ts).
        if state.timestamp % 50000 == 0:
            for p in self.INSIDER_PRODUCTS:
                edge_root = self.insider_edge.get(p, {})
                for nm, by_K in edge_root.items():
                    passes, t_max = self._insider_score(p, nm)
                    n_short = (by_K.get(str(self.INSIDER_HORIZONS_TS[0])) or [0])[0]
                    if passes or t_max > 1.5:
                        logger.print(
                            f"[INSIDER ts={state.timestamp}] {p} {nm} "
                            f"n_short={n_short} t_max={t_max:.2f} flag={passes}"
                        )

        conversions = 0
        trader_data = self._serialize_state()

        logger.flush(state, orders_by_product, conversions, trader_data)
        return orders_by_product, conversions, trader_data

    # =====================================================
    # Counterparty role detection
    # =====================================================
    def _update_counterparty_stats(self, state):
        """Walk state.market_trades for the 3 exploit products and accumulate
        per-(name, product) buy/sell quantity. Also record the most recent ts
        each name acted as a BUYER per product, for the freshness gate.

        We dedup by tracking the highest market-trade ts processed per product,
        same approach used for own_trades cash bookkeeping.
        """
        for product in self.EXPLOIT_PRODUCTS:
            trades = state.market_trades.get(product, []) if state.market_trades else []
            if not trades:
                continue

            if product not in self.cp_stats:
                self.cp_stats[product] = {}
            if product not in self.cp_last_buy_ts:
                self.cp_last_buy_ts[product] = {}

            last_ts = self.cp_seen_ts.get(product, -1)
            new_last_ts = last_ts

            for t in trades:
                # Only process trades strictly newer than the last processed ts.
                if t.timestamp <= last_ts:
                    continue
                if t.timestamp > new_last_ts:
                    new_last_ts = t.timestamp

                qty = abs(int(t.quantity))
                buyer = t.buyer or ""
                seller = t.seller or ""

                # Skip own trades (already counted elsewhere) — we want
                # behavior of EXTERNAL counterparties.
                if buyer and buyer != "SUBMISSION":
                    rec = self.cp_stats[product].get(buyer)
                    if rec is None:
                        rec = [0, 0]
                        self.cp_stats[product][buyer] = rec
                    rec[0] += qty
                    self.cp_last_buy_ts[product][buyer] = t.timestamp

                if seller and seller != "SUBMISSION":
                    rec = self.cp_stats[product].get(seller)
                    if rec is None:
                        rec = [0, 0]
                        self.cp_stats[product][seller] = rec
                    rec[1] += qty

            self.cp_seen_ts[product] = new_last_ts

    def _is_noise_buyer(self, product, name):
        """Return True iff this counterparty has been classified as a noise
        buyer on this product based on accumulated stats."""
        if self.EXPLOIT_HARDCODE_NAME:
            return name == self.EXPLOIT_HARDCODE_LABEL

        stats = self.cp_stats.get(product, {})
        rec = stats.get(name)
        if not rec:
            return False
        buy, sell = rec
        total = buy + sell
        if total < self.ROLE_MIN_SAMPLES:
            return False
        return (buy / total) >= self.ROLE_BUY_THRESHOLD

    def _noise_buyer_active(self, product, current_ts):
        """Has any name classified as noise buyer for this product been the
        BUYER on a market trade within the last ROLE_RECENT_TS units?"""
        if not self.CP_EXPLOIT_ENABLED:
            return False
        last_buys = self.cp_last_buy_ts.get(product, {})
        if not last_buys:
            return False
        cutoff = current_ts - self.ROLE_RECENT_TS
        for name, ts in last_buys.items():
            if ts < cutoff:
                continue
            if self._is_noise_buyer(product, name):
                return True
        return False

    # =====================================================
    # Insider tracker — generic forward-edge detector
    # =====================================================
    def _update_insider_state(self, state):
        for product in self.INSIDER_PRODUCTS:
            depth = state.order_depths.get(product) if state.order_depths else None
            if not depth or not depth.buy_orders or not depth.sell_orders:
                continue
            mid = self.get_mid(depth)

            hist = self.mid_history.setdefault(product, [])
            if not hist or hist[-1][0] != state.timestamp:
                hist.append([state.timestamp, mid])
            if len(hist) > self.INSIDER_MID_HISTORY_MAX:
                del hist[: len(hist) - self.INSIDER_MID_HISTORY_MAX]

            trades = state.market_trades.get(product, []) if state.market_trades else []
            last_seen = self.insider_seen_ts.get(product, -1)
            new_last = last_seen
            queue = self.pending_trades.setdefault(product, [])

            for t in trades:
                if t.timestamp <= last_seen:
                    continue
                if t.timestamp > new_last:
                    new_last = t.timestamp

                buyer = t.buyer or ""
                seller = t.seller or ""
                qty = abs(int(t.quantity))
                price = float(t.price)

                if buyer and buyer != "SUBMISSION":
                    queue.append([t.timestamp, buyer, +1, price, qty, 0])
                    self.insider_last_trade[product] = (
                        t.timestamp, buyer, +1, qty, price,
                    )
                if seller and seller != "SUBMISSION":
                    queue.append([t.timestamp, seller, -1, price, qty, 0])
                    self.insider_last_trade[product] = (
                        t.timestamp, seller, -1, qty, price,
                    )

            self.insider_seen_ts[product] = new_last
            self._evaluate_pending(product, state.timestamp)

            if len(queue) > self.INSIDER_PENDING_QUEUE_MAX:
                del queue[: len(queue) - self.INSIDER_PENDING_QUEUE_MAX]

    def _evaluate_pending(self, product, current_ts):
        """Walk pending trades; for each (trade, horizon) not yet evaluated,
        if mid[ts + K] is available in mid_history, fold the forward_edge into
        the running stats. Drop trades whose every horizon has been evaluated
        AND whose age exceeds the largest horizon (cannot grow stats further)."""
        queue = self.pending_trades.get(product, [])
        hist = self.mid_history.get(product, [])
        if not queue or not hist:
            return

        # Quick lookup: ts -> mid (history is short and ordered, but dict beats
        # linear search on every horizon evaluation).
        mid_at = {ts: m for ts, m in hist}

        edge_root = self.insider_edge.setdefault(product, {})
        full_mask = (1 << len(self.INSIDER_HORIZONS_TS)) - 1
        max_K = max(self.INSIDER_HORIZONS_TS)

        keep = []
        for trade in queue:
            ts, name, side, _price, qty, mask = trade
            mid_origin = mid_at.get(ts)
            if mid_origin is None:
                # Mid for the trade's own ts not in history (we may have started
                # mid-sample). Without baseline mid, edge can't be measured —
                # let trade age out.
                if current_ts - ts <= max_K:
                    keep.append(trade)
                continue

            for i, K in enumerate(self.INSIDER_HORIZONS_TS):
                bit = 1 << i
                if mask & bit:
                    continue
                target_ts = ts + K
                future_mid = mid_at.get(target_ts)
                if future_mid is None:
                    continue
                edge = side * (future_mid - mid_origin)

                name_stats = edge_root.setdefault(name, {})
                key = str(K)
                rec = name_stats.get(key)
                if rec is None:
                    rec = [0, 0.0, 0.0]
                    name_stats[key] = rec
                rec[0] += 1
                rec[1] += edge
                rec[2] += edge * edge

                mask |= bit

            trade[5] = mask
            if mask != full_mask and current_ts - ts <= max_K:
                keep.append(trade)
            # else: fully evaluated or aged past the largest horizon → drop.

        self.pending_trades[product] = keep

    def _insider_score(self, product, name):
        """Return (passes, t_max) where passes is True iff the (name, product)
        meets sample-size + edge-magnitude + t-stat thresholds on at least
        INSIDER_HORIZONS_REQUIRED horizons. t_max is the max t-stat across
        qualifying horizons (used to scale mirror size)."""
        edge_root = self.insider_edge.get(product, {}).get(name)
        if not edge_root:
            return False, 0.0

        passing = 0
        t_max = 0.0
        for K in self.INSIDER_HORIZONS_TS:
            rec = edge_root.get(str(K))
            if not rec:
                continue
            count, s_e, s_e2 = rec
            if count < self.INSIDER_N_MIN:
                continue
            mean = s_e / count
            if mean < self.INSIDER_EDGE_MIN:
                continue
            var = max(0.0, s_e2 / count - mean * mean)
            stderr = (var / count) ** 0.5 if count > 0 else 0.0
            if stderr <= 0:
                continue
            t = mean / stderr
            if t >= self.INSIDER_T_THRESHOLD:
                passing += 1
                if t > t_max:
                    t_max = t

        return (passing >= self.INSIDER_HORIZONS_REQUIRED, t_max)

    def _compute_insider_mirror(self, product, depth, position, current_ts, existing):
        # Scan pending_trades in reverse chronological order for the most recent
        # trade by ANY counterparty that scores as insider. Using only the
        # globally-latest trade misses cases where an MM trades after an insider
        # within the same window.
        cutoff = current_ts - self.INSIDER_K_RECENT_TS
        queue = self.pending_trades.get(product, [])
        ts = name = None
        side = qty = 0
        t_max = 0.0
        for entry in reversed(queue):
            etrade_ts, ename, eside, _eprice, eqty, _mask = entry
            if etrade_ts < cutoff:
                break
            passes, t = self._insider_score(product, ename)
            if passes:
                ts, name, side, qty = etrade_ts, ename, eside, eqty
                t_max = t
                break
        if name is None:
            return []

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        spread = best_ask - best_bid
        max_spread = self.INSIDER_MAX_SPREAD.get(product, 50)
        if spread > max_spread:
            return []

        confidence = min(1.0, max(0.0, t_max / self.INSIDER_T_THRESHOLD - 1.0))
        if confidence <= 0:
            return []

        existing_buy = sum(o.quantity for o in existing if o.quantity > 0)
        existing_sell = sum(-o.quantity for o in existing if o.quantity < 0)

        # If baseline already wants the OPPOSITE side, defer to baseline —
        # contradicting signals mean the alpha isn't strong enough to override.
        if side == +1 and existing_sell > existing_buy and existing_sell > 0:
            return []
        if side == -1 and existing_buy > existing_sell and existing_buy > 0:
            return []

        limit = self.LIMITS.get(product, 0)
        scaled = int(qty * self.INSIDER_PROPORTION * confidence)
        scaled = min(scaled, self.INSIDER_MAX_PER_TICK)
        if scaled <= 0:
            return []

        if side == +1:
            headroom = max(0, limit - position - existing_buy)
            ask_volume = -depth.sell_orders[best_ask]
            qty_use = min(scaled, headroom, ask_volume)
            if qty_use <= 0:
                return []
            return [Order(product, best_ask, qty_use)]
        else:
            headroom = max(0, limit + position - existing_sell)
            bid_volume = depth.buy_orders[best_bid]
            qty_use = min(scaled, headroom, bid_volume)
            if qty_use <= 0:
                return []
            return [Order(product, best_bid, -qty_use)]

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
    # HYDROGEL_PACK
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
    # VEV_4000
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
    # EXTRACT
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
    # VEV_5300 — short premium with counterparty exploit
    # =====================================================
    def get_premium_5300(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.STRIKE)
        return option_mid - intrinsic

    def trade_5300(self, order_depth, position, underlying_mid, imbalance, current_ts):
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

        # ---- Baseline behavior (UNCHANGED) ----
        if position < 0 and premium <= self.COVER_THRESHOLD:
            qty = min(self.COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty
                sell_capacity += qty

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
                    sell_capacity -= qty
            elif premium >= self.STRONG_SELL_THRESHOLD and imbalance <= 0.15:
                qty = min(self.STRONG_SELL_SIZE, bid_volume, sell_capacity,
                          position - self.MAX_SHORT_5300)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    sell_capacity -= qty

        # ---- Counterparty exploit add-on ----
        # When a generically detected noise buyer has been active recently on
        # this product, post an OPPORTUNISTIC SELL one tick above best ask:
        # the noise buyer crosses the spread to lift offers, so we sell at
        # a richer price than baseline (which only hits bids at best_bid).
        if (sell_capacity > 0
                and position > self.MAX_SHORT_5300
                and self._noise_buyer_active(product, current_ts)
                and premium >= self.EXPLOIT_MIN_PREMIUM[product]):
            offset = self.EXPLOIT_QUOTE_OFFSET[product]
            quote_size = self.EXPLOIT_QUOTE_SIZE[product]
            quote_price = best_ask + offset
            qty = min(
                quote_size,
                sell_capacity,
                max(0, position - self.MAX_SHORT_5300),
            )
            if qty > 0:
                orders.append(Order(product, quote_price, -qty))

        return orders

    # =====================================================
    # VEV_5400 — short premium with counterparty exploit
    # =====================================================
    def get_premium_5400(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.V5400_STRIKE)
        return option_mid - intrinsic

    def trade_5400(self, order_depth, position, underlying_mid, imbalance, current_ts):
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

        # ---- Baseline behavior (UNCHANGED) ----
        if position < 0 and premium <= self.V5400_COVER_THRESHOLD:
            qty = min(self.V5400_COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty
                sell_capacity += qty

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
                    sell_capacity -= qty
            elif premium >= self.V5400_STRONG_SELL_THRESHOLD and imbalance <= 0.15:
                qty = min(self.V5400_STRONG_SELL_SIZE, bid_volume, sell_capacity,
                          position - self.V5400_MAX_SHORT)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    sell_capacity -= qty

        # ---- Counterparty exploit add-on ----
        if (sell_capacity > 0
                and position > self.V5400_MAX_SHORT
                and self._noise_buyer_active(product, current_ts)
                and premium >= self.EXPLOIT_MIN_PREMIUM[product]):
            offset = self.EXPLOIT_QUOTE_OFFSET[product]
            quote_size = self.EXPLOIT_QUOTE_SIZE[product]
            quote_price = best_ask + offset
            qty = min(
                quote_size,
                sell_capacity,
                max(0, position - self.V5400_MAX_SHORT),
            )
            if qty > 0:
                orders.append(Order(product, quote_price, -qty))

        return orders

    # =====================================================
    # VEV_5500 — short premium with counterparty exploit
    # =====================================================
    def get_premium_5500(self, option_depth, underlying_mid):
        option_mid = self.get_mid(option_depth)
        intrinsic = max(0, underlying_mid - self.V5500_STRIKE)
        return option_mid - intrinsic

    def trade_5500(self, order_depth, position, underlying_mid, imbalance, current_ts):
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

        # ---- Baseline behavior (UNCHANGED) ----
        if position < 0 and premium <= self.V5500_COVER_THRESHOLD:
            qty = min(self.V5500_COVER_SIZE, ask_volume, buy_capacity, -position)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_capacity -= qty
                sell_capacity += qty

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
                    sell_capacity -= qty
            elif premium >= self.V5500_STRONG_SELL_THRESHOLD and imbalance <= 0.15:
                qty = min(self.V5500_STRONG_SELL_SIZE, bid_volume, sell_capacity,
                          position - self.V5500_MAX_SHORT)
                if can_sell and qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    sell_capacity -= qty

        # ---- Counterparty exploit add-on ----
        if (sell_capacity > 0
                and position > self.V5500_MAX_SHORT
                and self._noise_buyer_active(product, current_ts)
                and premium >= self.EXPLOIT_MIN_PREMIUM[product]):
            offset = self.EXPLOIT_QUOTE_OFFSET[product]
            quote_size = self.EXPLOIT_QUOTE_SIZE[product]
            quote_price = best_ask + offset
            qty = min(
                quote_size,
                sell_capacity,
                max(0, position - self.V5500_MAX_SHORT),
            )
            if qty > 0:
                orders.append(Order(product, quote_price, -qty))

        return orders

    # =====================================================
    # VEV_6000 / VEV_6500
    # =====================================================
    def trade_zero_lottery(self, product, order_depth, position):
        orders = []
        limit = self.LIMITS[product]
        remaining = limit - position
        if remaining > 0:
            orders.append(Order(product, 0, remaining))
        return orders

    # =====================================================
    # State / breaker
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
        self.cp_stats = d.get("cp_stats", {})
        self.cp_last_buy_ts = d.get("cp_last_buy_ts", {})
        self.cp_seen_ts = d.get("cp_seen_ts", {})
        self.mid_history = d.get("mid_history", {})
        self.pending_trades = d.get("pending_trades", {})
        self.insider_edge = d.get("insider_edge", {})
        self.insider_seen_ts = d.get("insider_seen_ts", {})
        # JSON tuples come back as lists; normalize so unpacking still works.
        last_trade = d.get("insider_last_trade", {})
        self.insider_last_trade = {p: tuple(v) for p, v in last_trade.items()}

    def _serialize_state(self):
        return json.dumps({
            "premium_ema": self.premium_ema,
            "cash": self.cash,
            "peak_mtm": self.peak_mtm,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "regime_started_ts": self.regime_started_ts,
            "last_processed_trade_ts": self.last_processed_trade_ts,
            "cp_stats": self.cp_stats,
            "cp_last_buy_ts": self.cp_last_buy_ts,
            "cp_seen_ts": self.cp_seen_ts,
            "mid_history": self.mid_history,
            "pending_trades": self.pending_trades,
            "insider_edge": self.insider_edge,
            "insider_seen_ts": self.insider_seen_ts,
            "insider_last_trade": self.insider_last_trade,
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
