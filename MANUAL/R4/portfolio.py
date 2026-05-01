"""Portfolio container that aggregates positions and computes PnL."""

from __future__ import annotations

import numpy as np

from products import Product


CONTRACT_SIZE = 3000


class Portfolio:
    """Represents a basket of long/short positions across products.

    Positive volume = long (bought at ask). Negative volume = short (sold at bid).
    Each position is held to that product's expiry, then marked to its realized
    payoff per simulation.
    """

    def __init__(self, contract_size: int = CONTRACT_SIZE):
        self.positions: dict[str, tuple[Product, int]] = {}
        self.contract_size = contract_size

    def add(self, product: Product, volume: int) -> "Portfolio":
        if volume == 0:
            return self
        if abs(volume) > product.max_volume:
            raise ValueError(
                f"{product.name}: |volume|={abs(volume)} exceeds max {product.max_volume}"
            )
        if product.name in self.positions:
            existing_p, existing_v = self.positions[product.name]
            new_v = existing_v + volume
            if abs(new_v) > product.max_volume:
                raise ValueError(
                    f"{product.name}: combined |volume|={abs(new_v)} exceeds max {product.max_volume}"
                )
            self.positions[product.name] = (existing_p, new_v)
        else:
            self.positions[product.name] = (product, volume)
        return self

    def buy(self, product: Product, volume: int) -> "Portfolio":
        return self.add(product, abs(volume))

    def sell(self, product: Product, volume: int) -> "Portfolio":
        return self.add(product, -abs(volume))

    @property
    def n_assets_used(self) -> int:
        return sum(1 for _, v in self.positions.values() if v != 0)

    def cost(self) -> float:
        """Total upfront cost (positive = paid out at t=0).

        For a long position you pay ask. For a short you receive bid.
        """
        total = 0.0
        for product, vol in self.positions.values():
            if vol > 0:
                total += vol * product.ask
            elif vol < 0:
                total += vol * product.bid  # negative => received cash
        return total

    def realized_value(self, paths: np.ndarray) -> np.ndarray:
        n_sims = paths.shape[0]
        total = np.zeros(n_sims)
        for product, vol in self.positions.values():
            if vol == 0:
                continue
            total += vol * product.payoff(paths)
        return total

    def pnl(self, paths: np.ndarray) -> np.ndarray:
        """Per-simulation PnL in score-units (already × contract_size)."""
        return (self.realized_value(paths) - self.cost()) * self.contract_size

    def stats(self, paths: np.ndarray) -> dict:
        pnl = self.pnl(paths)
        std = float(np.std(pnl))
        return {
            'mean': float(np.mean(pnl)),
            'std': std,
            'min': float(np.min(pnl)),
            'max': float(np.max(pnl)),
            'p5': float(np.percentile(pnl, 5)),
            'p25': float(np.percentile(pnl, 25)),
            'median': float(np.percentile(pnl, 50)),
            'p75': float(np.percentile(pnl, 75)),
            'p95': float(np.percentile(pnl, 95)),
            'win_rate': float(np.mean(pnl > 0)),
            'sharpe': float(np.mean(pnl) / std) if std > 0 else float('inf'),
            'cost_at_t0': self.cost() * self.contract_size,
            'n_assets_used': self.n_assets_used,
        }

    def describe(self) -> str:
        rows = []
        rows.append(f"{'Product':<12} {'Side':<5} {'Vol':>6} {'Price':>9} {'Notional':>14}")
        for name, (product, vol) in self.positions.items():
            if vol == 0:
                continue
            side = 'BUY' if vol > 0 else 'SELL'
            price = product.ask if vol > 0 else product.bid
            notional = abs(vol) * price * self.contract_size
            rows.append(f"{name:<12} {side:<5} {abs(vol):>6} {price:>9.4f} {notional:>14,.0f}")
        rows.append(f"\nupfront cost: {self.cost() * self.contract_size:,.0f}")
        rows.append(f"assets used:  {self.n_assets_used}/12")
        return '\n'.join(rows)
