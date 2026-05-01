from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import math


class Trader:
    """
    Round 5 Vertical Sleeping Pods strategy, v4 IMC-horizon safe. Same signals as v3, with full-size early windows that passed all-day direction checks.

    Trades only:
      - SLEEP_POD_COTTON
      - SLEEP_POD_LAMB_WOOL
      - SLEEP_POD_NYLON
      - SLEEP_POD_POLYESTER
      - SLEEP_POD_SUEDE

    Signal stack, ordered by trust:
      1. robust intraday schedule windows that moved the same direction on days 2/3/4
      2. product-vs-Sleep-Pod-basket deviation mean reversion
      3. strongest pair-spread mean reversion relationships
      4. own historical price-level mean reversion as confirmation
      5. microprice/spread fair-value skews for execution
    """

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

    # residual = mid_i - beta_i * mean(other four Sleep Pod mids)
    BETA_TO_EX_SELF_GROUP = {
        "COTTON": 1.4100779123,
        "LAMB_WOOL": 0.0457033203,
        "NYLON": 0.3056936667,
        "POLYESTER": 1.6999748206,
        "SUEDE": 1.2059713707,
    }

    # Historical residual anchors from days 2-4.
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

    # Sleep Pods have strong product-vs-group mean reversion, especially Lamb Wool and Suede.
    RESIDUAL_WEIGHT = {
        "COTTON": 0.65,
        "LAMB_WOOL": 1.00,
        "NYLON": 0.55,
        "POLYESTER": 0.45,
        "SUEDE": 0.95,
    }

    # Coarse overlays: full 100k blocks that moved same direction on every public day.
    # direction: +1 = long, -1 = short
    SCHEDULE_100K: List[Tuple[str, int, int, int, int]] = [
        ("POLYESTER", 100000, 199900, +1, 4),
        ("POLYESTER", 200000, 299900, -1, 4),
        ("SUEDE", 100000, 199900, -1, 3),
        ("SUEDE", 800000, 899900, +1, 4),
        ("SUEDE", 900000, 999900, -1, 3),
    ]

    # 50k windows accepted only when all three days had the same direction,
    # with minimum absolute move >= ~100 ticks and average absolute move >= ~150 ticks.
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
        # IMC sandbox/live horizon is 0-99,900, so these early windows are critical.
        # Accepted only because they are same-direction on days 2/3/4:
        # SUEDE 50k-74.9k: +114, +59, +161; SUEDE 75k-99.9k: -100, -171, -138;
        # COTTON 75k-99.9k: +307, +58.5, +406.5.
        ("SUEDE", 50000, 74900, +1, 10),
        ("SUEDE", 75000, 99900, -1, 10),
        ("COTTON", 75000, 99900, +1, 10),
        ("POLYESTER", 400000, 449900, -1, 5),
        ("POLYESTER", 750000, 799900, +1, 5),
        # Conservative v2 additions: these 50k windows were omitted from v1,
        # but moved in the same direction on all three public days. Sizes are
        # intentionally below the comparable v1 windows to reduce overfit risk.
        ("COTTON", 250000, 299900, +1, 4),
        ("COTTON", 950000, 999900, +1, 3),
        ("LAMB_WOOL", 150000, 199900, +1, 3),
        ("LAMB_WOOL", 350000, 399900, +1, 2),
        ("SUEDE", 550000, 599900, -1, 2),
    ]

    # Strongest 25k windows only; this keeps timestamp specificity without accepting
    # every tiny historical anomaly.
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

    # Pair spread = mid_a - beta * mid_b.
    # If z is high, a is rich vs b => short a / long beta*b.
    # If z is low, a is cheap vs b => long a / short beta*b.
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
        # Smaller confirmations; included at lower weight because they overlap the main RV signals.
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

    # High spread is usually bearish for Sleep Pods, especially Cotton, Lamb, Nylon, Suede.
    # Polyester spread has weaker predictive value, so it gets only a tiny skew.
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
        # short -> (best_bid, bid_volume, best_ask, ask_volume_abs, mid, spread)
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

        # 1) Intraday schedule.
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

        # 2-4) Statistical mean-reversion signals are disabled during the first 100k timestamps.
        # The IMC run/log uses only 0-99,900, while these anchors were estimated on full public days;
        # using them at the open created bad Cotton/Lamb Wool inventory in the platform log.
        if ts >= 100000:
            # 2) Product-vs-Sleep-basket residual mean reversion.
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

            # 3) Pair-spread mean reversion.
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

            # 4) Own historical price-level mean reversion as a small confirmation.
            # This is intentionally small because historical day mean is not known live.
            for s, mid in mids.items():
                z = (mid - self.MID_MEAN[s]) / max(self.MID_STD[s], 1e-9)
                threshold = 1.85 if s in ("LAMB_WOOL", "SUEDE") else 2.05
                if abs(z) > threshold:
                    contribution = -1.1 * (1 if z > 0 else -1)
                    scores[s] += contribution
                    fair_skew[s] += max(-18.0, min(18.0, -7.0 * z))

        # 5) Book-state execution/fair-value skew.
        for s in mids:
            best_bid, bid_vol, best_ask, ask_vol_abs, mid, spread = books[s]
            if bid_vol + ask_vol_abs > 0:
                micro = (best_ask * bid_vol + best_bid * ask_vol_abs) / (bid_vol + ask_vol_abs)
                # L1/microprice is positive short-horizon alpha, but small.
                fair_skew[s] += max(-3.5, min(3.5, micro - mid))

            if spread >= self.WIDE_SPREAD[s]:
                # High spread generally preceded negative forward movement.
                if s == "POLYESTER":
                    fair_skew[s] -= 2.0
                else:
                    fair_skew[s] -= 5.0

        # Convert scores into target positions and place orders.
        for s, score in scores.items():
            product = self.FULL[s]
            if s not in mids or product not in state.order_depths:
                continue

            pos = state.position.get(product, 0)
            active_schedule = self._has_active_schedule(s, ts)

            # Full cap only during accepted schedule windows.  Relative-value and confirmation
            # signals should not normally consume the entire 10-lot limit by themselves.
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

        conversions = 0
        traderData = ""
        return result, conversions, traderData

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