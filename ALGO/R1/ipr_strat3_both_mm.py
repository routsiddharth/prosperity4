import json
import math
from typing import Any, Dict, List

from datamodel import OrderDepth, TradingState, Order, Symbol


class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }
    IPR_EMA_ALPHA = 0.01   # Slow EMA for fair value
    IPR_MAX_SELL = 20       # Cap sell per iteration to stay net long

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}
        data = self._load(state.traderData)

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 80)

            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(order_depth.buy_orders)
            best_ask = min(order_depth.sell_orders)

            if product == "INTARIAN_PEPPER_ROOT":
                mid = (best_bid + best_ask) / 2.0
                pd = data.setdefault("IPR", {"ema": None})
                if pd["ema"] is None:
                    pd["ema"] = mid
                else:
                    pd["ema"] = self.IPR_EMA_ALPHA * mid + (1 - self.IPR_EMA_ALPHA) * pd["ema"]
                fair = pd["ema"]
                orders = self.ipr_both_mm(
                    product, order_depth, best_bid, best_ask, mid, position, limit, fair,
                )
            elif product == "ASH_COATED_OSMIUM":
                orders = self.aco_orders(product, best_bid, best_ask, position, limit)

            result[product] = orders

        return result, 0, json.dumps(data)

    def ipr_both_mm(
        self, product: str, od: OrderDepth, best_bid: int, best_ask: int,
        mid: float, position: int, limit: int, fair: float,
    ) -> List[Order]:
        """
        Penny-jump both bid and ask.  Maintain net-long position.
        - If short and price < fair: urgently take asks to cover.
        - If bid < fair (pullback): take best ask aggressively.
        - Sell side capped to current position (never go short intentionally).
        """
        orders: List[Order] = []
        buy_cap = limit - position

        # ── CASE 1: SHORT → urgently buy to cover, no sells ──
        if position < 0:
            if mid < fair:
                # Below fair + short: take asks to cover
                for ask_price in sorted(od.sell_orders):
                    if buy_cap <= 0:
                        break
                    qty = min(-od.sell_orders[ask_price], buy_cap)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        buy_cap -= qty
            # Penny-jump bid for remaining capacity
            if buy_cap > 0:
                orders.append(Order(product, best_bid + 1, buy_cap))
            return orders  # no sells when short

        # ── CASE 2: FLAT or LONG → market-make both sides ──

        # Enhancement: if bid < fair (pullback), take best ask
        if best_bid < fair and buy_cap > 0:
            ask_qty = min(-od.sell_orders[best_ask], buy_cap)
            if ask_qty > 0:
                orders.append(Order(product, best_ask, ask_qty))
                buy_cap -= ask_qty

        # Buy side: penny-jump the bid
        if buy_cap > 0:
            orders.append(Order(product, best_bid + 1, buy_cap))

        # Sell side: penny-jump the ask (capped to keep net long)
        sell_cap = min(position, self.IPR_MAX_SELL)
        if sell_cap > 0:
            orders.append(Order(product, best_ask - 1, -sell_cap))

        return orders

    @staticmethod
    def aco_orders(
        product: str, best_bid: int, best_ask: int, position: int, limit: int,
    ) -> List[Order]:
        """ACO: inventory-aware market making (unchanged across strategies)."""
        orders: List[Order] = []
        buy_qty = limit - position
        sell_qty = limit + position

        if position >= 20:
            if sell_qty > 0:
                orders.append(Order(product, best_ask - 1, -sell_qty))
        elif position <= -20:
            if buy_qty > 0:
                orders.append(Order(product, best_bid + 1, buy_qty))
        else:
            if buy_qty > 0:
                orders.append(Order(product, best_bid + 1, buy_qty))
            if sell_qty > 0:
                orders.append(Order(product, best_ask - 1, -sell_qty))

        return orders

    @staticmethod
    def _load(td: str) -> Dict[str, Any]:
        if not td:
            return {}
        try:
            d = json.loads(td)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
