import json
import math
from typing import Any, Dict, List

from datamodel import OrderDepth, TradingState, Order, Symbol


class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }
    IPR_EMA_ALPHA = 0.01  # Slow EMA — lags ~10 ticks in steady uptrend

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
                orders = self.ipr_bid_mm(product, order_depth, best_bid, best_ask, position, limit, fair)
            elif product == "ASH_COATED_OSMIUM":
                orders = self.aco_orders(product, best_bid, best_ask, position, limit)

            result[product] = orders

        return result, 0, json.dumps(data)

    @staticmethod
    def ipr_bid_mm(
        product: str, od: OrderDepth, best_bid: int, best_ask: int,
        position: int, limit: int, fair: float,
    ) -> List[Order]:
        """
        Penny-jump bid only.  Never sell.
        Enhancement: if best_bid < fair (pullback), also take best ask
        aggressively to accumulate faster.
        """
        orders: List[Order] = []
        buy_cap = limit - position
        if buy_cap <= 0:
            return orders

        # Enhancement: pullback detected → take best ask
        if best_bid < fair and buy_cap > 0:
            ask_qty = min(-od.sell_orders[best_ask], buy_cap)
            if ask_qty > 0:
                orders.append(Order(product, best_ask, ask_qty))
                buy_cap -= ask_qty

        # Core: penny-jump the bid
        if buy_cap > 0:
            orders.append(Order(product, best_bid + 1, buy_cap))

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
