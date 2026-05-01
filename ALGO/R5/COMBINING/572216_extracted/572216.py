"""
microchip_trader_v3.py — round 5 deployment.

4-sleeve microchip mean-reversion (basket3, basket4, TRI idio, RECT MR)
gated by a priority + partial budget manager. Single trading day; state
resets when timestamp returns to 0.

v3 patches over baseline microchip_trader.py:
  - A_basket3   max_units 4→5,  max_hold 1500→700
  - B_basket4                   max_hold 1500→900
  - D_rect_mr                   max_hold  400→700
  - WARMUP_EXIT_COOLDOWN=100 ticks blocks re-entry after warmup time-stop
Validated 3-day backtest: +$24,322 (+32%) vs baseline.

Post-review revisions (see analysis/v3_review_findings.md):
  - E_oval_idio dropped: cum-residual fails ADF on every day (p=0.16/0.69/0.41)
    and contributed only ~$5k of $100k. Bespoke z=1.5 / warmup=off knobs
    were defending a non-stationary signal.
  - C_tri_idio direction "short" → "both": short-only beat long-only by
    $4.3k, but bidirectional beat short-only by $4.3k. The asymmetry was a
    fitted carve-out, not a signal property. C still flagged: cum-residual
    also fails ADF day-by-day (p=0.15/0.53/0.48); kept for the +$8.6k
    in-sample contribution but signal evidence is weaker than basket3.
Combined revision validated: 3-day backtest $99,728 (vs $100,268 baseline,
-$540, ~flat) with materially cleaner signal-quality story.
"""

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
from typing import Any, Dict, List
import json
import jsonpickle
import math


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
WARMUP_EXIT_COOLDOWN = 100  # ticks; block re-entry after warmup time-stop

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
    """Shift-invariant idio z: cum-residual series of length `window`."""
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
    """Returns (z, regime) where regime in {"long", "short", None}."""
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


class Trader:
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

        # pending-hedge guard: any chip whose intent doesn't match position
        pre_intent = current_total_legs(sleeves_st)
        chips_with_pending = set()
        for c in CHIPS:
            if pre_intent[c] != state.position.get(c, 0):
                chips_with_pending.add(c)

        z_by_sleeve = {sid: compute_z_for_sleeve(sid, tstate, tick) for sid in SLEEVE_ORDER}

        # Phase 1: exits (unconditional)
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
                # Warmup time-stop triggers cooldown to prevent the
                # warmup→long handoff from doubling position size on the
                # same signal extreme.
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

        # Phase 2: entries
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

        # Phase 3: build orders to reach final intent
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
        logger.flush(state, result, 0, traderData)
        return result, 0, traderData