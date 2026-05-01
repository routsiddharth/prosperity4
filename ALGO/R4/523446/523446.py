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

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp, trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        return [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                for arr in trades.values() for t in arr]

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice, observation.askPrice, observation.transportFees,
                observation.exportTariff, observation.importTariff,
                observation.sugarPrice, observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        return [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr]

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
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


class Trader:
    DAY_TS = 1_000_000

    HYDROGEL = "HYDROGEL_PACK"
    EXTRACT  = "VELVETFRUIT_EXTRACT"

    LIMITS = {
        "HYDROGEL_PACK":       200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000":            300,
        "VEV_4500":            300,
        "VEV_5000":            300,
        "VEV_5100":            300,
        "VEV_5200":            300,
        "VEV_5300":            300,
        "VEV_5400":            300,
        "VEV_5500":            300,
    }

    # ══════════════════════════════════════════════════════════════════════
    # HYDROGEL parameters
    # ══════════════════════════════════════════════════════════════════════
    HYDROGEL_BASE_FAIR           = 9992
    HYDROGEL_QUOTE_SIZE          = 25
    HYDROGEL_TAKE_SIZE           = 25
    HYDROGEL_TAKE_WIDTH          = 8
    HYDROGEL_PASSIVE_EDGE        = 1
    HYDROGEL_INVENTORY_SKEW      = 23
    HYDROGEL_INVENTORY_SKEW_QUAD = 12
    HYDROGEL_IMBALANCE_SKEW      = 32
    HYDROGEL_INV_TAKE_THROTTLE   = 2
    HYDROGEL_NEAR_FAIR_ZONE      = 4
    HYDROGEL_NEAR_FAIR_EDGE      = 2
    HYDROGEL_FLATTEN_THRESHOLD   = 182
    HYDROGEL_FLATTEN_SIZE        = 8
    HYDROGEL_EXTREME_DISTANCE    = 50
    HYDROGEL_NORMAL_BASE_WEIGHT  = 0.75
    HYDROGEL_NORMAL_MID_WEIGHT   = 0.25
    HYDROGEL_EXTREME_BASE_WEIGHT = 0.65
    HYDROGEL_EXTREME_MID_WEIGHT  = 0.35

    # ══════════════════════════════════════════════════════════════════════
    # Signal configs — one entry per options product.
    #
    # signal        : product whose premium drives trade decisions
    # signal_strike : strike to compute signal intrinsic value
    # bucket        : product whose opening premium classifies the day
    # bucket_strike : strike to compute bucket intrinsic value
    # direction     : "follow" = long when premium high
    #                 "fade"   = short when premium high
    # ══════════════════════════════════════════════════════════════════════
    SIGNAL_CONFIGS = {

        # ── EXTRACT: VEV_5100 signal, follow ─────────────────────────────
        "VELVETFRUIT_EXTRACT": dict(
            signal="VEV_5100",    signal_strike=5100,
            bucket="VEV_5100",    bucket_strike=5100,
            direction="follow",
            target_long=200,      target_short=-200,
            sweep=3,
            high_open=18.0,       mid_open=8.0,
            high_low=13.0,        high_high=22.0,
            mid_low=7.0,          mid_high=19.5,
            low_low=5.5,          low_high=13.5,
            high_flatten=875_000, mid_flatten=975_000, low_flatten=None,
        ),

        # ── VEV_4000: VEV_5000 signal, follow ────────────────────────────
        "VEV_4000": dict(
            signal="VEV_5000",    signal_strike=5000,
            bucket="VEV_5000",    bucket_strike=5000,
            direction="follow",
            target_long=300,      target_short=-300,
            sweep=0,
            high_open=5.0,        mid_open=2.0,
            high_low=2.0,         high_high=9.0,
            mid_low=0.0,          mid_high=7.5,
            low_low=0.0,          low_high=6.5,
            high_flatten=800_000, mid_flatten=900_000, low_flatten=None,
        ),

        # ── VEV_4500: VEV_5200 signal, follow ────────────────────────────
        "VEV_4500": dict(
            signal="VEV_5200",    signal_strike=5200,
            bucket="VEV_5200",    bucket_strike=5200,
            direction="follow",
            target_long=300,      target_short=-300,
            sweep=0,
            high_open=45.0,       mid_open=30.0,
            high_low=36.5,        high_high=48.0,
            mid_low=28.5,         mid_high=54.0,
            low_low=27.5,         low_high=42.5,
            high_flatten=975_000, mid_flatten=975_000, low_flatten=None,
        ),

        # ── VEV_5000: VEV_5200 signal, follow ────────────────────────────
        "VEV_5000": dict(
            signal="VEV_5200",    signal_strike=5200,
            bucket="VEV_5200",    bucket_strike=5200,
            direction="follow",
            target_long=300,      target_short=-300,
            sweep=0,
            high_open=45.0,       mid_open=30.0,
            high_low=36.5,        high_high=48.0,
            mid_low=28.5,         mid_high=54.0,
            low_low=27.5,         low_high=42.5,
            high_flatten=975_000, mid_flatten=975_000, low_flatten=None,
        ),

        # ── VEV_5100: VEV_5200 signal, follow ────────────────────────────
        "VEV_5100": dict(
            signal="VEV_5200",    signal_strike=5200,
            bucket="VEV_5200",    bucket_strike=5200,
            direction="follow",
            target_long=300,      target_short=-300,
            sweep=0,
            high_open=45.0,       mid_open=30.0,
            high_low=36.5,        high_high=48.0,
            mid_low=28.5,         mid_high=54.0,
            low_low=27.5,         low_high=42.5,
            high_flatten=975_000, mid_flatten=975_000, low_flatten=None,
        ),

        # ── VEV_5200: self-signal, follow ─────────────────────────────────
        "VEV_5200": dict(
            signal="VEV_5200",    signal_strike=5200,
            bucket="VEV_5200",    bucket_strike=5200,
            direction="follow",
            target_long=300,      target_short=-300,
            sweep=0,
            high_open=45.0,       mid_open=30.0,
            high_low=36.5,        high_high=48.0,
            mid_low=28.5,         mid_high=54.0,
            low_low=27.5,         low_high=42.5,
            high_flatten=975_000, mid_flatten=975_000, low_flatten=None,
        ),

        # ── VEV_5300: self-premium fade, bucket via VEV_5200 ──────────────
        "VEV_5300": dict(
            signal="VEV_5300",    signal_strike=5300,
            bucket="VEV_5200",    bucket_strike=5200,
            direction="fade",
            target_long=300,      target_short=-300,
            sweep=0,
            high_open=45.0,       mid_open=30.0,
            high_low=40.0,        high_high=55.0,
            mid_low=28.5,         mid_high=54.0,
            low_low=25.0,         low_high=38.0,
            high_flatten=950_000, mid_flatten=975_000, low_flatten=None,
        ),

        # ── VEV_5400: VEV_5300 signal fade, bucket via VEV_5200 ───────────
        "VEV_5400": dict(
            signal="VEV_5300",    signal_strike=5300,
            bucket="VEV_5200",    bucket_strike=5200,
            direction="fade",
            target_long=300,      target_short=-300,
            sweep=0,
            high_open=45.0,       mid_open=30.0,
            high_low=40.0,        high_high=55.0,
            mid_low=28.5,         mid_high=54.0,
            low_low=25.5,         low_high=40.5,
            high_flatten=950_000, mid_flatten=975_000, low_flatten=None,
        ),

        # ── VEV_5500: VEV_5400 signal fade, bucket via VEV_5200 ───────────
        "VEV_5500": dict(
            signal="VEV_5400",    signal_strike=5400,
            bucket="VEV_5200",    bucket_strike=5200,
            direction="fade",
            target_long=300,      target_short=-300,
            sweep=0,
            high_open=45.0,       mid_open=30.0,
            high_low=12.5,        high_high=19.0,
            mid_low=10.0,         mid_high=17.5,
            low_low=5.5,          low_high=11.5,
            high_flatten=950_000, mid_flatten=975_000, low_flatten=None,
        ),
    }

    # ═════════════════════════════════════════════════════════════════════

    def __init__(self):
        self.state: Dict[str, dict] = {}
        for product in self.SIGNAL_CONFIGS:
            self.state[product] = dict(
                target=0,
                current_day_id=None,
                last_timestamp=None,
                reset_day_counter=0,
                opening_bucket_premium=None,
                low_threshold=None,
                high_threshold=None,
                flatten_after_ts=None,
            )

    # ═════════════════════════════════════════════════════════════════════
    # MAIN RUN
    # ═════════════════════════════════════════════════════════════════════

    def run(self, state: TradingState):
        self._restore(state.traderData)

        orders: Dict[Symbol, List[Order]] = {p: [] for p in state.order_depths}
        depths    = state.order_depths
        positions = state.position

        # ── HYDROGEL ──────────────────────────────────────────────────────
        if self.HYDROGEL in depths:
            d = depths[self.HYDROGEL]
            if d.buy_orders and d.sell_orders:
                orders[self.HYDROGEL] = self._trade_hydrogel(
                    d, int(positions.get(self.HYDROGEL, 0))
                )

        # ── Signal-driven options ─────────────────────────────────────────
        for product, cfg in self.SIGNAL_CONFIGS.items():
            if product not in depths or self.EXTRACT not in depths:
                continue

            signal_prod = cfg["signal"]
            bucket_prod = cfg["bucket"]

            if signal_prod not in depths or bucket_prod not in depths:
                continue

            pd = depths[product]
            sd = depths[signal_prod]
            bd = depths[bucket_prod]
            ud = depths[self.EXTRACT]

            if not (pd.buy_orders and pd.sell_orders and
                    sd.buy_orders and sd.sell_orders and
                    bd.buy_orders and bd.sell_orders and
                    ud.buy_orders and ud.sell_orders):
                continue

            underlying_mid = self._mid(ud)
            signal_premium = self._mid(sd) - max(0.0, underlying_mid - cfg["signal_strike"])
            bucket_premium = self._mid(bd) - max(0.0, underlying_mid - cfg["bucket_strike"])

            orders[product] = self._trade_signal(
                product, cfg, state.timestamp,
                pd, signal_premium, bucket_premium,
                int(positions.get(product, 0))
            )

        trader_data = self._serialize()
        logger.flush(state, orders, 0, trader_data)
        return orders, 0, trader_data

    # ═════════════════════════════════════════════════════════════════════
    # HYDROGEL market-making
    # ═════════════════════════════════════════════════════════════════════

    def _trade_hydrogel(self, od: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        product  = self.HYDROGEL
        limit    = self.LIMITS[product]
        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        spread   = best_ask - best_bid
        if spread <= 0:
            return orders

        mid       = (best_bid + best_ask) / 2.0
        dist      = abs(mid - self.HYDROGEL_BASE_FAIR)
        imbalance = self._imbalance(od)
        pos_skew  = position / limit

        if dist > self.HYDROGEL_EXTREME_DISTANCE:
            fair = self.HYDROGEL_EXTREME_BASE_WEIGHT * self.HYDROGEL_BASE_FAIR + self.HYDROGEL_EXTREME_MID_WEIGHT * mid
        else:
            fair = self.HYDROGEL_NORMAL_BASE_WEIGHT  * self.HYDROGEL_BASE_FAIR + self.HYDROGEL_NORMAL_MID_WEIGHT  * mid

        fair -= pos_skew * self.HYDROGEL_INVENTORY_SKEW
        fair -= self.HYDROGEL_INVENTORY_SKEW_QUAD * (pos_skew ** 3)
        fair -= imbalance * self.HYDROGEL_IMBALANCE_SKEW

        buy_cap  = limit - position
        sell_cap = limit + position

        # Aggressive takes
        for ask_price, ask_vol_raw in sorted(od.sell_orders.items()):
            ask_vol = -ask_vol_raw
            if ask_price <= fair - self.HYDROGEL_TAKE_WIDTH and buy_cap > 0:
                throttle = max(0.0, 1.0 - max(0.0, pos_skew) ** self.HYDROGEL_INV_TAKE_THROTTLE)
                size = max(1, int(self.HYDROGEL_TAKE_SIZE * throttle))
                qty  = min(size, ask_vol, buy_cap)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    buy_cap -= qty

        for bid_price, bid_vol in sorted(od.buy_orders.items(), reverse=True):
            if bid_price >= fair + self.HYDROGEL_TAKE_WIDTH and sell_cap > 0:
                throttle = max(0.0, 1.0 - max(0.0, -pos_skew) ** self.HYDROGEL_INV_TAKE_THROTTLE)
                size = max(1, int(self.HYDROGEL_TAKE_SIZE * throttle))
                qty  = min(size, bid_vol, sell_cap)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    sell_cap -= qty

        # Passive quotes
        edge = self.HYDROGEL_NEAR_FAIR_EDGE if abs(mid - self.HYDROGEL_BASE_FAIR) < self.HYDROGEL_NEAR_FAIR_ZONE else self.HYDROGEL_PASSIVE_EDGE
        bid_price = math.floor(fair - edge)
        ask_price = math.ceil(fair  + edge)

        if spread > 2:
            bid_price = min(bid_price, best_bid + 1)
            ask_price = max(ask_price, best_ask - 1)
        if bid_price >= ask_price:
            bid_price, ask_price = best_bid, best_ask

        buy_size  = min(self.HYDROGEL_QUOTE_SIZE, buy_cap)
        sell_size = min(self.HYDROGEL_QUOTE_SIZE, sell_cap)

        if buy_size  > 0 and bid_price < best_ask:
            orders.append(Order(product, bid_price,  buy_size))
        if sell_size > 0 and ask_price > best_bid:
            orders.append(Order(product, ask_price, -sell_size))

        # Flatten
        if position > self.HYDROGEL_FLATTEN_THRESHOLD and sell_cap > 0:
            qty = min(self.HYDROGEL_FLATTEN_SIZE, sell_cap)
            if qty > 0 and best_ask - 1 > best_bid:
                orders.append(Order(product, best_ask - 1, -qty))
        elif position < -self.HYDROGEL_FLATTEN_THRESHOLD and buy_cap > 0:
            qty = min(self.HYDROGEL_FLATTEN_SIZE, buy_cap)
            if qty > 0 and best_bid + 1 < best_ask:
                orders.append(Order(product, best_bid + 1, qty))

        return orders

    # ═════════════════════════════════════════════════════════════════════
    # Generic signal-driven strategy
    # ═════════════════════════════════════════════════════════════════════

    def _trade_signal(
        self,
        product:        str,
        cfg:            dict,
        timestamp:      int,
        pd:             OrderDepth,
        signal_premium: float,
        bucket_premium: float,
        position:       int,
    ) -> List[Order]:
        orders: List[Order] = []
        limit    = self.LIMITS[product]
        ps       = self.state[product]
        best_bid = max(pd.buy_orders)
        best_ask = min(pd.sell_orders)

        self._update_regime(product, cfg, timestamp, bucket_premium)

        time_in_day = timestamp % self.DAY_TS

        if ps["flatten_after_ts"] is not None and time_in_day >= ps["flatten_after_ts"]:
            ps["target"] = 0
        else:
            if ps["high_threshold"] is not None and signal_premium >= ps["high_threshold"]:
                ps["target"] = cfg["target_long"] if cfg["direction"] == "follow" else cfg["target_short"]
            elif ps["low_threshold"] is not None and signal_premium <= ps["low_threshold"]:
                ps["target"] = cfg["target_short"] if cfg["direction"] == "follow" else cfg["target_long"]

        target = max(-limit, min(limit, ps["target"]))

        if target > position:
            qty = min(target - position, limit - position)
            if qty > 0:
                orders.append(Order(product, int(best_ask + cfg["sweep"]), qty))
        elif target < position:
            qty = min(position - target, limit + position)
            if qty > 0:
                orders.append(Order(product, int(best_bid - cfg["sweep"]), -qty))

        ps["last_timestamp"] = timestamp
        return orders

    def _update_regime(self, product: str, cfg: dict, timestamp: int, bucket_premium: float):
        ps = self.state[product]

        if ps["last_timestamp"] is not None and timestamp < ps["last_timestamp"]:
            ps["reset_day_counter"] += 1

        day_id = max(timestamp // self.DAY_TS, ps["reset_day_counter"])

        if ps["current_day_id"] is None or day_id != ps["current_day_id"]:
            ps["current_day_id"]          = day_id
            ps["opening_bucket_premium"]  = bucket_premium
            ps["target"]                  = 0

            if bucket_premium >= cfg["high_open"]:
                ps["low_threshold"]    = cfg["high_low"]
                ps["high_threshold"]   = cfg["high_high"]
                ps["flatten_after_ts"] = cfg["high_flatten"]
            elif bucket_premium >= cfg["mid_open"]:
                ps["low_threshold"]    = cfg["mid_low"]
                ps["high_threshold"]   = cfg["mid_high"]
                ps["flatten_after_ts"] = cfg["mid_flatten"]
            else:
                ps["low_threshold"]    = cfg["low_low"]
                ps["high_threshold"]   = cfg["low_high"]
                ps["flatten_after_ts"] = cfg["low_flatten"]

    # ═════════════════════════════════════════════════════════════════════
    # Helpers
    # ═════════════════════════════════════════════════════════════════════

    def _mid(self, od: OrderDepth) -> float:
        return (max(od.buy_orders) + min(od.sell_orders)) / 2.0

    def _imbalance(self, od: OrderDepth) -> float:
        bid_vol = sum(od.buy_orders.values())
        ask_vol = sum(-v for v in od.sell_orders.values())
        if bid_vol + ask_vol == 0:
            return 0.0
        return (bid_vol - ask_vol) / (bid_vol + ask_vol)

    # ═════════════════════════════════════════════════════════════════════
    # State persistence
    # ═════════════════════════════════════════════════════════════════════

    def _restore(self, trader_data: str):
        if not trader_data:
            return
        try:
            saved = json.loads(trader_data)
        except Exception:
            return

        for product, ps in saved.get("state", {}).items():
            if product not in self.state:
                continue
            s = self.state[product]
            s["target"]                 = int(ps.get("target", 0))
            cdi = ps.get("current_day_id")
            s["current_day_id"]         = int(cdi)   if cdi is not None else None
            lts = ps.get("last_timestamp")
            s["last_timestamp"]         = int(lts)   if lts is not None else None
            s["reset_day_counter"]      = int(ps.get("reset_day_counter", 0))
            obp = ps.get("opening_bucket_premium")
            s["opening_bucket_premium"] = float(obp) if obp is not None else None
            lo  = ps.get("low_threshold")
            s["low_threshold"]          = float(lo)  if lo  is not None else None
            hi  = ps.get("high_threshold")
            s["high_threshold"]         = float(hi)  if hi  is not None else None
            fl  = ps.get("flatten_after_ts")
            s["flatten_after_ts"]       = int(fl)    if fl  is not None else None

    def _serialize(self) -> str:
        return json.dumps({"state": self.state}, separators=(",", ":"))