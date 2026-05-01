import json
import math
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

# ---------------- Shared helpers ----------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if sigma <= 0 or T <= 0 or S <= 0:
        return max(S - K, 0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)

def _bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if sigma <= 0 or T <= 0 or S <= 0:
        return 1.0 if S > K else 0.0
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    return _norm_cdf(d1)

def _implied_vol(mid, S, K, T):
    intrinsic = max(S - K, 0.0)
    if mid <= intrinsic + 1e-6 or mid >= S - 1e-6:
        return None
    lo, hi = 1e-4, 5.0
    for _ in range(60):
        m = 0.5 * (lo + hi)
        if _bs_call(S, K, T, m) > mid:
            hi = m
        else:
            lo = m
        if hi - lo < 1e-5:
            break
    return 0.5 * (lo + hi)

def _fit_smile_quadratic(points):
    n = len(points)
    if n < 3:
        return None
    sx = sum(p[0] for p in points); sx2 = sum(p[0]**2 for p in points)
    sx3 = sum(p[0]**3 for p in points); sx4 = sum(p[0]**4 for p in points)
    sy = sum(p[1] for p in points); sxy = sum(p[0]*p[1] for p in points)
    sx2y = sum(p[0]**2 * p[1] for p in points)
    A = [[n, sx, sx2], [sx, sx2, sx3], [sx2, sx3, sx4]]
    B = [sy, sxy, sx2y]
    for i in range(3):
        piv = A[i][i]
        if abs(piv) < 1e-12:
            return None
        for j in range(i+1, 3):
            f = A[j][i] / piv
            for k in range(3):
                A[j][k] -= f * A[i][k]
            B[j] -= f * B[i]
    if abs(A[2][2]) < 1e-12:
        return None
    c = B[2]/A[2][2]; b = (B[1] - A[1][2]*c)/A[1][1]; a = (B[0] - A[0][1]*b - A[0][2]*c)/A[0][0]
    return (a, b, c)

def _voucher_strike(sym: str):
    if not sym.startswith("VEV_"):
        return None
    try:
        return int(sym.split("_", 1)[1])
    except Exception:
        return None



class Trader:

    def bid(self):
        # Ignored outside Round 2
        return 0

    # NOTE: verify these against the Round 3 position-limits page before the
    # final submission. These are educated guesses based on comparable rounds.
    POSITION_LIMITS: Dict[str, int] = {
        "HYDROGEL_PACK": 50,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 200,
        "VEV_5200": 200,
        "VEV_5300": 200,
        "VEV_5400": 200,
        "VEV_5500": 200,
    }

    # Options excluded due to no realized volume in training data:
    #   VEV_4500, VEV_5000, VEV_5100 — 1 trade each over 3 days
    #   VEV_6000, VEV_6500           — all trades at price 0 (worthless)
    ACTIVE_PRODUCTS = set(POSITION_LIMITS.keys())

    # Per-product MM parameters. Fixed-price commodities tolerate more
    # aggressive taking and wider quotes; voucher markets are quieter so
    # we quote smaller and cross less.
    PARAMS: Dict[str, Dict[str, Any]] = {
        "HYDROGEL_PACK": {
            "ema_alpha": 0.40,        # responsive — 16-pt spread jitters
            "quote_size": 15,
            "take_threshold": 3,      # take only when edge ≥ 3
            "max_divergence": 40,     # disable taking if |mid−EMA| > 40
            "crash_divergence": 120,  # flatten if anchor truly breaks
        },
        "VELVETFRUIT_EXTRACT": {
            "ema_alpha": 0.40,
            "quote_size": 20,       # was 25 — smaller passive quote wins on
                                    # trending days (less adverse selection)
            "take_threshold": 1,    # was 2 — tighter take captures more edge
            "max_divergence": 20,
            "crash_divergence": 80,
        },
        # Voucher defaults: active BS-fair mode (see voucher_orders).
        # EMA/max_divergence/crash_divergence are kept only for schema
        # compatibility; the voucher path doesn't use them.
        "_VOUCHER": {
            "ema_alpha": 0.40,
            "quote_size": 30,       # model gives us a real fair value, so
                                    # we can quote big on both sides
            "take_threshold": 0.5,  # lift/hit on ≥ 1 tick of model edge
            "max_divergence": 8,
            "crash_divergence": 30,
            # Fair must stay within this fraction of market mid for us to
            # trust the model and act on it. Otherwise we go flat for the tick.
            "fair_sanity_frac": 0.25,
        },
    }

    # Underlying used to price the VEV_* call options. Intrinsic = max(0, S-K).
    VOUCHER_UNDERLYING = "VELVETFRUIT_EXTRACT"

    # Strikes used purely for IV calibration (not necessarily traded). Near-ATM
    # strikes give the most reliable implied vol.
    CALIBRATION_MONEYNESS = 0.06  # use strikes within ±6% of spot for IV fit

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

    BS_T = 0.5

    def _run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}
        conversions = 0

        saved = self._parse_trader_data(state.traderData)
        ema_state: Dict[str, float] = dict(saved.get("ema", {}))
        prev_mid_state: Dict[str, float] = dict(saved.get("prev_mid", {}))

        # Strategy A: per-voucher smile fit, reprice ONLY vouchers whose own IV
        # was in the fit set (deep ITM/OTM fall back to EMA).
        model_fair: Dict[str, float] = {}
        velv_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        S = None
        if velv_depth and velv_depth.buy_orders and velv_depth.sell_orders:
            S = (max(velv_depth.buy_orders.keys()) + min(velv_depth.sell_orders.keys())) / 2.0

        if S is not None:
            iv_list = []  # (sym, x, iv, K)
            for sym, depth in state.order_depths.items():
                K = _voucher_strike(sym)
                if K is None or sym not in self.ACTIVE_PRODUCTS:
                    continue
                if not depth.buy_orders or not depth.sell_orders:
                    continue
                mid = (max(depth.buy_orders.keys()) + min(depth.sell_orders.keys())) / 2.0
                iv = _implied_vol(mid, S, K, self.BS_T)
                if iv is None or iv < 0.01 or iv > 3.0:
                    continue
                x = math.log(K / S)
                iv_list.append((sym, x, iv, K))

            if len(iv_list) >= 3:
                fit = _fit_smile_quadratic([(x, iv) for _, x, iv, _ in iv_list])
                if fit is not None:
                    a, b, c = fit
                    for sym, x, _, K in iv_list:
                        sig_fit = a + b*x + c*x*x
                        if sig_fit < 0.01 or sig_fit > 5.0:
                            continue
                        mf = _bs_call(S, K, self.BS_T, sig_fit)
                        if mf > 0 and mf < S:
                            model_fair[sym] = mf

        voucher_fairs, underlying_spot, consensus_v = self._compute_voucher_fairs(
            state.order_depths
        )
        if underlying_spot is not None:
            logger.print(
                f"VOUCHER_MODEL | S={underlying_spot:.2f} v={consensus_v:.4f} "
                f"fairs={ {p: f'{f:.2f}' for p, f in voucher_fairs.items()} }"
            )

        for product, order_depth in state.order_depths.items():
            if product not in self.ACTIVE_PRODUCTS:
                # Skip dead/worthless strikes entirely.
                result[product] = []
                continue

            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS[product]
            params = self._params_for(product)

            try:
                if not order_depth.buy_orders or not order_depth.sell_orders:
                    result[product] = []
                    continue

                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())
                if best_bid >= best_ask:
                    result[product] = []
                    continue

                mid = (best_bid + best_ask) / 2.0

                if product.startswith("VEV_") and product in voucher_fairs:
                    fair = voucher_fairs[product]
                    logger.print(
                        f"{product} | pos={position} bid={best_bid} ask={best_ask} "
                        f"mid={mid:.2f} fair={fair:.2f} div={mid-fair:+.2f}"
                    )
                    orders = self.voucher_orders(
                        product=product,
                        order_depth=order_depth,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        mid=mid,
                        fair=fair,
                        position=position,
                        limit=limit,
                        params=params,
                    )
                else:
                    prev_ema = ema_state.get(product)
                    alpha = params["ema_alpha"]
                    anchor = mid if prev_ema is None else alpha * mid + (1 - alpha) * prev_ema
                    ema_state[product] = anchor

                    prev_mid = prev_mid_state.get(product)
                    prev_mid_state[product] = mid

                    logger.print(
                        f"{product} | pos={position} bid={best_bid} ask={best_ask} "
                        f"mid={mid:.2f} ema={anchor:.2f} div={mid-anchor:+.2f}"
                    )

                    orders = self.mm_orders(
                        product=product,
                        order_depth=order_depth,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        mid=mid,
                        position=position,
                        limit=limit,
                        anchor=anchor,
                        prev_mid=prev_mid,
                        params=params,
                    )
            except Exception as e:
                logger.print(f"ERROR in {product}: {e}")
                orders = []

            orders = self._clamp_to_position_limit(orders, position, limit)
            if orders:
                logger.print(
                    f"{product} orders: {[(o.price, o.quantity) for o in orders]}"
                )
            result[product] = orders

        trader_data = json.dumps({
            "ema": ema_state,
            "prev_mid": prev_mid_state,
        })
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    @classmethod
    def _params_for(cls, product: str) -> Dict[str, Any]:
        if product in cls.PARAMS:
            return cls.PARAMS[product]
        return cls.PARAMS["_VOUCHER"]

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
        # Independently truncate buy and sell sides so nothing upstream can
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

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @classmethod
    def _bs_call(cls, S: float, K: float, v: float) -> float:
        if v <= 1e-9 or S <= 0 or K <= 0:
            return max(0.0, S - K)
        d1 = (math.log(S / K) + 0.5 * v * v) / v
        d2 = d1 - v
        return S * cls._norm_cdf(d1) - K * cls._norm_cdf(d2)

    @classmethod
    def _implied_v(cls, S: float, K: float, C: float) -> float:
        intrinsic = max(0.0, S - K)
        if C <= intrinsic + 1e-6:
            return 0.0
        lo, hi = 1e-3, 3.0
        c_hi = cls._bs_call(S, K, hi)
        if C >= c_hi:
            return hi
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if cls._bs_call(S, K, mid) < C:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-6:
                break
        return 0.5 * (lo + hi)

    @classmethod
    def _compute_voucher_fairs(
        cls, order_depths: Dict[Symbol, OrderDepth]
    ) -> tuple:
        """Return (fair_by_product, spot, consensus_v).

        Calibrates a single implied vol v = σ√T from near-ATM vouchers, then
        prices every listed VEV_* with Black–Scholes using that v. We don't
        need to separate σ from T — only v shows up in pricing.
        """
        ud = order_depths.get(cls.VOUCHER_UNDERLYING)
        if ud is None or not ud.buy_orders or not ud.sell_orders:
            return {}, None, 0.0
        S = (max(ud.buy_orders.keys()) + min(ud.sell_orders.keys())) / 2.0

        records: List[tuple] = []
        for product, od in order_depths.items():
            if not product.startswith("VEV_"):
                continue
            try:
                K = float(product.split("_")[1])
            except Exception:
                continue
            if not od.buy_orders or not od.sell_orders:
                continue
            bb = max(od.buy_orders.keys())
            ba = min(od.sell_orders.keys())
            if bb >= ba:
                continue
            m = (bb + ba) / 2.0
            records.append((product, K, m))

        if not records:
            return {}, S, 0.0

        vs: List[float] = []
        for _, K, m in records:
            if abs(K - S) / max(S, 1.0) > cls.CALIBRATION_MONEYNESS:
                continue
            v = cls._implied_v(S, K, m)
            if 1e-3 < v < 3.0:
                vs.append(v)

        if not vs:
            for _, K, m in records:
                v = cls._implied_v(S, K, m)
                if 1e-3 < v < 3.0:
                    vs.append(v)

        if not vs:
            return {p: m for p, _, m in records}, S, 0.0

        vs.sort()
        v_consensus = vs[len(vs) // 2]

        fairs: Dict[str, float] = {}
        for product, K, _ in records:
            fairs[product] = cls._bs_call(S, K, v_consensus)
        return fairs, S, v_consensus

    @classmethod
    def voucher_orders(
        cls,
        product: str,
        order_depth: OrderDepth,
        best_bid: int,
        best_ask: int,
        mid: float,
        fair: float,
        position: int,
        limit: int,
        params: Dict[str, Any],
    ) -> List[Order]:
        """Active option-MM: BS fair from underlying + inventory-skewed book.

          1) cross the spread on any ask ≤ fair − edge  /  bid ≥ fair + edge
          2) post tight size around fair, skewing quotes toward reducing inventory
          3) if the model disagrees wildly with market, go flat for the tick
        """
        quote_size = params["quote_size"]
        take_threshold = params["take_threshold"]
        sanity_frac = params.get("fair_sanity_frac", 0.25)

        # Sanity: if fair and mid are wildly apart, trust the market, sit out.
        if abs(fair - mid) > max(2.0, sanity_frac * max(mid, 1.0)):
            return []

        orders: List[Order] = []
        remaining_buy = max(0, limit - position)
        remaining_sell = max(0, limit + position)

        skew = position / float(max(limit, 1))  # in [-1, 1], +ve = long
        take_buy_edge = take_threshold * (1.0 + max(0.0, skew))
        take_sell_edge = take_threshold * (1.0 + max(0.0, -skew))

        # 1) Cross the spread when market is off from model fair.
        for ask_price in sorted(order_depth.sell_orders.keys()):
            if remaining_buy <= 0:
                break
            if ask_price <= fair - take_buy_edge:
                ask_vol = -order_depth.sell_orders[ask_price]
                qty = min(remaining_buy, ask_vol)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    remaining_buy -= qty
            else:
                break

        for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
            if remaining_sell <= 0:
                break
            if bid_price >= fair + take_sell_edge:
                bid_vol = order_depth.buy_orders[bid_price]
                qty = min(remaining_sell, bid_vol)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    remaining_sell -= qty
            else:
                break

        # 2) Active quoting. We'll improve the BBO by one tick if fair allows,
        # join otherwise, and be willing to sit at fair if it's outside BBO.
        fair_floor = int(math.floor(fair))
        fair_ceil = int(math.ceil(fair))

        if best_bid + 1 <= fair_floor and best_bid + 1 < best_ask:
            our_bid = best_bid + 1
        elif best_bid <= fair_floor:
            our_bid = best_bid
        else:
            our_bid = fair_floor

        if best_ask - 1 >= fair_ceil and best_ask - 1 > best_bid:
            our_ask = best_ask - 1
        elif best_ask >= fair_ceil:
            our_ask = best_ask
        else:
            our_ask = fair_ceil

        if our_bid >= our_ask:
            our_bid = fair_floor - 1
            our_ask = fair_ceil + 1

        buy_qty = min(int(quote_size * max(0.2, 1.0 - skew)), remaining_buy)
        sell_qty = min(int(quote_size * max(0.2, 1.0 + skew)), remaining_sell)

        if buy_qty > 0 and our_bid < best_ask:
            orders.append(Order(product, int(our_bid), buy_qty))
        if sell_qty > 0 and our_ask > best_bid:
            orders.append(Order(product, int(our_ask), -sell_qty))

        return orders

    @classmethod
    def mm_orders(
        cls,
        product: str,
        order_depth: OrderDepth,
        best_bid: int,
        best_ask: int,
        mid: float,
        position: int,
        limit: int,
        anchor: float,
        prev_mid: Any,
        params: Dict[str, Any],
    ) -> List[Order]:
        """Fixed-price-style MM with a dynamic EMA anchor instead of a hard-coded one.
        Same three-stage shape as the R2 ASH_COATED_OSMIUM engine:
          1) aggressive taking when prices are past anchor ± threshold
          2) flatten inventory at the anchor
          3) passive quoting inside the effective spread
        """
        orders: List[Order] = []

        take_threshold = params["take_threshold"]
        quote_size = params["quote_size"]
        max_divergence = params["max_divergence"]
        crash_divergence = params["crash_divergence"]

        fair_int = int(round(anchor))

        # Guards
        anchor_divergence_safe = abs(mid - anchor) <= max_divergence
        mid_jumped = (
            isinstance(prev_mid, (int, float))
            and abs(mid - prev_mid) > max(max_divergence, 10)
        )
        take_safe = anchor_divergence_safe and not mid_jumped

        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)
        remaining_buy = buy_capacity
        remaining_sell = sell_capacity

        # Emergency flatten: if the anchor is very wrong, scramble out of
        # inventory and skip new quoting this tick.
        if abs(mid - anchor) > crash_divergence and position != 0:
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
            return orders

        # 1) Aggressive take against the EMA anchor
        if take_safe:
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if remaining_buy <= 0:
                    break
                if ask_price <= anchor - take_threshold:
                    ask_vol = -order_depth.sell_orders[ask_price]
                    qty = min(remaining_buy, ask_vol)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        remaining_buy -= qty
                else:
                    break

            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if remaining_sell <= 0:
                    break
                if bid_price >= anchor + take_threshold:
                    bid_vol = order_depth.buy_orders[bid_price]
                    qty = min(remaining_sell, bid_vol)
                    if qty > 0:
                        orders.append(Order(product, bid_price, -qty))
                        remaining_sell -= qty
                else:
                    break

        # 2) Flatten residual inventory at the anchor if a resting counterparty
        #    is sitting exactly at fair_int.
        effective_position = position + sum(o.quantity for o in orders)
        if effective_position < 0 and remaining_buy > 0:
            if fair_int in order_depth.sell_orders:
                ask_vol = -order_depth.sell_orders[fair_int]
                qty = min(remaining_buy, ask_vol, abs(effective_position))
                if qty > 0:
                    orders.append(Order(product, fair_int, qty))
                    remaining_buy -= qty
                    effective_position += qty
        elif effective_position > 0 and remaining_sell > 0:
            if fair_int in order_depth.buy_orders:
                bid_vol = order_depth.buy_orders[fair_int]
                qty = min(remaining_sell, bid_vol, abs(effective_position))
                if qty > 0:
                    orders.append(Order(product, fair_int, -qty))
                    remaining_sell -= qty
                    effective_position -= qty

        # 3) Passive quoting inside the effective spread.
        # Recompute effective best bid/ask after the taking pass, since levels
        # we lifted are no longer available to rest against.
        effective_best_ask = fair_int + 1
        for ask_lvl in sorted(order_depth.sell_orders.keys()):
            book_vol = -order_depth.sell_orders[ask_lvl]
            bought_at_lvl = sum(
                o.quantity for o in orders if o.quantity > 0 and o.price == ask_lvl
            )
            if bought_at_lvl < book_vol:
                effective_best_ask = ask_lvl
                break

        effective_best_bid = fair_int - 1
        for bid_lvl in sorted(order_depth.buy_orders.keys(), reverse=True):
            book_vol = order_depth.buy_orders[bid_lvl]
            sold_at_lvl = sum(
                -o.quantity for o in orders if o.quantity < 0 and o.price == bid_lvl
            )
            if sold_at_lvl < book_vol:
                effective_best_bid = bid_lvl
                break

        spread = effective_best_ask - effective_best_bid
        if spread >= 2:
            bid_price = effective_best_bid + 1
            ask_price = effective_best_ask - 1
        else:
            bid_price = effective_best_bid
            ask_price = effective_best_ask

        # Never buy above fair or sell below fair.
        bid_price = min(bid_price, effective_best_ask - 1, fair_int)
        ask_price = max(ask_price, effective_best_bid + 1, fair_int)
        if bid_price >= ask_price:
            bid_price = fair_int - 1
            ask_price = fair_int + 1

        passive_safe = anchor_divergence_safe
        passive_buy_qty = min(quote_size, remaining_buy)
        passive_sell_qty = min(quote_size, remaining_sell)

        if passive_safe and passive_buy_qty > 0 and bid_price < fair_int:
            orders.append(Order(product, bid_price, passive_buy_qty))
        if passive_safe and passive_sell_qty > 0 and ask_price > fair_int:
            orders.append(Order(product, ask_price, -passive_sell_qty))

        return orders
