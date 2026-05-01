import math
from typing import Dict, List

from datamodel import OrderDepth, TradingState, Order, Symbol


class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    def run(
        self, state: TradingState
    ) -> tuple[Dict[Symbol, List[Order]], int, str]:
        result: Dict[Symbol, List[Order]] = {}

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
                orders = self.ipr_buyhold(product, order_depth, best_bid, best_ask, position, limit)
            elif product == "ASH_COATED_OSMIUM":
                orders = self.aco_orders(product, best_bid, best_ask, position, limit)

            result[product] = orders

        return result, 0, ""

    @staticmethod
    def ipr_buyhold(
        product: str, od: OrderDepth, best_bid: int, best_ask: int,
        position: int, limit: int,
    ) -> List[Order]:
        """
        Buy-and-hold: accumulate IPR below fair value.
        fair = mid price.  Max buy price = floor(fair) - 3.
        Take any asks at or below that price; passive bid for remaining capacity.
        Never sell.
        """
        orders: List[Order] = []
        buy_cap = limit - position
        if buy_cap <= 0:
            return orders

        fair = (best_bid + best_ask) / 2.0
        max_buy_price = math.floor(fair) - 3

        # Aggressive: take asks at or below max_buy_price
        for ask_price in sorted(od.sell_orders):
            if ask_price > max_buy_price or buy_cap <= 0:
                break
            qty = min(-od.sell_orders[ask_price], buy_cap)
            if qty > 0:
                orders.append(Order(product, ask_price, qty))
                buy_cap -= qty

        # Passive: bid at max_buy_price for remaining capacity
        if buy_cap > 0:
            orders.append(Order(product, max_buy_price, buy_cap))

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
