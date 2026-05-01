"""GBM path simulator for AETHER_CRYSTAL (R4 manual)."""

import numpy as np


TRADING_DAYS_PER_YEAR = 252
STEPS_PER_DAY = 4
STEPS_PER_YEAR = TRADING_DAYS_PER_YEAR * STEPS_PER_DAY


def weeks_to_years(weeks: float) -> float:
    return (weeks * 5) / TRADING_DAYS_PER_YEAR


def steps_for_weeks(weeks: float) -> int:
    return int(round(weeks * 5 * STEPS_PER_DAY))


WEEKS_2_STEPS = steps_for_weeks(2)   # 40
WEEKS_3_STEPS = steps_for_weeks(3)   # 60


class Simulator:
    def __init__(self, S0: float = 50.0, sigma: float = 2.51,
                 days_per_year: int = TRADING_DAYS_PER_YEAR,
                 steps_per_day: int = STEPS_PER_DAY):
        self.S0 = S0
        self.sigma = sigma
        self.dt = 1.0 / (days_per_year * steps_per_day)

    def simulate(self, n_sims: int, n_steps: int = WEEKS_3_STEPS, seed=None) -> np.ndarray:
        """Returns array of shape (n_sims, n_steps + 1) with paths starting at S0."""
        rng = np.random.default_rng(seed)
        Z = rng.standard_normal(size=(n_sims, n_steps))
        increments = -0.5 * self.sigma ** 2 * self.dt + self.sigma * np.sqrt(self.dt) * Z
        log_S = np.cumsum(increments, axis=1) + np.log(self.S0)
        S = np.exp(log_S)
        S0_col = np.full((n_sims, 1), self.S0)
        return np.concatenate([S0_col, S], axis=1)
