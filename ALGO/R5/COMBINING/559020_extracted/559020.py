from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Optional, Tuple
import json


class Trader:
    """
    FINAL SAFE BASELINE - Round 5 UV + Panels selected-legs strategy.

    Intended for the full 1,000,000 timestamp run.

    Panels:
      Signal basket = PANEL_2X2 + PANEL_2X4 + PANEL_4X4
      Traded legs   = PANEL_2X4 + PANEL_4X4 only
      window=500, entry_edge=200, exit_edge=200, trade_size=1

    UV:
      Signal basket = UV_VISOR_AMBER + UV_VISOR_ORANGE + UV_VISOR_MAGENTA
      Traded legs   = UV_VISOR_AMBER + UV_VISOR_ORANGE + UV_VISOR_MAGENTA
      window=500, entry_edge=400, exit_edge=200, trade_size=1

    Important:
      PANEL_2X2 is used only as signal information. It is NOT traded.
      This version does NOT use adaptive warmup and does NOT lower UV entry.
    """

    POSITION_LIMIT = 10

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
        # Keep only the rolling windows to avoid oversized traderData.
        for strat in self.STRATEGIES:
            name = strat["name"]
            window = int(strat["window"])
            data[name] = data.get(name, [])[-window:]
        return json.dumps(data, separators=(",", ":"))

    def _best_bid_ask(self, order_depth: OrderDepth) -> Optional[Tuple[int, int, int, int, float]]:
        """
        Returns best_bid, bid_volume, best_ask, ask_volume, mid.
        In Prosperity, buy volumes are positive and sell volumes are negative.
        """
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
        """
        Add synchronized orders on trade_symbols only.
        side='buy' buys every traded leg at best ask.
        side='sell' sells every traded leg at best bid.
        """
        qty = int(trade_size)

        if side == "buy":
            for symbol in trade_symbols:
                pos = local_pos.get(symbol, 0)
                if exit_only:
                    pos_room = max(0, -pos)  # close shorts only
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
                    pos_room = max(0, pos)  # close longs only
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

        # Need all signal products available. Since trade_symbols are a subset
        # of signal_symbols here, this also provides prices for traded legs.
        snap = self._snapshot(state, signal_symbols)
        if snap is None:
            return

        basket_mid = sum(snap[s]["mid"] for s in signal_symbols)
        basket_ask = sum(snap[s]["ask"] for s in signal_symbols)
        basket_bid = sum(snap[s]["bid"] for s in signal_symbols)

        # Use previous history only. Append current tick after decision.
        # Normal version: no trading before the full 500-observation window.
        if len(history) >= window:
            fair = sum(history[-window:]) / window
            positions = [local_pos.get(s, 0) for s in trade_symbols]
            all_long = all(p > 0 for p in positions)
            all_short = all(p < 0 for p in positions)

            # Basket cheap: buy selected traded legs.
            if basket_ask < fair - entry_edge:
                self._add_orders(result, local_pos, trade_symbols, snap, "buy", trade_size, exit_only=False)

            # Basket expensive: sell selected traded legs.
            elif basket_bid > fair + entry_edge:
                self._add_orders(result, local_pos, trade_symbols, snap, "sell", trade_size, exit_only=False)

            # Exit long only after signal basket overshoots expensive.
            elif all_long and basket_bid > fair + exit_edge:
                self._add_orders(result, local_pos, trade_symbols, snap, "sell", trade_size, exit_only=True)

            # Exit short only after signal basket overshoots cheap.
            elif all_short and basket_ask < fair - exit_edge:
                self._add_orders(result, local_pos, trade_symbols, snap, "buy", trade_size, exit_only=True)

        history.append(basket_mid)
        if len(history) > window:
            del history[:-window]

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        data = self._load_data(state.traderData)

        # Local copy so if multiple strategies traded same symbol, we would not
        # accidentally exceed limits. Here the strategies are disjoint, but this is safer.
        local_pos: Dict[str, int] = dict(state.position) if state.position is not None else {}

        for strat in self.STRATEGIES:
            name = strat["name"]
            history = data.setdefault(name, [])
            self._trade_strategy(state, result, local_pos, history, strat)

        trader_data = self._dump_data(data)
        conversions = 0
        return result, conversions, trader_data