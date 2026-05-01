from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
import math


class Trader:
    """
    Round 5 Galaxy Sounds strategy.

    Trades only:
      - GALAXY_SOUNDS_DARK_MATTER
      - GALAXY_SOUNDS_BLACK_HOLES
      - GALAXY_SOUNDS_PLANETARY_RINGS
      - GALAXY_SOUNDS_SOLAR_WINDS
      - GALAXY_SOUNDS_SOLAR_FLAMES

    Signal stack:
      1. intraday schedule from robust repeated 25k/50k timestamp buckets
      2. historical product-vs-Galaxy residual mean reversion
      3. selected pair-spread mean reversion
      4. own historical price-level mean reversion as a small confirmation
      5. spread/microprice used as execution/fair-value skew, not as core direction
    """

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

    # beta for: residual = mid_i - beta_i * mean(other four Galaxy mids)
    BETA_TO_EX_SELF_GROUP = {
        "BLACK_HOLES": 0.7460,
        "DARK_MATTER": 0.1692,
        "PLANETARY_RINGS": 0.4586,
        "SOLAR_FLAMES": -0.1995,
        "SOLAR_WINDS": 0.3812,
    }

    # Historical residual anchors from days 2-4.
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

    # Historical price-level anchors from days 2-4.
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

    # Strong 25k timestamp windows. Tuple: (short_product, start, end, direction, target_lots)
    # direction: +1 = long, -1 = short.
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

    # Broader 50k windows. Lower weight than 25k windows, but useful for positioning
    # during intervals where the full 50k block was directionally persistent.
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


    # Coarse 100k overlays accepted only if the full 100k move had the same
    # direction on all three public days. These are intentionally low-size.
    # The SOLAR_FLAMES 0-99.9k overlay was removed after comparison: v2 improved
    # total PnL, but SOLAR_FLAMES alone fell slightly, so deleting that extra
    # rule lowers overfit risk while keeping the stronger broad overlays.
    SCHEDULE_100K: List[Tuple[str, int, int, int, int]] = [
        ("BLACK_HOLES", 100000, 199900, +1, 4),
        ("PLANETARY_RINGS", 400000, 499900, +1, 4),
        ("PLANETARY_RINGS", 500000, 599900, -1, 4),
        ("SOLAR_WINDS", 100000, 199900, +1, 4),
    ]

    # Pair spread = mid_a - beta * mid_b.  If z is high, short the spread;
    # if z is low, long the spread.
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

        # 1) Intraday schedule: strongest signal.
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

        # 2) Product-vs-Galaxy residual mean reversion.
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

        # 3) Pair-spread mean reversion.
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

        # 4) Own historical price-level mean reversion as a small confirmation.
        for s, mid in mids.items():
            z = (mid - self.MID_MEAN[s]) / max(self.MID_STD[s], 1e-9)
            if abs(z) > 2.0:
                contribution = -1.2 * (1 if z > 0 else -1)
                scores[s] += contribution
                fair_skew[s] += max(-20.0, min(20.0, -8.0 * z))

        # 5) Spread and microprice execution skew.  High spread is bearish for most Galaxy products,
        # but it caused too much churn as a target signal, so only shift fair value.
        for s in mids:
            best_bid, bid_vol, best_ask, ask_vol_abs, mid, spread = books[s]
            if bid_vol + ask_vol_abs > 0:
                micro = (best_ask * bid_vol + best_bid * ask_vol_abs) / (bid_vol + ask_vol_abs)
                fair_skew[s] += max(-3.0, min(3.0, micro - mid))
            if s != "BLACK_HOLES" and spread >= self.WIDE_SPREAD[s]:
                fair_skew[s] -= 4.0

        # Convert scores into target positions and place orders.
        for s, score in scores.items():
            product = self.FULL[s]
            if s not in mids or product not in state.order_depths:
                continue
            pos = state.position.get(product, 0)

            # Scheduled targets can occupy the full limit; non-scheduled residual/pair targets are capped lower.
            active_schedule = self._has_active_schedule(s, ts)
            cap = self.LIMIT if active_schedule else 7
            target = int(round(score))
            target = max(-cap, min(cap, target))
            target = max(-self.LIMIT, min(self.LIMIT, target))

            orders = self._orders_to_target(product, s, state.order_depths[product], pos, target, fair_skew[s], aggressive[s])
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
        spread = best_ask - best_bid
        fair = mid + fair_skew
        delta = target - pos

        if delta > 0:
            qty = min(delta, self.LIMIT - pos)
            if qty <= 0:
                return orders
            if aggressive or fair >= best_ask - 1:
                price = best_ask
            else:
                # Improve the bid, but do not cross unless the signal says to.
                price = min(best_ask - 1, max(best_bid + 1, int(math.floor(fair - 1))))
            orders.append(Order(product, int(price), int(qty)))

        elif delta < 0:
            qty = min(-delta, self.LIMIT + pos)
            if qty <= 0:
                return orders
            if aggressive or fair <= best_bid + 1:
                price = best_bid
            else:
                # Improve the ask, but do not cross unless the signal says to.
                price = max(best_bid + 1, min(best_ask - 1, int(math.ceil(fair + 1))))
            orders.append(Order(product, int(price), -int(qty)))

        return orders