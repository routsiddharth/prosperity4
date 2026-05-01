"""
Round 5 combined Trader.

Dispatches to 8 sub-strategies, each operating on a disjoint product set:
  - PebblesTrader        (PEBBLES_XS/S/M/L/XL)
  - GalaxySoundsTrader   (GALAXY_SOUNDS_*)
  - PanelUVTrader        (PANEL_2X2/2X4/4X4 + UV_VISOR_AMBER/ORANGE/MAGENTA)
  - TranslatorTrader     (TRANSLATOR_*)
  - SleepPodTrader       (SLEEP_POD_*)
  - MicrochipTrader      (MICROCHIP_*)
  - RobotDishesTrader    (ROBOT_DISHES)
  - SnackpackTrader      (SNACKPACK_*)

Each sub-trader keeps its own traderData blob; the top-level Trader serializes
them as a JSON dict keyed by sub name. A single Logger.flush at the end emits
the consolidated visualizer log.
"""

import json
import math
from typing import Any, Dict, List, Optional, Tuple

import jsonpickle

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


# =========================================================================
# LOGGER
# =========================================================================

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

    def compress_state(self, state: TradingState, trader_data: str) -> list:
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

    def compress_listings(self, listings) -> list:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths) -> dict:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades) -> list:
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

    def compress_observations(self, observations) -> list:
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

    def compress_orders(self, orders) -> list:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value) -> str:
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


# =========================================================================
# MICROCHIP MODULE-LEVEL CONSTANTS / HELPERS
# =========================================================================

CHIPS = [
    "MICROCHIP_CIRCLE",
    "MICROCHIP_OVAL",
    "MICROCHIP_RECTANGLE",
    "MICROCHIP_SQUARE",
    "MICROCHIP_TRIANGLE",
]
LIMIT_PER_CHIP = 10
MAX_BUFFER = 1010
END_OF_DAY_TS = 990000
DAILY_LOSS_HALT = -5000
WARMUP_EXIT_COOLDOWN = 100

SPREAD_MED = {
    "MICROCHIP_CIRCLE": 8,
    "MICROCHIP_OVAL": 8,
    "MICROCHIP_RECTANGLE": 8,
    "MICROCHIP_SQUARE": 12,
    "MICROCHIP_TRIANGLE": 9,
}

PARAMS = {
    "A_basket3": {
        "kind": "basket", "priority": 1,
        "legs": {"MICROCHIP_RECTANGLE": +1,
                 "MICROCHIP_TRIANGLE": +1,
                 "MICROCHIP_OVAL": -1},
        "window": 1000, "z_entry": 2.0, "exit_mode": "opposite",
        "direction": "both", "max_units": 5,
        "max_hold": 700, "z_stop": 4.0,
        "warmup_mode": "dual", "w_short": 200, "z_short": 3.0,
        "pre_warmup_max_units": 1, "pre_warmup_max_hold": 300,
    },
    "B_basket4": {
        "kind": "basket", "priority": 2,
        "legs": {"MICROCHIP_CIRCLE": +1,
                 "MICROCHIP_OVAL": +1,
                 "MICROCHIP_RECTANGLE": -1,
                 "MICROCHIP_TRIANGLE": -1},
        "window": 1000, "z_entry": 2.0, "exit_mode": "opposite",
        "direction": "both", "max_units": 3,
        "max_hold": 900, "z_stop": 4.0,
        "warmup_mode": "dual", "w_short": 200, "z_short": 3.0,
        "pre_warmup_max_units": 1, "pre_warmup_max_hold": 300,
    },
    "C_tri_idio": {
        "kind": "idio", "priority": 3, "target": "MICROCHIP_TRIANGLE",
        "window": 1000, "z_entry": 2.0, "exit_mode": "opposite",
        "direction": "both", "max_units": 2,
        "max_hold": 1000, "z_stop": 4.0,
        "warmup_mode": "dual", "w_short": 200, "z_short": 3.0,
        "pre_warmup_max_units": 1, "pre_warmup_max_hold": 300,
    },
    "D_rect_mr": {
        "kind": "single", "priority": 4, "target": "MICROCHIP_RECTANGLE",
        "window": 300, "z_entry": 2.0, "exit_mode": "opposite",
        "direction": "both", "max_units": 2,
        "max_hold": 700, "z_stop": 4.0,
        "warmup_mode": "dual", "w_short": 100, "z_short": 3.0,
        "pre_warmup_max_units": 1, "pre_warmup_max_hold": 300,
    },
}

SLEEVE_ORDER = ["A_basket3", "B_basket4", "C_tri_idio", "D_rect_mr"]


def sleeve_legs(sid: str) -> Dict[str, int]:
    cfg = PARAMS[sid]
    if cfg["kind"] == "basket":
        return cfg["legs"]
    return {cfg["target"]: +1}


def init_state() -> dict:
    return {
        "last_ts": -1,
        "tick": 0,
        "mids_x2": {c: [] for c in CHIPS},
        "sleeves": {sid: {"units": 0, "entry_tick": None, "entry_price": None,
                          "entry_regime": "long", "cooldown_until": -1}
                    for sid in SLEEVE_ORDER},
        "daily_pnl": 0.0,
        "halted": False,
    }


def _trim(buf: list) -> list:
    if len(buf) > MAX_BUFFER:
        return buf[-MAX_BUFFER:]
    return buf


def compute_z(series: List[float], window: int, ddof: int = 1):
    n = len(series)
    if n < window:
        return None
    s = series[-window:]
    mean = sum(s) / window
    sq = 0.0
    for x in s:
        d = x - mean
        sq += d * d
    denom = window - ddof
    if denom <= 0:
        return None
    var = sq / denom
    if var <= 0:
        return None
    return (s[-1] - mean) / math.sqrt(var)


def compute_basket_z(state: dict, legs: Dict[str, int], window: int):
    n = min(len(state["mids_x2"][c]) for c in legs)
    if n < window:
        return None
    series = []
    start = n - window
    mids = state["mids_x2"]
    for i in range(start, n):
        v = 0.0
        for c, sgn in legs.items():
            v += (mids[c][i] * 0.5) * sgn
        series.append(v)
    return compute_z(series, window)


def compute_single_z(state: dict, target: str, window: int):
    n = len(state["mids_x2"][target])
    if n < window:
        return None
    seg = state["mids_x2"][target][-window:]
    return compute_z([v * 0.5 for v in seg], window)


def compute_idio_z(state: dict, target: str, window: int):
    n = min(len(state["mids_x2"][c]) for c in CHIPS)
    if n < window + 1:
        return None
    others = [c for c in CHIPS if c != target]
    mids = state["mids_x2"]
    cum = [0.0]
    start = n - window
    for i in range(start + 1, n):
        prev_t = mids[target][i - 1] * 0.5
        cur_t = mids[target][i] * 0.5
        if prev_t == 0:
            inc_t = 0.0
        else:
            inc_t = (cur_t - prev_t) / prev_t
        sum_o = 0.0
        for c in others:
            prev_o = mids[c][i - 1] * 0.5
            cur_o = mids[c][i] * 0.5
            if prev_o == 0:
                continue
            sum_o += (cur_o - prev_o) / prev_o
        mean_o = sum_o / len(others)
        cum.append(cum[-1] + (inc_t - mean_o))
    return compute_z(cum, window)


def _z_for_window(sid: str, state: dict, window: int):
    cfg = PARAMS[sid]
    if cfg["kind"] == "basket":
        return compute_basket_z(state, cfg["legs"], window)
    if cfg["kind"] == "single":
        return compute_single_z(state, cfg["target"], window)
    if cfg["kind"] == "idio":
        return compute_idio_z(state, cfg["target"], window)
    return None


def compute_z_for_sleeve(sid: str, state: dict, tick: int):
    cfg = PARAMS[sid]
    z_long = _z_for_window(sid, state, cfg["window"])
    if z_long is not None:
        return z_long, "long"
    if cfg.get("warmup_mode") == "dual":
        w_short = cfg.get("w_short", max(100, cfg["window"] // 5))
        z_short = _z_for_window(sid, state, w_short)
        if z_short is not None:
            return z_short, "short"
    return None, None


def proposed_entry(sid: str, units_now: int, z_now, regime):
    cfg = PARAMS[sid]
    if units_now != 0 or z_now is None or regime is None:
        return 0
    z_thr = cfg["z_short"] if regime == "short" else cfg["z_entry"]
    if regime == "short":
        units_cap = cfg.get("pre_warmup_max_units", 1)
    else:
        units_cap = cfg["max_units"]
    d = cfg.get("direction", "both")
    if d in ("both", "short") and z_now > z_thr:
        return -units_cap
    if d in ("both", "long") and z_now < -z_thr:
        return +units_cap
    return 0


def should_exit(sid: str, st: dict, z_now, regime, tick: int) -> bool:
    cfg = PARAMS[sid]
    units = st["units"]
    if units == 0 or st["entry_tick"] is None:
        return False
    held = tick - st["entry_tick"]
    entry_regime = st.get("entry_regime", "long")
    if entry_regime == "short":
        mhold = cfg.get("pre_warmup_max_hold", 300)
    else:
        mhold = cfg.get("max_hold")
    if mhold and held >= mhold:
        return True
    if z_now is None:
        return False
    if cfg.get("z_stop"):
        if units > 0 and z_now < -cfg["z_stop"]:
            return True
        if units < 0 and z_now > cfg["z_stop"]:
            return True
    z_thr = cfg["z_short"] if entry_regime == "short" else cfg["z_entry"]
    if cfg["exit_mode"] == "opposite":
        if units > 0 and z_now >= z_thr:
            return True
        if units < 0 and z_now <= -z_thr:
            return True
    return False


def current_total_legs(sleeves_state: dict) -> Dict[str, int]:
    total = {c: 0 for c in CHIPS}
    for sid, st in sleeves_state.items():
        if st["units"] != 0:
            for c, sgn in sleeve_legs(sid).items():
                total[c] += st["units"] * sgn
    return total


def fits(total: Dict[str, int], leg_vec: Dict[str, int]) -> bool:
    for c, v in leg_vec.items():
        if abs(total.get(c, 0) + v) > LIMIT_PER_CHIP:
            return False
    return True


def cap_units_to_fit(units_desired: int,
                     leg_signs: Dict[str, int],
                     total: Dict[str, int]) -> int:
    if units_desired == 0:
        return 0
    sgn = 1 if units_desired > 0 else -1
    for u in range(abs(int(units_desired)), 0, -1):
        leg_vec = {c: sgn * u * sg for c, sg in leg_signs.items()}
        if fits(total, leg_vec):
            return sgn * u
    return 0


def mode1_priority_partial(desired, current_total):
    accepted = []
    total = dict(current_total)
    for sid, units in sorted(desired, key=lambda x: PARAMS[x[0]]["priority"]):
        u = cap_units_to_fit(units, sleeve_legs(sid), total)
        if u != 0:
            for c, sg in sleeve_legs(sid).items():
                total[c] = total.get(c, 0) + u * sg
            accepted.append((sid, u))
    return accepted


# =========================================================================
# MICROCHIP TRADER
# =========================================================================

class MicrochipTrader:
    def run(self, state: TradingState):
        if state.traderData:
            try:
                tstate = jsonpickle.decode(state.traderData)
            except Exception:
                tstate = init_state()
            if not isinstance(tstate, dict) or "mids_x2" not in tstate:
                tstate = init_state()
        else:
            tstate = init_state()

        last_ts = tstate.get("last_ts", -1)
        if state.timestamp == 0 and last_ts >= 0:
            tstate = init_state()
        elif state.timestamp < last_ts:
            tstate = init_state()
        tstate["last_ts"] = state.timestamp

        mids_now: Dict[str, float] = {}
        spread_now: Dict[str, int] = {}
        for c in CHIPS:
            od: OrderDepth = state.order_depths.get(c)
            if od and od.buy_orders and od.sell_orders:
                bb = max(od.buy_orders.keys())
                ba = min(od.sell_orders.keys())
                mids_now[c] = (bb + ba) / 2.0
                spread_now[c] = ba - bb
            else:
                buf = tstate["mids_x2"].get(c, [])
                mids_now[c] = (buf[-1] * 0.5) if buf else None
                spread_now[c] = None

        for c in CHIPS:
            if mids_now[c] is not None:
                tstate["mids_x2"][c].append(int(round(mids_now[c] * 2)))
                tstate["mids_x2"][c] = _trim(tstate["mids_x2"][c])

        tick = tstate["tick"]
        result: Dict[str, List[Order]] = {c: [] for c in CHIPS}

        eod = state.timestamp >= END_OF_DAY_TS
        sleeves_st = tstate["sleeves"]

        pre_intent = current_total_legs(sleeves_st)
        chips_with_pending = set()
        for c in CHIPS:
            if pre_intent[c] != state.position.get(c, 0):
                chips_with_pending.add(c)

        z_by_sleeve = {sid: compute_z_for_sleeve(sid, tstate, tick) for sid in SLEEVE_ORDER}

        for sid in SLEEVE_ORDER:
            st = sleeves_st[sid]
            if st["units"] == 0:
                continue
            cfg = PARAMS[sid]
            z, regime = z_by_sleeve[sid]
            exit_now = eod or should_exit(sid, st, z, regime, tick)
            if exit_now:
                u = st["units"]
                exit_regime = st.get("entry_regime", "long")
                warmup_time_stop = (
                    exit_regime == "short"
                    and st["entry_tick"] is not None
                    and (tick - st["entry_tick"])
                        >= cfg.get("pre_warmup_max_hold", 300)
                )
                if st["entry_price"] is not None:
                    leg_pnl = 0.0
                    for c, sgn in sleeve_legs(sid).items():
                        if mids_now.get(c) is None:
                            leg_pnl = 0.0
                            break
                        leg_pnl += u * sgn * (mids_now[c] - st["entry_price"][c])
                    cost = abs(u) * sum(SPREAD_MED[c] for c in sleeve_legs(sid))
                    tstate["daily_pnl"] += leg_pnl - cost
                st["units"] = 0
                st["entry_tick"] = None
                st["entry_price"] = None
                st["entry_regime"] = "long"
                if warmup_time_stop and WARMUP_EXIT_COOLDOWN > 0:
                    st["cooldown_until"] = tick + WARMUP_EXIT_COOLDOWN

        if (not tstate["halted"]) and tstate["daily_pnl"] < DAILY_LOSS_HALT:
            tstate["halted"] = True

        if not eod and not tstate["halted"]:
            desired = []
            for sid in SLEEVE_ORDER:
                st = sleeves_st[sid]
                if st["units"] != 0:
                    continue
                if st.get("cooldown_until", -1) > tick:
                    continue
                z, regime = z_by_sleeve[sid]
                u = proposed_entry(sid, st["units"], z, regime)
                if u == 0:
                    continue
                legs = sleeve_legs(sid)
                ok = True
                for c in legs:
                    sp = spread_now.get(c)
                    if sp is None or sp > 2 * SPREAD_MED[c]:
                        ok = False
                        break
                if not ok:
                    continue
                if any(c in chips_with_pending for c in legs):
                    continue
                desired.append((sid, u))

            existing_total = current_total_legs(sleeves_st)
            accepted = mode1_priority_partial(desired, existing_total)

            for sid, u in accepted:
                st = sleeves_st[sid]
                legs = sleeve_legs(sid)
                _, regime_at_entry = z_by_sleeve[sid]
                st["units"] = u
                st["entry_tick"] = tick
                st["entry_price"] = {c: mids_now[c] for c in legs}
                st["entry_regime"] = regime_at_entry or "long"

        final_intent = current_total_legs(sleeves_st)
        for c in CHIPS:
            cur = state.position.get(c, 0)
            delta = final_intent[c] - cur
            if delta == 0:
                continue
            od = state.order_depths.get(c)
            if od is None:
                continue
            if delta > 0:
                if od.sell_orders:
                    ba = min(od.sell_orders.keys())
                    result[c].append(Order(c, ba, delta))
            else:
                if od.buy_orders:
                    bb = max(od.buy_orders.keys())
                    result[c].append(Order(c, bb, delta))

        tstate["tick"] = tick + 1
        traderData = jsonpickle.encode(tstate, unpicklable=False)
        return result, 0, traderData


# =========================================================================
# TRANSLATOR TRADER
# =========================================================================

class TranslatorTrader:
    TRANSLATORS = [
        "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL",
        "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_SPACE_GRAY",
        "TRANSLATOR_VOID_BLUE",
    ]

    POS_LIMIT = 10
    THRESH = 3
    IMPROVE = 1
    MAX_QUOTE = 5
    MIN_SPREAD = 3

    def run(self, state: TradingState):
        orders_by_product: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            if product not in self.TRANSLATORS:
                continue
            depth = state.order_depths[product]
            position = int(state.position.get(product, 0))
            ords = self.market_make(product, depth, position)
            if ords:
                orders_by_product[product] = ords

        return orders_by_product, 0, ""

    def market_make(
        self, product: str, depth: OrderDepth, position: int
    ) -> List[Order]:
        orders: List[Order] = []

        if not depth.buy_orders or not depth.sell_orders:
            return orders

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        spread = best_ask - best_bid

        if spread < self.MIN_SPREAD:
            return orders

        # Microprice skew: shift quotes toward the heavy side of the book so
        # passive MM stops loading inventory into a falling/rising market.
        bid_vol = abs(depth.buy_orders[best_bid])
        ask_vol = abs(depth.sell_orders[best_ask])
        total_vol = bid_vol + ask_vol
        if total_vol > 0:
            mid = (best_bid + best_ask) / 2.0
            microprice = (best_ask * bid_vol + best_bid * ask_vol) / total_vol
            skew = microprice - mid
        else:
            skew = 0.0

        bid_quote = best_bid + self.IMPROVE + int(math.floor(skew))
        ask_quote = best_ask - self.IMPROVE + int(math.ceil(skew))

        # Never cross our own quotes or the BBO.
        bid_quote = min(bid_quote, best_ask - 1)
        ask_quote = max(ask_quote, best_bid + 1)

        if bid_quote >= ask_quote:
            return orders

        suppress_bid = position >= self.THRESH
        suppress_ask = position <= -self.THRESH

        buy_capacity = self.POS_LIMIT - position
        sell_capacity = self.POS_LIMIT + position

        if not suppress_bid and buy_capacity > 0:
            bid_size = min(self.MAX_QUOTE, buy_capacity)
            if bid_size > 0:
                orders.append(Order(product, bid_quote, bid_size))

        if not suppress_ask and sell_capacity > 0:
            ask_size = min(self.MAX_QUOTE, sell_capacity)
            if ask_size > 0:
                orders.append(Order(product, ask_quote, -ask_size))

        return orders


# =========================================================================
# GALAXY SOUNDS TRADER
# =========================================================================

class GalaxySoundsTrader:
    PRODUCTS = [
        "GALAXY_SOUNDS_BLACK_HOLES",
        "GALAXY_SOUNDS_DARK_MATTER",
        "GALAXY_SOUNDS_PLANETARY_RINGS",
        "GALAXY_SOUNDS_SOLAR_FLAMES",
        "GALAXY_SOUNDS_SOLAR_WINDS",
    ]

    SHORT = {
        "GALAXY_SOUNDS_BLACK_HOLES": "BLACK_HOLES",
        "GALAXY_SOUNDS_DARK_MATTER": "DARK_MATTER",
        "GALAXY_SOUNDS_PLANETARY_RINGS": "PLANETARY_RINGS",
        "GALAXY_SOUNDS_SOLAR_FLAMES": "SOLAR_FLAMES",
        "GALAXY_SOUNDS_SOLAR_WINDS": "SOLAR_WINDS",
    }
    FULL = {v: k for k, v in SHORT.items()}

    LIMIT = 10

    BETA_TO_EX_SELF_GROUP = {
        "BLACK_HOLES": 0.7460,
        "DARK_MATTER": 0.1692,
        "PLANETARY_RINGS": 0.4586,
        "SOLAR_FLAMES": -0.1995,
        "SOLAR_WINDS": 0.3812,
    }

    RESIDUAL_MEAN = {
        "BLACK_HOLES": 3536.248534,
        "DARK_MATTER": 8375.458959,
        "PLANETARY_RINGS": 5811.081761,
        "SOLAR_FLAMES": 13232.097034,
        "SOLAR_WINDS": 6286.964149,
    }
    RESIDUAL_STD = {
        "BLACK_HOLES": 934.524337,
        "DARK_MATTER": 324.161933,
        "PLANETARY_RINGS": 750.897260,
        "SOLAR_FLAMES": 442.403122,
        "SOLAR_WINDS": 523.822392,
    }

    MID_MEAN = {
        "BLACK_HOLES": 11466.872083,
        "DARK_MATTER": 10226.661817,
        "PLANETARY_RINGS": 10766.673183,
        "SOLAR_FLAMES": 11092.571700,
        "SOLAR_WINDS": 10437.543967,
    }
    MID_STD = {
        "BLACK_HOLES": 958.444676,
        "DARK_MATTER": 330.700516,
        "PLANETARY_RINGS": 765.836693,
        "SOLAR_FLAMES": 450.150431,
        "SOLAR_WINDS": 541.110756,
    }

    RESIDUAL_WEIGHT = {
        "BLACK_HOLES": 0.55,
        "DARK_MATTER": 0.85,
        "PLANETARY_RINGS": 0.40,
        "SOLAR_FLAMES": 1.00,
        "SOLAR_WINDS": 0.75,
    }

    SCHEDULE_25K: List[Tuple[str, int, int, int, int]] = [
        ("BLACK_HOLES", 150000, 174900, +1, 8),
        ("BLACK_HOLES", 200000, 224900, -1, 10),
        ("BLACK_HOLES", 300000, 324900, +1, 10),
        ("PLANETARY_RINGS", 75000, 99900, -1, 8),
        ("PLANETARY_RINGS", 150000, 174900, -1, 10),
        ("PLANETARY_RINGS", 950000, 974900, -1, 10),
        ("SOLAR_FLAMES", 75000, 99900, +1, 8),
        ("SOLAR_FLAMES", 375000, 399900, -1, 8),
        ("SOLAR_FLAMES", 750000, 774900, -1, 8),
        ("SOLAR_FLAMES", 900000, 924900, -1, 8),
        ("SOLAR_WINDS", 775000, 799900, -1, 8),
    ]

    SCHEDULE_50K: List[Tuple[str, int, int, int, int]] = [
        ("BLACK_HOLES", 0, 49900, -1, 8),
        ("BLACK_HOLES", 50000, 99900, +1, 6),
        ("BLACK_HOLES", 150000, 199900, +1, 8),
        ("BLACK_HOLES", 300000, 349900, +1, 6),
        ("BLACK_HOLES", 850000, 899900, +1, 8),
        ("BLACK_HOLES", 900000, 949900, +1, 6),
        ("PLANETARY_RINGS", 50000, 99900, -1, 8),
        ("PLANETARY_RINGS", 100000, 149900, +1, 6),
        ("PLANETARY_RINGS", 150000, 199900, -1, 8),
        ("PLANETARY_RINGS", 450000, 499900, +1, 6),
        ("SOLAR_FLAMES", 50000, 99900, +1, 8),
        ("SOLAR_WINDS", 100000, 149900, +1, 6),
        ("SOLAR_WINDS", 250000, 299900, -1, 8),
        ("SOLAR_WINDS", 600000, 649900, +1, 6),
    ]

    SCHEDULE_100K: List[Tuple[str, int, int, int, int]] = [
        ("BLACK_HOLES", 100000, 199900, +1, 4),
        ("PLANETARY_RINGS", 400000, 499900, +1, 4),
        ("PLANETARY_RINGS", 500000, 599900, -1, 4),
        ("SOLAR_WINDS", 100000, 199900, +1, 4),
    ]

    PAIR_PARAMS = {
        ("SOLAR_FLAMES", "SOLAR_WINDS"): {
            "beta": -0.2788789274,
            "mean": 14003.382766,
            "std": 424.104697,
            "weight": 1.6,
        },
        ("DARK_MATTER", "PLANETARY_RINGS"): {
            "beta": 0.1875056763,
            "mean": 8207.849480,
            "std": 297.898660,
            "weight": 1.6,
        },
        ("DARK_MATTER", "SOLAR_WINDS"): {
            "beta": -0.0095836947,
            "mean": 10326.692052,
            "std": 330.659856,
            "weight": 0.8,
        },
        ("DARK_MATTER", "SOLAR_FLAMES"): {
            "beta": -0.0165546819,
            "mean": 10410.295812,
            "std": 330.616547,
            "weight": 0.8,
        },
        ("BLACK_HOLES", "SOLAR_FLAMES"): {
            "beta": -0.2493231700,
            "mean": 14232.507224,
            "std": 951.851252,
            "weight": 0.6,
        },
    }

    WIDE_SPREAD = {
        "BLACK_HOLES": 16,
        "DARK_MATTER": 14,
        "PLANETARY_RINGS": 15,
        "SOLAR_FLAMES": 15,
        "SOLAR_WINDS": 14,
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        mids: Dict[str, float] = {}
        books: Dict[str, Tuple[int, int, int, int, float, int]] = {}
        for product in self.PRODUCTS:
            if product not in state.order_depths:
                continue
            depth = state.order_depths[product]
            if not depth.buy_orders or not depth.sell_orders:
                continue
            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            bid_vol = depth.buy_orders[best_bid]
            ask_vol_abs = abs(depth.sell_orders[best_ask])
            mid = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            s = self.SHORT[product]
            mids[s] = mid
            books[s] = (best_bid, bid_vol, best_ask, ask_vol_abs, mid, spread)

        scores: Dict[str, float] = {s: 0.0 for s in self.FULL}
        aggressive: Dict[str, bool] = {s: False for s in self.FULL}
        fair_skew: Dict[str, float] = {s: 0.0 for s in self.FULL}

        ts = int(state.timestamp)
        for s, start, end, direction, lots in self.SCHEDULE_100K:
            if s in mids and start <= ts <= end:
                scores[s] += direction * lots
                fair_skew[s] += direction * 12.0
                aggressive[s] = True
        for s, start, end, direction, lots in self.SCHEDULE_50K:
            if s in mids and start <= ts <= end:
                scores[s] += direction * lots
                fair_skew[s] += direction * 20.0
                aggressive[s] = True
        for s, start, end, direction, lots in self.SCHEDULE_25K:
            if s in mids and start <= ts <= end:
                scores[s] += direction * lots
                fair_skew[s] += direction * 35.0
                aggressive[s] = True

        if len(mids) >= 5:
            for s in list(mids.keys()):
                others = [mids[o] for o in mids if o != s]
                if len(others) < 4:
                    continue
                group_ex_self = sum(others) / len(others)
                beta = self.BETA_TO_EX_SELF_GROUP[s]
                residual = mids[s] - beta * group_ex_self
                z = (residual - self.RESIDUAL_MEAN[s]) / max(self.RESIDUAL_STD[s], 1e-9)
                if abs(z) > 1.30:
                    contribution = -2.2 * self.RESIDUAL_WEIGHT[s] * z
                    contribution = max(-5.0, min(5.0, contribution))
                    scores[s] += contribution
                    fair_skew[s] += max(-30.0, min(30.0, -12.0 * z))
                    if abs(z) > 2.2:
                        aggressive[s] = True

        for (a, b), params in self.PAIR_PARAMS.items():
            if a not in mids or b not in mids:
                continue
            beta = params["beta"]
            spread_value = mids[a] - beta * mids[b]
            z = (spread_value - params["mean"]) / max(params["std"], 1e-9)
            if abs(z) > 1.80:
                q = -params["weight"] * z
                q = max(-3.0, min(3.0, q))
                scores[a] += q
                scores[b] += -beta * q
                fair_skew[a] += max(-22.0, min(22.0, -10.0 * z))
                fair_skew[b] += max(-16.0, min(16.0, 10.0 * beta * z))
                if abs(z) > 2.5:
                    aggressive[a] = True
                    aggressive[b] = True

        for s, mid in mids.items():
            z = (mid - self.MID_MEAN[s]) / max(self.MID_STD[s], 1e-9)
            if abs(z) > 2.0:
                contribution = -1.2 * (1 if z > 0 else -1)
                scores[s] += contribution
                fair_skew[s] += max(-20.0, min(20.0, -8.0 * z))

        for s in mids:
            best_bid, bid_vol, best_ask, ask_vol_abs, mid, spread = books[s]
            if bid_vol + ask_vol_abs > 0:
                micro = (best_ask * bid_vol + best_bid * ask_vol_abs) / (bid_vol + ask_vol_abs)
                fair_skew[s] += max(-3.0, min(3.0, micro - mid))
            if s != "BLACK_HOLES" and spread >= self.WIDE_SPREAD[s]:
                fair_skew[s] -= 4.0

        for s, score in scores.items():
            product = self.FULL[s]
            if s not in mids or product not in state.order_depths:
                continue
            pos = state.position.get(product, 0)
            active_schedule = self._has_active_schedule(s, ts)
            cap = self.LIMIT if active_schedule else 7
            target = int(round(score))
            target = max(-cap, min(cap, target))
            target = max(-self.LIMIT, min(self.LIMIT, target))

            orders = self._orders_to_target(product, s, state.order_depths[product], pos, target, fair_skew[s], aggressive[s])
            if orders:
                result[product] = orders

        return result, 0, ""

    def _has_active_schedule(self, s: str, ts: int) -> bool:
        for product, start, end, _, _ in self.SCHEDULE_25K:
            if product == s and start <= ts <= end:
                return True
        for product, start, end, _, _ in self.SCHEDULE_50K:
            if product == s and start <= ts <= end:
                return True
        for product, start, end, _, _ in self.SCHEDULE_100K:
            if product == s and start <= ts <= end:
                return True
        return False

    def _orders_to_target(
        self,
        product: str,
        short_product: str,
        depth: OrderDepth,
        pos: int,
        target: int,
        fair_skew: float,
        aggressive: bool,
    ) -> List[Order]:
        orders: List[Order] = []
        if not depth.buy_orders or not depth.sell_orders:
            return orders

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        mid = (best_bid + best_ask) / 2.0
        fair = mid + fair_skew
        delta = target - pos

        if delta > 0:
            qty = min(delta, self.LIMIT - pos)
            if qty <= 0:
                return orders
            if aggressive or fair >= best_ask - 1:
                price = best_ask
            else:
                price = min(best_ask - 1, max(best_bid + 1, int(math.floor(fair - 1))))
            orders.append(Order(product, int(price), int(qty)))

        elif delta < 0:
            qty = min(-delta, self.LIMIT + pos)
            if qty <= 0:
                return orders
            if aggressive or fair <= best_bid + 1:
                price = best_bid
            else:
                price = max(best_bid + 1, min(best_ask - 1, int(math.ceil(fair + 1))))
            orders.append(Order(product, int(price), -int(qty)))

        return orders


# =========================================================================
# SLEEP POD TRADER
# =========================================================================

class SleepPodTrader:
    PRODUCTS = [
        "SLEEP_POD_COTTON",
        "SLEEP_POD_LAMB_WOOL",
        "SLEEP_POD_NYLON",
        "SLEEP_POD_POLYESTER",
        "SLEEP_POD_SUEDE",
    ]

    SHORT = {
        "SLEEP_POD_COTTON": "COTTON",
        "SLEEP_POD_LAMB_WOOL": "LAMB_WOOL",
        "SLEEP_POD_NYLON": "NYLON",
        "SLEEP_POD_POLYESTER": "POLYESTER",
        "SLEEP_POD_SUEDE": "SUEDE",
    }
    FULL = {v: k for k, v in SHORT.items()}

    LIMIT = 10

    BETA_TO_EX_SELF_GROUP = {
        "COTTON": 1.4100779123,
        "LAMB_WOOL": 0.0457033203,
        "NYLON": 0.3056936667,
        "POLYESTER": 1.6999748206,
        "SUEDE": 1.2059713707,
    }

    RESIDUAL_MEAN = {
        "COTTON": -3833.738031,
        "LAMB_WOOL": 10194.111234,
        "NYLON": 6161.726247,
        "POLYESTER": -6545.919907,
        "SUEDE": -1779.652642,
    }
    RESIDUAL_STD = {
        "COTTON": 501.320101,
        "LAMB_WOOL": 411.934553,
        "NYLON": 467.781636,
        "POLYESTER": 503.019969,
        "SUEDE": 627.374943,
    }

    MID_MEAN = {
        "COTTON": 11527.613967,
        "LAMB_WOOL": 10701.441717,
        "NYLON": 9636.472567,
        "POLYESTER": 11840.560950,
        "SUEDE": 11397.420433,
    }
    MID_STD = {
        "COTTON": 887.692891,
        "LAMB_WOOL": 413.169049,
        "NYLON": 508.728535,
        "POLYESTER": 977.539539,
        "SUEDE": 899.946472,
    }

    RESIDUAL_WEIGHT = {
        "COTTON": 0.65,
        "LAMB_WOOL": 1.00,
        "NYLON": 0.55,
        "POLYESTER": 0.45,
        "SUEDE": 0.95,
    }

    SCHEDULE_100K: List[Tuple[str, int, int, int, int]] = [
        ("POLYESTER", 100000, 199900, +1, 4),
        ("POLYESTER", 200000, 299900, -1, 4),
        ("SUEDE", 100000, 199900, -1, 3),
        ("SUEDE", 800000, 899900, +1, 4),
        ("SUEDE", 900000, 999900, -1, 3),
    ]

    SCHEDULE_50K: List[Tuple[str, int, int, int, int]] = [
        ("POLYESTER", 250000, 299900, -1, 8),
        ("SUEDE", 800000, 849900, +1, 8),
        ("SUEDE", 250000, 299900, +1, 8),
        ("POLYESTER", 150000, 199900, +1, 8),
        ("SUEDE", 150000, 199900, -1, 7),
        ("COTTON", 900000, 949900, -1, 6),
        ("NYLON", 150000, 199900, +1, 6),
        ("SUEDE", 700000, 749900, +1, 6),
        ("LAMB_WOOL", 750000, 799900, +1, 6),
        ("SUEDE", 0, 49900, +1, 10),
        ("SUEDE", 50000, 74900, +1, 10),
        ("SUEDE", 75000, 99900, -1, 10),
        ("COTTON", 75000, 99900, +1, 10),
        ("POLYESTER", 400000, 449900, -1, 5),
        ("POLYESTER", 750000, 799900, +1, 5),
        ("COTTON", 250000, 299900, +1, 4),
        ("COTTON", 950000, 999900, +1, 3),
        ("LAMB_WOOL", 150000, 199900, +1, 3),
        ("LAMB_WOOL", 350000, 399900, +1, 2),
        ("SUEDE", 550000, 599900, -1, 2),
    ]

    SCHEDULE_25K: List[Tuple[str, int, int, int, int]] = [
        ("SUEDE", 825000, 849900, +1, 7),
        ("POLYESTER", 175000, 199900, +1, 7),
        ("LAMB_WOOL", 275000, 299900, +1, 7),
        ("SUEDE", 100000, 124900, +1, 6),
        ("NYLON", 550000, 574900, -1, 7),
        ("POLYESTER", 275000, 299900, -1, 7),
        ("POLYESTER", 700000, 724900, -1, 6),
        ("SUEDE", 900000, 924900, -1, 6),
        ("SUEDE", 800000, 824900, +1, 5),
        ("COTTON", 575000, 599900, -1, 5),
        ("NYLON", 175000, 199900, +1, 5),
        ("NYLON", 425000, 449900, +1, 4),
    ]

    PAIR_PARAMS = {
        ("COTTON", "POLYESTER"): {
            "beta": 0.7948195677,
            "mean": 2116.504431,
            "std": 429.372024,
            "weight": 1.5,
        },
        ("POLYESTER", "SUEDE"): {
            "beta": 0.9337636163,
            "mean": 1198.064429,
            "std": 499.463608,
            "weight": 1.3,
        },
        ("LAMB_WOOL", "NYLON"): {
            "beta": 0.4005488291,
            "mean": 6841.563913,
            "std": 359.428666,
            "weight": 1.5,
        },
        ("LAMB_WOOL", "SUEDE"): {
            "beta": -0.0278286194,
            "mean": 11018.654332,
            "std": 412.866097,
            "weight": 0.7,
        },
        ("LAMB_WOOL", "POLYESTER"): {
            "beta": -0.0163054974,
            "mean": 10894.409467,
            "std": 413.014567,
            "weight": 0.7,
        },
    }

    WIDE_SPREAD = {
        "COTTON": 11,
        "LAMB_WOOL": 10,
        "NYLON": 10,
        "POLYESTER": 12,
        "SUEDE": 11,
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        mids: Dict[str, float] = {}
        books: Dict[str, Tuple[int, int, int, int, float, int]] = {}
        for product in self.PRODUCTS:
            if product not in state.order_depths:
                continue
            depth = state.order_depths[product]
            if not depth.buy_orders or not depth.sell_orders:
                continue
            best_bid = max(depth.buy_orders.keys())
            best_ask = min(depth.sell_orders.keys())
            bid_vol = depth.buy_orders[best_bid]
            ask_vol_abs = abs(depth.sell_orders[best_ask])
            mid = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            s = self.SHORT[product]
            mids[s] = mid
            books[s] = (best_bid, bid_vol, best_ask, ask_vol_abs, mid, spread)

        scores: Dict[str, float] = {s: 0.0 for s in self.FULL}
        aggressive: Dict[str, bool] = {s: False for s in self.FULL}
        fair_skew: Dict[str, float] = {s: 0.0 for s in self.FULL}

        ts = int(state.timestamp)

        for s, start, end, direction, lots in self.SCHEDULE_100K:
            if s in mids and start <= ts <= end:
                scores[s] += direction * lots
                fair_skew[s] += direction * 10.0
                aggressive[s] = True

        for s, start, end, direction, lots in self.SCHEDULE_50K:
            if s in mids and start <= ts <= end:
                scores[s] += direction * lots
                fair_skew[s] += direction * 20.0
                aggressive[s] = True

        for s, start, end, direction, lots in self.SCHEDULE_25K:
            if s in mids and start <= ts <= end:
                scores[s] += direction * lots
                fair_skew[s] += direction * 32.0
                aggressive[s] = True

        if ts >= 100000:
            if len(mids) >= 5:
                for s in list(mids.keys()):
                    others = [mids[o] for o in mids if o != s]
                    if len(others) < 4:
                        continue
                    group_ex_self = sum(others) / len(others)
                    beta = self.BETA_TO_EX_SELF_GROUP[s]
                    residual = mids[s] - beta * group_ex_self
                    z = (residual - self.RESIDUAL_MEAN[s]) / max(self.RESIDUAL_STD[s], 1e-9)

                    if abs(z) > 1.25:
                        contribution = -2.4 * self.RESIDUAL_WEIGHT[s] * z
                        contribution = max(-5.0, min(5.0, contribution))
                        scores[s] += contribution
                        fair_skew[s] += max(-30.0, min(30.0, -12.0 * z))
                        if abs(z) > 2.15:
                            aggressive[s] = True

            for (a, b), params in self.PAIR_PARAMS.items():
                if a not in mids or b not in mids:
                    continue
                beta = params["beta"]
                spread_value = mids[a] - beta * mids[b]
                z = (spread_value - params["mean"]) / max(params["std"], 1e-9)
                if abs(z) > 1.75:
                    q = -params["weight"] * z
                    q = max(-3.0, min(3.0, q))
                    scores[a] += q
                    scores[b] += -beta * q
                    fair_skew[a] += max(-22.0, min(22.0, -10.0 * z))
                    fair_skew[b] += max(-18.0, min(18.0, 10.0 * beta * z))
                    if abs(z) > 2.45:
                        aggressive[a] = True
                        aggressive[b] = True

            for s, mid in mids.items():
                z = (mid - self.MID_MEAN[s]) / max(self.MID_STD[s], 1e-9)
                threshold = 1.85 if s in ("LAMB_WOOL", "SUEDE") else 2.05
                if abs(z) > threshold:
                    contribution = -1.1 * (1 if z > 0 else -1)
                    scores[s] += contribution
                    fair_skew[s] += max(-18.0, min(18.0, -7.0 * z))

        for s in mids:
            best_bid, bid_vol, best_ask, ask_vol_abs, mid, spread = books[s]
            if bid_vol + ask_vol_abs > 0:
                micro = (best_ask * bid_vol + best_bid * ask_vol_abs) / (bid_vol + ask_vol_abs)
                fair_skew[s] += max(-3.5, min(3.5, micro - mid))

            if spread >= self.WIDE_SPREAD[s]:
                if s == "POLYESTER":
                    fair_skew[s] -= 2.0
                else:
                    fair_skew[s] -= 5.0

        for s, score in scores.items():
            product = self.FULL[s]
            if s not in mids or product not in state.order_depths:
                continue

            pos = state.position.get(product, 0)
            active_schedule = self._has_active_schedule(s, ts)

            cap = self.LIMIT if active_schedule else 7
            target = int(round(score))
            target = max(-cap, min(cap, target))
            target = max(-self.LIMIT, min(self.LIMIT, target))

            orders = self._orders_to_target(
                product,
                s,
                state.order_depths[product],
                pos,
                target,
                fair_skew[s],
                aggressive[s],
            )
            if orders:
                result[product] = orders

        return result, 0, ""

    def _has_active_schedule(self, s: str, ts: int) -> bool:
        for product, start, end, _, _ in self.SCHEDULE_25K:
            if product == s and start <= ts <= end:
                return True
        for product, start, end, _, _ in self.SCHEDULE_50K:
            if product == s and start <= ts <= end:
                return True
        for product, start, end, _, _ in self.SCHEDULE_100K:
            if product == s and start <= ts <= end:
                return True
        return False

    def _orders_to_target(
        self,
        product: str,
        short_product: str,
        depth: OrderDepth,
        pos: int,
        target: int,
        fair_skew: float,
        aggressive: bool,
    ) -> List[Order]:
        orders: List[Order] = []
        if not depth.buy_orders or not depth.sell_orders:
            return orders

        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        mid = (best_bid + best_ask) / 2.0
        fair = mid + fair_skew
        delta = target - pos

        if delta > 0:
            qty = min(delta, self.LIMIT - pos)
            if qty <= 0:
                return orders
            if aggressive or fair >= best_ask - 1:
                price = best_ask
            else:
                price = min(best_ask - 1, max(best_bid + 1, int(math.floor(fair - 1))))
            orders.append(Order(product, int(price), int(qty)))

        elif delta < 0:
            qty = min(-delta, self.LIMIT + pos)
            if qty <= 0:
                return orders
            if aggressive or fair <= best_bid + 1:
                price = best_bid
            else:
                price = max(best_bid + 1, min(best_ask - 1, int(math.ceil(fair + 1))))
            orders.append(Order(product, int(price), -int(qty)))

        return orders


# =========================================================================
# PANEL + UV TRADER
# =========================================================================

class PanelUVTrader:
    POSITION_LIMIT = 10
    MIN_WARMUP = 200

    STRATEGIES = [
        {
            "name": "PANEL_selected_legs",
            "signal_symbols": ["PANEL_2X2", "PANEL_2X4", "PANEL_4X4"],
            "trade_symbols": ["PANEL_2X4", "PANEL_4X4"],
            "window": 500,
            "entry_edge": 200.0,
            "exit_edge": 200.0,
            "trade_size": 1,
        },
        {
            "name": "UV_full_AOM",
            "signal_symbols": ["UV_VISOR_AMBER", "UV_VISOR_ORANGE", "UV_VISOR_MAGENTA"],
            "trade_symbols": ["UV_VISOR_AMBER", "UV_VISOR_ORANGE", "UV_VISOR_MAGENTA"],
            "window": 500,
            "entry_edge": 400.0,
            "exit_edge": 200.0,
            "trade_size": 1,
        },
    ]

    def _load_data(self, trader_data: str) -> Dict[str, List[float]]:
        default = {s["name"]: [] for s in self.STRATEGIES}
        if not trader_data:
            return default
        try:
            data = json.loads(trader_data)
            if not isinstance(data, dict):
                return default
            for strat in self.STRATEGIES:
                name = strat["name"]
                if name not in data or not isinstance(data[name], list):
                    data[name] = []
            return data
        except Exception:
            return default

    def _dump_data(self, data: Dict[str, List[float]]) -> str:
        for strat in self.STRATEGIES:
            name = strat["name"]
            window = int(strat["window"])
            data[name] = data.get(name, [])[-window:]
        return json.dumps(data, separators=(",", ":"))

    def _best_bid_ask(self, order_depth: OrderDepth) -> Optional[Tuple[int, int, int, int, float]]:
        if order_depth is None:
            return None
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_volume = int(order_depth.buy_orders[best_bid])
        ask_volume = int(-order_depth.sell_orders[best_ask])

        if bid_volume <= 0 or ask_volume <= 0:
            return None

        mid = (best_bid + best_ask) / 2.0
        return best_bid, bid_volume, best_ask, ask_volume, mid

    def _snapshot(self, state: TradingState, symbols: List[str]):
        snap = {}
        for symbol in symbols:
            if symbol not in state.order_depths:
                return None
            top = self._best_bid_ask(state.order_depths[symbol])
            if top is None:
                return None

            best_bid, bid_vol, best_ask, ask_vol, mid = top
            snap[symbol] = {
                "bid": best_bid,
                "bid_vol": bid_vol,
                "ask": best_ask,
                "ask_vol": ask_vol,
                "mid": mid,
            }
        return snap

    def _add_orders(
        self,
        result: Dict[str, List[Order]],
        local_pos: Dict[str, int],
        trade_symbols: List[str],
        snap: Dict[str, Dict[str, float]],
        side: str,
        trade_size: int,
        exit_only: bool = False,
    ) -> bool:
        qty = int(trade_size)

        if side == "buy":
            for symbol in trade_symbols:
                pos = local_pos.get(symbol, 0)
                if exit_only:
                    pos_room = max(0, -pos)
                else:
                    pos_room = max(0, self.POSITION_LIMIT - pos)
                liquidity = int(snap[symbol]["ask_vol"])
                qty = min(qty, pos_room, liquidity)

            if qty <= 0:
                return False

            for symbol in trade_symbols:
                price = int(snap[symbol]["ask"])
                result.setdefault(symbol, []).append(Order(symbol, price, qty))
                local_pos[symbol] = local_pos.get(symbol, 0) + qty
            return True

        if side == "sell":
            for symbol in trade_symbols:
                pos = local_pos.get(symbol, 0)
                if exit_only:
                    pos_room = max(0, pos)
                else:
                    pos_room = max(0, self.POSITION_LIMIT + pos)
                liquidity = int(snap[symbol]["bid_vol"])
                qty = min(qty, pos_room, liquidity)

            if qty <= 0:
                return False

            for symbol in trade_symbols:
                price = int(snap[symbol]["bid"])
                result.setdefault(symbol, []).append(Order(symbol, price, -qty))
                local_pos[symbol] = local_pos.get(symbol, 0) - qty
            return True

        return False

    def _trade_strategy(
        self,
        state: TradingState,
        result: Dict[str, List[Order]],
        local_pos: Dict[str, int],
        history: List[float],
        strat: Dict,
    ) -> None:
        signal_symbols = strat["signal_symbols"]
        trade_symbols = strat["trade_symbols"]
        window = int(strat["window"])
        entry_edge = float(strat["entry_edge"])
        exit_edge = float(strat["exit_edge"])
        trade_size = int(strat["trade_size"])

        snap = self._snapshot(state, signal_symbols)
        if snap is None:
            return

        basket_mid = sum(snap[s]["mid"] for s in signal_symbols)
        basket_ask = sum(snap[s]["ask"] for s in signal_symbols)
        basket_bid = sum(snap[s]["bid"] for s in signal_symbols)

        effective_window = min(len(history), window)
        if effective_window >= self.MIN_WARMUP:
            fair = sum(history[-effective_window:]) / effective_window
            positions = [local_pos.get(s, 0) for s in trade_symbols]
            all_long = all(p > 0 for p in positions)
            all_short = all(p < 0 for p in positions)

            if basket_ask < fair - entry_edge:
                self._add_orders(result, local_pos, trade_symbols, snap, "buy", trade_size, exit_only=False)

            elif basket_bid > fair + entry_edge:
                self._add_orders(result, local_pos, trade_symbols, snap, "sell", trade_size, exit_only=False)

            elif all_long and basket_bid > fair + exit_edge:
                self._add_orders(result, local_pos, trade_symbols, snap, "sell", trade_size, exit_only=True)

            elif all_short and basket_ask < fair - exit_edge:
                self._add_orders(result, local_pos, trade_symbols, snap, "buy", trade_size, exit_only=True)

        history.append(basket_mid)
        if len(history) > window:
            del history[:-window]

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        data = self._load_data(state.traderData)

        local_pos: Dict[str, int] = dict(state.position) if state.position is not None else {}

        for strat in self.STRATEGIES:
            name = strat["name"]
            history = data.setdefault(name, [])
            self._trade_strategy(state, result, local_pos, history, strat)

        trader_data = self._dump_data(data)
        return result, 0, trader_data


# =========================================================================
# SNACKPACK TRADER
# =========================================================================

class SnackpackTrader:
    PRODUCTS = [
        "SNACKPACK_CHOCOLATE",
        "SNACKPACK_VANILLA",
        "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY",
        "SNACKPACK_RASPBERRY",
    ]

    LIMITS = {
        "SNACKPACK_CHOCOLATE":  10,
        "SNACKPACK_VANILLA":    10,
        "SNACKPACK_PISTACHIO":  10,
        "SNACKPACK_STRAWBERRY": 10,
        "SNACKPACK_RASPBERRY":  10,
    }

    BASKET_WINDOW = 3000
    MIN_BASKET_HISTORY = 100

    ENTRY_Z = 2.0
    EXIT_Z = 0.0
    PANIC_Z = 4.0

    STAT_ARB_BASE_SIZE = 4
    STAT_ARB_MAX_SIZE = 10

    SIGMA_FLOOR = 50.0

    MICROPRICE_EDGE_MULT = 0.15
    IMBALANCE_EDGE_MULT = 1.5

    BASKET_A_LEGS = {
        "SNACKPACK_RASPBERRY": +1,
        "SNACKPACK_CHOCOLATE": -1,
        "SNACKPACK_VANILLA":   -1,
    }
    BASKET_A_ANCHOR = "SNACKPACK_RASPBERRY"

    BASKET_B_LEGS = {
        "SNACKPACK_STRAWBERRY": +1,
        "SNACKPACK_PISTACHIO":  +1,
    }
    BASKET_B_ANCHOR = "SNACKPACK_STRAWBERRY"

    def run(self, state: TradingState):
        orders: Dict[Symbol, List[Order]] = {p: [] for p in self.PRODUCTS}
        data = self._decode_state(state.traderData)

        mids = {}
        best_bids = {}
        best_asks = {}
        microprices = {}
        imbalances = {}

        for product in self.PRODUCTS:
            depth = state.order_depths.get(product)
            if depth is None:
                continue
            best_bid, best_ask = self.best_bid_ask(depth)
            if best_bid is None or best_ask is None:
                continue
            mids[product] = (best_bid + best_ask) / 2
            best_bids[product] = best_bid
            best_asks[product] = best_ask
            microprices[product] = self.microprice(depth)
            imbalances[product] = self.imbalance(depth)

        if all(p in mids for p in self.BASKET_A_LEGS):
            self.update_basket_a_history(data, mids)
            z_a = self.compute_basket_a_z(data)
            if z_a is not None:
                self.manage_basket_a_position(
                    state=state,
                    orders=orders,
                    best_bids=best_bids,
                    best_asks=best_asks,
                    microprices=microprices,
                    imbalances=imbalances,
                    z=z_a,
                )

        if all(p in mids for p in self.BASKET_B_LEGS):
            self.update_basket_b_history(data, mids)
            z_b = self.compute_basket_b_z(data)
            if z_b is not None:
                self.manage_basket_b_position(
                    state=state,
                    orders=orders,
                    best_bids=best_bids,
                    best_asks=best_asks,
                    microprices=microprices,
                    imbalances=imbalances,
                    z=z_b,
                )

        orders = {k: v for k, v in orders.items() if v}
        trader_data = self._encode_state(data)
        return orders, 0, trader_data

    def _encode_state(self, data: Dict[str, Any]) -> str:
        a = ",".join(str(int(round(v * 2))) for v in data.get("basket_a_history", []))
        b = ",".join(str(int(round(v * 2))) for v in data.get("basket_b_history", []))
        return a + "|" + b

    def _decode_state(self, trader_data: str) -> Dict[str, Any]:
        empty = {"basket_a_history": [], "basket_b_history": []}
        if not trader_data:
            return empty
        parts = trader_data.split("|")
        if len(parts) != 2:
            return empty
        try:
            a = [int(t) / 2.0 for t in parts[0].split(",") if t]
            b = [int(t) / 2.0 for t in parts[1].split(",") if t]
        except ValueError:
            return empty
        return {"basket_a_history": a, "basket_b_history": b}

    def update_basket_a_history(self, data, mids):
        value = sum(sign * mids[p] for p, sign in self.BASKET_A_LEGS.items())
        data["basket_a_history"].append(value)
        if len(data["basket_a_history"]) > self.BASKET_WINDOW:
            data["basket_a_history"] = data["basket_a_history"][-self.BASKET_WINDOW:]

    def update_basket_b_history(self, data, mids):
        value = sum(sign * mids[p] for p, sign in self.BASKET_B_LEGS.items())
        data["basket_b_history"].append(value)
        if len(data["basket_b_history"]) > self.BASKET_WINDOW:
            data["basket_b_history"] = data["basket_b_history"][-self.BASKET_WINDOW:]

    def compute_basket_a_z(self, data):
        return self._z_score(data.get("basket_a_history", []))

    def compute_basket_b_z(self, data):
        return self._z_score(data.get("basket_b_history", []))

    def _z_score(self, hist):
        if len(hist) < self.MIN_BASKET_HISTORY:
            return None
        current = hist[-1]
        mean = sum(hist) / len(hist)
        variance = sum((x - mean) ** 2 for x in hist) / len(hist)
        std = max(math.sqrt(variance), self.SIGMA_FLOOR)
        if std <= 1e-9:
            return None
        return (current - mean) / std

    def manage_basket_a_position(self, state, orders, best_bids, best_asks, microprices, imbalances, z):
        if abs(z) <= self.EXIT_Z:
            self.flatten_basket_a(state, orders, best_bids, best_asks)
            return
        if abs(z) < self.ENTRY_Z:
            return
        if abs(z) > self.PANIC_Z:
            base_size = 1
        else:
            base_size = min(self.STAT_ARB_MAX_SIZE,
                            max(1, int(self.STAT_ARB_BASE_SIZE * abs(z) / self.ENTRY_Z)))
        if z > self.ENTRY_Z:
            self.open_short_basket_a(state, orders, best_bids, best_asks, microprices, imbalances, base_size)
        elif z < -self.ENTRY_Z:
            self.open_long_basket_a(state, orders, best_bids, best_asks, microprices, imbalances, base_size)

    def manage_basket_b_position(self, state, orders, best_bids, best_asks, microprices, imbalances, z):
        if abs(z) <= self.EXIT_Z:
            self.flatten_basket_b(state, orders, best_bids, best_asks)
            return
        if abs(z) < self.ENTRY_Z:
            return
        if abs(z) > self.PANIC_Z:
            base_size = 1
        else:
            base_size = min(self.STAT_ARB_MAX_SIZE,
                            max(1, int(self.STAT_ARB_BASE_SIZE * abs(z) / self.ENTRY_Z)))
        if z > self.ENTRY_Z:
            self.open_short_basket_b(state, orders, best_bids, best_asks, microprices, imbalances, base_size)
        elif z < -self.ENTRY_Z:
            self.open_long_basket_b(state, orders, best_bids, best_asks, microprices, imbalances, base_size)

    def open_short_basket_a(self, state, orders, best_bids, best_asks, microprices, imbalances, base_size):
        for product, sign in self.BASKET_A_LEGS.items():
            self._send_leg_order(product, -sign, state, orders, best_bids, best_asks, microprices, imbalances, base_size)

    def open_long_basket_a(self, state, orders, best_bids, best_asks, microprices, imbalances, base_size):
        for product, sign in self.BASKET_A_LEGS.items():
            self._send_leg_order(product, +sign, state, orders, best_bids, best_asks, microprices, imbalances, base_size)

    def flatten_basket_a(self, state, orders, best_bids, best_asks):
        for product in self.BASKET_A_LEGS:
            self._send_flatten_order(product, state, orders, best_bids, best_asks)

    def open_short_basket_b(self, state, orders, best_bids, best_asks, microprices, imbalances, base_size):
        for product, sign in self.BASKET_B_LEGS.items():
            self._send_leg_order(product, -sign, state, orders, best_bids, best_asks, microprices, imbalances, base_size)

    def open_long_basket_b(self, state, orders, best_bids, best_asks, microprices, imbalances, base_size):
        for product, sign in self.BASKET_B_LEGS.items():
            self._send_leg_order(product, +sign, state, orders, best_bids, best_asks, microprices, imbalances, base_size)

    def flatten_basket_b(self, state, orders, best_bids, best_asks):
        for product in self.BASKET_B_LEGS:
            self._send_flatten_order(product, state, orders, best_bids, best_asks)

    def _send_leg_order(self, product, direction, state, orders, best_bids, best_asks, microprices, imbalances, base_size):
        pos = state.position.get(product, 0)
        limit = self.LIMITS[product]
        signal = self.micro_signal(
            mid=(best_bids[product] + best_asks[product]) / 2,
            microprice=microprices[product],
            imbalance=imbalances[product],
        )
        size = base_size
        if direction > 0 and signal > 0:
            size += 1
        elif direction < 0 and signal < 0:
            size += 1
        if direction > 0:
            buy_capacity = limit - pos
            qty = min(size, buy_capacity)
            if qty > 0:
                orders[product].append(Order(product, best_asks[product], qty))
        else:
            sell_capacity = limit + pos
            qty = min(size, sell_capacity)
            if qty > 0:
                orders[product].append(Order(product, best_bids[product], -qty))

    def _send_flatten_order(self, product, state, orders, best_bids, best_asks):
        pos = state.position.get(product, 0)
        if pos > 0:
            orders[product].append(Order(product, best_bids[product], -pos))
        elif pos < 0:
            orders[product].append(Order(product, best_asks[product], -pos))

    def best_bid_ask(self, depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def imbalance(self, depth: OrderDepth) -> float:
        if not depth.buy_orders or not depth.sell_orders:
            return 0.0
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        bid_vol = abs(depth.buy_orders[best_bid])
        ask_vol = abs(depth.sell_orders[best_ask])
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    def microprice(self, depth: OrderDepth) -> float:
        if not depth.buy_orders or not depth.sell_orders:
            return 0.0
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        bid_vol = abs(depth.buy_orders[best_bid])
        ask_vol = abs(depth.sell_orders[best_ask])
        total = bid_vol + ask_vol
        if total == 0:
            return (best_bid + best_ask) / 2
        return (best_ask * bid_vol + best_bid * ask_vol) / total

    def micro_signal(self, mid: float, microprice: float, imbalance: float) -> int:
        signal = 0
        if microprice > mid:
            signal += 1
        elif microprice < mid:
            signal -= 1
        if imbalance > 0.5:
            signal += 1
        elif imbalance < -0.5:
            signal -= 1
        return signal


# =========================================================================
# PEBBLES TRADER
# =========================================================================

class PebblesTrader:
    PRODUCTS = [
        "PEBBLES_L",
        "PEBBLES_M",
        "PEBBLES_S",
        "PEBBLES_XL",
        "PEBBLES_XS",
    ]

    LIMITS = {
        "PEBBLES_L": 10,
        "PEBBLES_M": 10,
        "PEBBLES_S": 10,
        "PEBBLES_XL": 10,
        "PEBBLES_XS": 10,
    }

    RATIO_WINDOW = 300
    MIN_RATIO_HISTORY = 60

    ENTRY_Z = 2.0
    EXIT_Z = 0.45
    PANIC_Z = 4.0

    STAT_ARB_BASE_SIZE = 1
    STAT_ARB_MAX_SIZE = 4

    XS_MM_SIZE = 1
    S_MM_SIZE = 2
    LM_MM_SIZE = 1

    MICROPRICE_EDGE_MULT = 0.15
    IMBALANCE_EDGE_MULT = 1.5

    XS_SHORT_DRIFT_SKEW = -1.5
    INVENTORY_SKEW = 0

    MIN_SPREAD_TO_MM = {
        "PEBBLES_XS": 9,
        "PEBBLES_S": 11,
        "PEBBLES_L": 13,
        "PEBBLES_M": 13,
        "PEBBLES_XL": 17,
    }

    BASKET_PRODUCTS = [
        "PEBBLES_L",
        "PEBBLES_M",
        "PEBBLES_S",
        "PEBBLES_XS",
    ]

    def run(self, state: TradingState):
        orders: Dict[Symbol, List[Order]] = {p: [] for p in self.PRODUCTS}

        data = self.load_data(state.traderData)

        mids = {}
        best_bids = {}
        best_asks = {}
        microprices = {}
        imbalances = {}

        for product in self.PRODUCTS:
            depth = state.order_depths.get(product)
            if depth is None:
                continue
            best_bid, best_ask = self.best_bid_ask(depth)
            if best_bid is None or best_ask is None:
                continue
            mids[product] = (best_bid + best_ask) / 2
            best_bids[product] = best_bid
            best_asks[product] = best_ask
            microprices[product] = self.microprice(depth)
            imbalances[product] = self.imbalance(depth)

        z = None

        if all(p in mids for p in self.PRODUCTS):
            self.update_ratio_history(data, mids)
            z = self.compute_basket_z(data)

            if z is not None:
                self.manage_stat_arb_position(
                    state=state,
                    orders=orders,
                    mids=mids,
                    best_bids=best_bids,
                    best_asks=best_asks,
                    microprices=microprices,
                    imbalances=imbalances,
                    z=z,
                )

        for product in self.PRODUCTS:
            if product not in mids:
                continue
            if product == "PEBBLES_XL":
                continue

            self.market_make(
                state=state,
                orders=orders,
                product=product,
                mid=mids[product],
                best_bid=best_bids[product],
                best_ask=best_asks[product],
                microprice=microprices[product],
                imbalance=imbalances[product],
            )

        orders = {k: v for k, v in orders.items() if v}
        trader_data = json.dumps(data, separators=(",", ":"))
        return orders, 0, trader_data

    def load_data(self, trader_data: str) -> Dict[str, Any]:
        if trader_data:
            try:
                data = json.loads(trader_data)
            except Exception:
                data = {}
        else:
            data = {}

        if "basket_ratios" not in data:
            data["basket_ratios"] = []

        return data

    def update_ratio_history(self, data, mids):
        basket = (
            mids["PEBBLES_L"]
            + mids["PEBBLES_M"]
            + mids["PEBBLES_S"]
            + mids["PEBBLES_XS"]
        ) / 4

        xl = mids["PEBBLES_XL"]
        if xl <= 0:
            return

        ratio = basket / xl
        data["basket_ratios"].append(ratio)
        if len(data["basket_ratios"]) > self.RATIO_WINDOW:
            data["basket_ratios"] = data["basket_ratios"][-self.RATIO_WINDOW:]

    def compute_basket_z(self, data):
        hist = data.get("basket_ratios", [])
        if len(hist) < self.MIN_RATIO_HISTORY:
            return None
        current = hist[-1]
        mean = sum(hist) / len(hist)
        variance = sum((x - mean) ** 2 for x in hist) / len(hist)
        std = math.sqrt(variance)
        if std <= 1e-9:
            return None
        return (current - mean) / std

    def manage_stat_arb_position(self, state, orders, mids, best_bids, best_asks, microprices, imbalances, z):
        if abs(z) < self.ENTRY_Z:
            return
        if abs(z) > self.PANIC_Z:
            base_size = 1
        else:
            base_size = min(self.STAT_ARB_MAX_SIZE,
                            max(1, int(self.STAT_ARB_BASE_SIZE * abs(z) / self.ENTRY_Z)))

        if z > self.ENTRY_Z:
            self.open_short_basket_long_xl(state, orders, best_bids, best_asks, mids, microprices, imbalances, base_size)
        elif z < -self.ENTRY_Z:
            self.open_long_basket_short_xl(state, orders, best_bids, best_asks, mids, microprices, imbalances, base_size)

    def open_short_basket_long_xl(self, state, orders, best_bids, best_asks, mids, microprices, imbalances, base_size):
        xl_pos = state.position.get("PEBBLES_XL", 0)
        xl_buy_capacity = self.LIMITS["PEBBLES_XL"] - xl_pos
        if xl_buy_capacity <= 0:
            return

        basket_trade_count = 0
        for product in self.BASKET_PRODUCTS:
            pos = state.position.get(product, 0)
            sell_capacity = self.LIMITS[product] + pos
            if sell_capacity <= 0:
                continue
            signal = self.micro_signal(
                mid=mids[product],
                microprice=microprices[product],
                imbalance=imbalances[product],
            )
            size = base_size
            if signal < 0:
                size += 1
            size = min(size, sell_capacity)
            if size > 0:
                orders[product].append(Order(product, best_bids[product], -size))
                basket_trade_count += size

        xl_size = min(xl_buy_capacity, max(1, basket_trade_count // 2))
        if xl_size > 0:
            orders["PEBBLES_XL"].append(Order("PEBBLES_XL", best_asks["PEBBLES_XL"], xl_size))

    def open_long_basket_short_xl(self, state, orders, best_bids, best_asks, mids, microprices, imbalances, base_size):
        xl_pos = state.position.get("PEBBLES_XL", 0)
        xl_sell_capacity = self.LIMITS["PEBBLES_XL"] + xl_pos
        if xl_sell_capacity <= 0:
            return

        basket_trade_count = 0
        for product in self.BASKET_PRODUCTS:
            pos = state.position.get(product, 0)
            buy_capacity = self.LIMITS[product] - pos
            if buy_capacity <= 0:
                continue
            signal = self.micro_signal(
                mid=mids[product],
                microprice=microprices[product],
                imbalance=imbalances[product],
            )
            size = base_size
            if signal > 0:
                size += 1
            size = min(size, buy_capacity)
            if size > 0:
                orders[product].append(Order(product, best_asks[product], size))
                basket_trade_count += size

        xl_size = min(xl_sell_capacity, max(1, basket_trade_count // 2))
        if xl_size > 0:
            orders["PEBBLES_XL"].append(Order("PEBBLES_XL", best_bids["PEBBLES_XL"], -xl_size))

    def market_make(self, state, orders, product, mid, best_bid, best_ask, microprice, imbalance):
        spread = best_ask - best_bid
        if spread < self.MIN_SPREAD_TO_MM[product]:
            return

        pos = state.position.get(product, 0)
        limit = self.LIMITS[product]

        if product == "PEBBLES_XS":
            size = self.XS_MM_SIZE
        elif product == "PEBBLES_S":
            size = self.S_MM_SIZE
        else:
            size = self.LM_MM_SIZE

        fair = mid
        fair += self.MICROPRICE_EDGE_MULT * (microprice - mid)
        fair += self.IMBALANCE_EDGE_MULT * imbalance

        if product == "PEBBLES_XS":
            fair += self.XS_SHORT_DRIFT_SKEW

        fair -= self.INVENTORY_SKEW * pos

        bid_price = int(math.floor(fair - spread * 0.35))
        ask_price = int(math.ceil(fair + spread * 0.35))

        bid_price = min(bid_price, best_bid + 1)
        ask_price = max(ask_price, best_ask - 1)

        buy_qty = min(size, limit - pos)
        sell_qty = min(size, limit + pos)

        if buy_qty > 0:
            orders[product].append(Order(product, bid_price, buy_qty))
        if sell_qty > 0:
            orders[product].append(Order(product, ask_price, -sell_qty))

    def best_bid_ask(self, depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders:
            return None, None
        return max(depth.buy_orders.keys()), min(depth.sell_orders.keys())

    def imbalance(self, depth: OrderDepth) -> float:
        if not depth.buy_orders or not depth.sell_orders:
            return 0.0
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        bid_vol = abs(depth.buy_orders[best_bid])
        ask_vol = abs(depth.sell_orders[best_ask])
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    def microprice(self, depth: OrderDepth) -> float:
        if not depth.buy_orders or not depth.sell_orders:
            return 0.0
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        bid_vol = abs(depth.buy_orders[best_bid])
        ask_vol = abs(depth.sell_orders[best_ask])
        total = bid_vol + ask_vol
        if total == 0:
            return (best_bid + best_ask) / 2
        return (best_ask * bid_vol + best_bid * ask_vol) / total

    def micro_signal(self, mid: float, microprice: float, imbalance: float) -> int:
        signal = 0
        if microprice > mid:
            signal += 1
        elif microprice < mid:
            signal -= 1
        if imbalance > 0.5:
            signal += 1
        elif imbalance < -0.5:
            signal -= 1
        return signal


# =========================================================================
# ROBOT DISHES TRADER
# =========================================================================

class RobotDishesTrader:
    PRODUCT = "ROBOT_DISHES"
    LIMIT = 10

    HISTORY_LIMIT = 1500

    REGIME_WINDOW = 600
    MIN_HISTORY = 600

    ACF1_THRESHOLD = -0.08
    ZERO_RATE_THRESHOLD = 0.30
    NET_MOVE_THRESHOLD = 150

    FAIR_WINDOW = 10
    TAKER_THRESHOLD = 3.0
    TAKER_SIZE = 4

    MAX_LOSS = -1000
    KILL_SWITCH_KEY = "killed"

    def run(self, state: TradingState):
        data = self.load_data(state.traderData)
        orders_by_product: Dict[str, List[Order]] = {}

        if self.PRODUCT not in state.order_depths:
            return {}, 0, json.dumps(data)

        od = state.order_depths[self.PRODUCT]
        position = int(state.position.get(self.PRODUCT, 0))

        if not od.buy_orders or not od.sell_orders:
            return {}, 0, json.dumps(data)

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)
        mid = (best_bid + best_ask) / 2

        if "cash" not in data:
            data["cash"] = 0.0
        if "last_position" not in data:
            data["last_position"] = position
        if self.KILL_SWITCH_KEY not in data:
            data[self.KILL_SWITCH_KEY] = False

        prev_pos = int(data.get("last_position", 0))
        delta_pos = position - prev_pos

        data["cash"] -= delta_pos * mid
        data["last_position"] = position

        mtm_pnl = data["cash"] + position * mid
        data["mtm_pnl"] = mtm_pnl

        if mtm_pnl <= self.MAX_LOSS:
            data[self.KILL_SWITCH_KEY] = True

        if data.get(self.KILL_SWITCH_KEY, False):
            orders_by_product[self.PRODUCT] = self.flatten_position(od, position)
            return orders_by_product, 0, json.dumps(data)

        orders = self.trade_dishes(od, position, data)
        if orders:
            orders_by_product[self.PRODUCT] = orders

        return orders_by_product, 0, json.dumps(data)

    def trade_dishes(self, od, position, data):
        orders: List[Order] = []

        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        bid_vol = int(od.buy_orders[best_bid])
        ask_vol = -int(od.sell_orders[best_ask])

        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid

        self.update_history(mid, data)
        taker_enabled = self.regime_ok(data)

        if taker_enabled:
            orders += self.taker_alpha(best_bid, best_ask, bid_vol, ask_vol, position, data)

        used_buy = sum(o.quantity for o in orders if o.quantity > 0)
        used_sell = -sum(o.quantity for o in orders if o.quantity < 0)
        effective_position = position + used_buy - used_sell

        if taker_enabled:
            base_size = 1
            max_size = 2
            min_spread = 7
        else:
            base_size = 1
            max_size = 1
            min_spread = 8

        orders += self.defensive_mm(
            best_bid, best_ask, bid_vol, ask_vol, effective_position,
            spread, base_size, max_size, min_spread,
        )

        return orders

    def regime_ok(self, data):
        mids = data.get("mid", [])
        if len(mids) < self.MIN_HISTORY:
            return False

        window = mids[-self.REGIME_WINDOW:]
        diffs = []
        zero_count = 0

        for i in range(1, len(window)):
            d = window[i] - window[i - 1]
            diffs.append(d)
            if d == 0:
                zero_count += 1

        if len(diffs) < 10:
            return False

        mean = sum(diffs) / len(diffs)
        var = sum((x - mean) ** 2 for x in diffs)

        if var == 0:
            acf1 = -1.0
        else:
            cov = sum(
                (diffs[i] - mean) * (diffs[i - 1] - mean)
                for i in range(1, len(diffs))
            )
            acf1 = cov / var

        zero_rate = zero_count / len(diffs)
        net_move = window[-1] - window[0]

        return (
            acf1 < self.ACF1_THRESHOLD
            and zero_rate > self.ZERO_RATE_THRESHOLD
            and net_move > self.NET_MOVE_THRESHOLD
        )

    def taker_alpha(self, best_bid, best_ask, bid_vol, ask_vol, position, data):
        orders: List[Order] = []
        mids = data.get("mid", [])

        if len(mids) < self.FAIR_WINDOW:
            return orders

        fair = sum(mids[-self.FAIR_WINDOW:]) / self.FAIR_WINDOW

        if best_ask < fair - self.TAKER_THRESHOLD and position < self.LIMIT:
            size = min(self.TAKER_SIZE, ask_vol, self.LIMIT - position)
            if size > 0:
                orders.append(Order(self.PRODUCT, best_ask, size))

        if best_bid > fair + self.TAKER_THRESHOLD and position > -self.LIMIT:
            size = min(self.TAKER_SIZE, bid_vol, self.LIMIT + position)
            if size > 0:
                orders.append(Order(self.PRODUCT, best_bid, -size))

        return orders

    def defensive_mm(self, best_bid, best_ask, bid_vol, ask_vol, position,
                     spread, base_size, max_size, min_spread):
        orders: List[Order] = []

        if spread < min_spread:
            return orders

        buy_price = best_bid + 1
        sell_price = best_ask - 1

        inv_ratio = position / self.LIMIT

        if inv_ratio > 0.3:
            buy_price -= 2
            sell_price -= 1
        elif inv_ratio < -0.3:
            buy_price += 1
            sell_price += 2

        buy_price = min(buy_price, best_ask - 1)
        sell_price = max(sell_price, best_bid + 1)

        if buy_price >= sell_price:
            return orders

        size = base_size
        if spread >= min_spread + 2:
            size += 1
        size = min(size, max_size)

        buy_size = size
        sell_size = size

        if position > 0:
            buy_size = max(0, buy_size - 1)
            sell_size = min(max_size, sell_size + 1)
        elif position < 0:
            sell_size = max(0, sell_size - 1)
            buy_size = min(max_size, buy_size + 1)

        if position >= 7:
            buy_size = 0
            sell_size = max(sell_size, 2)
        elif position <= -7:
            sell_size = 0
            buy_size = max(buy_size, 2)

        buy_size = min(buy_size, ask_vol, self.LIMIT - position)
        sell_size = min(sell_size, bid_vol, self.LIMIT + position)

        if buy_size > 0:
            orders.append(Order(self.PRODUCT, buy_price, buy_size))
        if sell_size > 0:
            orders.append(Order(self.PRODUCT, sell_price, -sell_size))

        return orders

    def flatten_position(self, od, position):
        orders: List[Order] = []

        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        bid_vol = int(od.buy_orders[best_bid])
        ask_vol = -int(od.sell_orders[best_ask])

        if position > 0:
            size = min(position, bid_vol)
            if size > 0:
                orders.append(Order(self.PRODUCT, best_bid, -size))
        elif position < 0:
            size = min(-position, ask_vol)
            if size > 0:
                orders.append(Order(self.PRODUCT, best_ask, size))

        return orders

    def update_history(self, mid, data):
        if "mid" not in data:
            data["mid"] = []
        data["mid"].append(mid)
        if len(data["mid"]) > self.HISTORY_LIMIT:
            data["mid"] = data["mid"][-self.HISTORY_LIMIT:]

    def load_data(self, trader_data):
        if trader_data:
            try:
                return json.loads(trader_data)
            except Exception:
                return {}
        return {}


# =========================================================================
# TOP-LEVEL DISPATCHER
# =========================================================================

class Trader:
    SUB_KEYS = [
        "microchip",
        "translator",
        "snackpack",
        "galaxy",
        "panel",
        "sleeppod",
        "pebbles",
        "robot",
    ]

    def __init__(self) -> None:
        self.subs = {
            "microchip":  MicrochipTrader(),
            "translator": TranslatorTrader(),
            "snackpack":  SnackpackTrader(),
            "galaxy":     GalaxySoundsTrader(),
            "panel":      PanelUVTrader(),
            "sleeppod":   SleepPodTrader(),
            "pebbles":    PebblesTrader(),
            "robot":      RobotDishesTrader(),
        }

    def _split_trader_data(self, blob: str) -> Dict[str, str]:
        if not blob:
            return {k: "" for k in self.SUB_KEYS}
        try:
            parsed = json.loads(blob)
            if not isinstance(parsed, dict):
                return {k: "" for k in self.SUB_KEYS}
            return {k: parsed.get(k, "") for k in self.SUB_KEYS}
        except Exception:
            return {k: "" for k in self.SUB_KEYS}

    def run(self, state: TradingState):
        sub_blobs = self._split_trader_data(state.traderData)

        merged_orders: Dict[Symbol, List[Order]] = {}
        total_conversions = 0
        new_blobs: Dict[str, str] = {}

        original_td = state.traderData
        try:
            for key in self.SUB_KEYS:
                sub = self.subs[key]
                state.traderData = sub_blobs.get(key, "") or ""
                try:
                    sub_orders, sub_conv, sub_td = sub.run(state)
                except Exception:
                    sub_orders, sub_conv, sub_td = {}, 0, sub_blobs.get(key, "")
                if sub_orders:
                    for sym, ords in sub_orders.items():
                        if not ords:
                            continue
                        merged_orders.setdefault(sym, []).extend(ords)
                total_conversions += int(sub_conv or 0)
                new_blobs[key] = sub_td if isinstance(sub_td, str) else ""
        finally:
            state.traderData = original_td

        merged_td = json.dumps(new_blobs, separators=(",", ":"))

        logger.flush(state, merged_orders, total_conversions, merged_td)
        return merged_orders, total_conversions, merged_td