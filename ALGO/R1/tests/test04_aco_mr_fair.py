"""
test04: ACO with short-memory AC(1)=-0.5 signal.
effective_fair = 0.5 * current_mid + 0.5 * anchor. Take/quote around effective_fair,
but clamp to anchor so we never bleed bid-ask on a noisy tick.
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
    ANCHOR = 10000
    TAKE_THRESH = 1
    QUOTE_SIZE = 15

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
        anchor = cls.ANCHOR
        mid = (bb + ba) / 2.0
        # AC(1)=-0.5 → next-tick expectation halfway between mid and anchor
        eff_fair = 0.5 * mid + 0.5 * anchor
        eff_fair_int = round(eff_fair)

        bv1 = od.buy_orders[bb]; av1 = -od.sell_orders[ba]
        imb = (bv1 - av1) / (bv1 + av1) if (bv1 + av1) else 0
        rb = max(0, limit - pos); rs = max(0, limit + pos)

        # take against eff_fair (the forward-looking price), floored/capped by anchor for safety
        take_cap_buy = min(eff_fair_int, anchor)    # never buy above anchor
        take_cap_sell = max(eff_fair_int, anchor)   # never sell below anchor

        for p in sorted(od.sell_orders):
            if p <= take_cap_buy - cls.TAKE_THRESH and rb > 0:
                q = min(rb, -od.sell_orders[p])
                if q > 0: orders.append(Order(product, p, q)); rb -= q
            else: break
        for p in sorted(od.buy_orders, reverse=True):
            if p >= take_cap_sell + cls.TAKE_THRESH and rs > 0:
                q = min(rs, od.buy_orders[p])
                if q > 0: orders.append(Order(product, p, -q)); rs -= q
            else: break

        eff = pos + sum(o.quantity for o in orders)
        # flatten at anchor if sitting there
        if eff < 0 and rb > 0 and anchor in od.sell_orders:
            q = min(rb, -od.sell_orders[anchor], abs(eff))
            if q > 0: orders.append(Order(product, anchor, q)); rb -= q; eff += q
        elif eff > 0 and rs > 0 and anchor in od.buy_orders:
            q = min(rs, od.buy_orders[anchor], abs(eff))
            if q > 0: orders.append(Order(product, anchor, -q)); rs -= q; eff -= q

        # passive quote centered on anchor (quote eff_fair ± 1 but clamp to anchor)
        quote_center = int(round(anchor + imb * 1.5))
        # Skew with MR: if mid > anchor, center bid slightly lower (expect reversion)
        # We quote anchor-1 bid, anchor+1 ask by default
        bp = quote_center - 1
        ap = quote_center + 1
        # If we're positioned long, shift both down; if short, shift up
        skew = round(pos / limit * 2)
        bp -= skew
        ap -= skew

        # never buy above anchor-1 or sell below anchor+1
        bp = min(bp, anchor - 1)
        ap = max(ap, anchor + 1)

        pbq = min(cls.QUOTE_SIZE, rb); psq = min(cls.QUOTE_SIZE, rs)
        if pbq > 0: orders.append(Order(product, bp, pbq))
        if psq > 0: orders.append(Order(product, ap, -psq))
        return orders
