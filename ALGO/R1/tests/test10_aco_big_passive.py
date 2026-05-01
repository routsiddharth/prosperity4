"""
test10: Fixed-fair ACO baseline with passive size bumped to 40 and
a second tier at fair±2 with size 20 (smaller than tight tier).
Goal: more passive-fill volume without inventory blowup.
"""
import json
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self): self.logs = ""; self.max_log_length = 3750
    def print(self, *o, sep=" ", end="\n"): self.logs += sep.join(map(str, o)) + end
    def flush(self, state, orders, conversions, trader_data):
        base = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        mil = (self.max_log_length - base) // 3
        print(self.to_json([self.compress_state(state, self.truncate(state.traderData, mil)),
                            self.compress_orders(orders), conversions,
                            self.truncate(trader_data, mil), self.truncate(self.logs, mil)]))
        self.logs = ""
    def compress_state(self, s, td):
        return [s.timestamp, td, [[l.symbol, l.product, l.denomination] for l in s.listings.values()],
                {k: [v.buy_orders, v.sell_orders] for k, v in s.order_depths.items()},
                [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for a in s.own_trades.values() for t in a],
                [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for a in s.market_trades.values() for t in a],
                s.position,
                [s.observations.plainValueObservations,
                 {p: [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex]
                  for p, o in s.observations.conversionObservations.items()}]]
    def compress_orders(self, orders):
        return [[o.symbol, o.price, o.quantity] for a in orders.values() for o in a]
    def to_json(self, v): return json.dumps(v, cls=ProsperityEncoder, separators=(",", ":"))
    def truncate(self, v, m):
        lo, hi = 0, min(len(v), m); out = ""
        while lo <= hi:
            mid = (lo + hi) // 2; c = v[:mid]
            if len(c) < len(v): c += "..."
            if len(json.dumps(c)) <= m: out = c; lo = mid + 1
            else: hi = mid - 1
        return out


logger = Logger()


class Trader:
    POSITION_LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
    ACO_FAIR = 10000
    TAKE_THRESH = 1
    TIGHT_SIZE = 40
    T2_SIZE = 20    # size at fair±2

    def run(self, state: TradingState):
        result = {}
        for product, od in state.order_depths.items():
            orders = []
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 80)
            if not od.buy_orders or not od.sell_orders:
                result[product] = orders
                continue
            bb, ba = max(od.buy_orders), min(od.sell_orders)
            if product == "INTARIAN_PEPPER_ROOT":
                q = limit - pos
                if q > 0: orders.append(Order(product, ba, q))
            elif product == "ASH_COATED_OSMIUM":
                orders = self.aco(product, od, bb, ba, pos, limit)
            result[product] = orders
        logger.flush(state, result, 0, "")
        return result, 0, ""

    @classmethod
    def aco(cls, product, od, bb, ba, pos, limit):
        orders = []
        fair = cls.ACO_FAIR
        bv1 = od.buy_orders[bb]; av1 = -od.sell_orders[ba]
        imb = (bv1 - av1) / (bv1 + av1) if (bv1 + av1) else 0
        rb = max(0, limit - pos); rs = max(0, limit + pos)

        for p in sorted(od.sell_orders):
            if p <= fair - cls.TAKE_THRESH and rb > 0:
                q = min(rb, -od.sell_orders[p])
                if q > 0: orders.append(Order(product, p, q)); rb -= q
            else: break
        for p in sorted(od.buy_orders, reverse=True):
            if p >= fair + cls.TAKE_THRESH and rs > 0:
                q = min(rs, od.buy_orders[p])
                if q > 0: orders.append(Order(product, p, -q)); rs -= q
            else: break

        eff = pos + sum(o.quantity for o in orders)
        if eff < 0 and rb > 0 and fair in od.sell_orders:
            q = min(rb, -od.sell_orders[fair], abs(eff))
            if q > 0: orders.append(Order(product, fair, q)); rb -= q; eff += q
        elif eff > 0 and rs > 0 and fair in od.buy_orders:
            q = min(rs, od.buy_orders[fair], abs(eff))
            if q > 0: orders.append(Order(product, fair, -q)); rs -= q; eff -= q

        # Tight passive quote at fair±1
        t1b = min(cls.TIGHT_SIZE, rb); t1s = min(cls.TIGHT_SIZE, rs)
        if t1b > 0: orders.append(Order(product, fair - 1, t1b)); rb -= t1b
        if t1s > 0: orders.append(Order(product, fair + 1, -t1s)); rs -= t1s

        # Second tier at fair±2 for remaining capacity
        t2b = min(cls.T2_SIZE, rb); t2s = min(cls.T2_SIZE, rs)
        if t2b > 0: orders.append(Order(product, fair - 2, t2b))
        if t2s > 0: orders.append(Order(product, fair + 2, -t2s))
        return orders
