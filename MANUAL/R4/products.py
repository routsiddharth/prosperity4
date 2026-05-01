"""Product definitions for R4 manual round.

Each product has bid/ask quotes, max volume, and a payoff(paths) function
that returns realized payoff at expiry for each simulated path.

Path index convention: paths[:, 0] is S0 at t=0; paths[:, k] is S after k steps.
"""

from __future__ import annotations

import numpy as np

from simulator import WEEKS_2_STEPS, WEEKS_3_STEPS


class Product:
    is_underlying = False

    def __init__(self, name: str, bid: float, ask: float, max_volume: int,
                 expiry_steps: int):
        self.name = name
        self.bid = bid
        self.ask = ask
        self.max_volume = max_volume
        self.expiry_steps = expiry_steps

    def payoff(self, paths: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def fair_value(self, paths: np.ndarray) -> float:
        return float(np.mean(self.payoff(paths)))

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name})"


class Underlying(Product):
    """Holding the spot — payoff at 'expiry' is just the spot price at that time.
    PnL per long unit = S_T - ask. PnL per short unit = bid - S_T.
    """
    is_underlying = True

    def payoff(self, paths: np.ndarray) -> np.ndarray:
        return paths[:, self.expiry_steps]


class VanillaCall(Product):
    def __init__(self, name, bid, ask, max_volume, expiry_steps, strike):
        super().__init__(name, bid, ask, max_volume, expiry_steps)
        self.strike = strike

    def payoff(self, paths: np.ndarray) -> np.ndarray:
        return np.maximum(paths[:, self.expiry_steps] - self.strike, 0.0)


class VanillaPut(Product):
    def __init__(self, name, bid, ask, max_volume, expiry_steps, strike):
        super().__init__(name, bid, ask, max_volume, expiry_steps)
        self.strike = strike

    def payoff(self, paths: np.ndarray) -> np.ndarray:
        return np.maximum(self.strike - paths[:, self.expiry_steps], 0.0)


class ChooserOption(Product):
    """At choice_steps, holder picks call or put — whichever is ITM.
    Then payoff is the chosen option at expiry_steps.
    """
    def __init__(self, name, bid, ask, max_volume, expiry_steps, strike, choice_steps):
        super().__init__(name, bid, ask, max_volume, expiry_steps)
        self.strike = strike
        self.choice_steps = choice_steps

    def payoff(self, paths: np.ndarray) -> np.ndarray:
        S_choice = paths[:, self.choice_steps]
        S_expiry = paths[:, self.expiry_steps]
        call_payoff = np.maximum(S_expiry - self.strike, 0.0)
        put_payoff = np.maximum(self.strike - S_expiry, 0.0)
        # When ITM-choice rule is used, holder picks call iff S_choice > K
        # (this matches the optimal max(C, P) under put-call parity at r=0).
        return np.where(S_choice > self.strike, call_payoff, put_payoff)


class BinaryPut(Product):
    """Pays `payout` if S_T < strike at expiry, else 0."""
    def __init__(self, name, bid, ask, max_volume, expiry_steps, strike, payout):
        super().__init__(name, bid, ask, max_volume, expiry_steps)
        self.strike = strike
        self.payout = payout

    def payoff(self, paths: np.ndarray) -> np.ndarray:
        return np.where(paths[:, self.expiry_steps] < self.strike,
                        self.payout, 0.0)


class KnockOutPut(Product):
    """Down-and-out put. If any pre-expiry observation is below `barrier`,
    the option dies (pays 0). Otherwise pays max(strike - S_T, 0).
    """
    def __init__(self, name, bid, ask, max_volume, expiry_steps, strike, barrier):
        super().__init__(name, bid, ask, max_volume, expiry_steps)
        self.strike = strike
        self.barrier = barrier

    def payoff(self, paths: np.ndarray) -> np.ndarray:
        # Observations 1 .. expiry_steps-1 (exclude S0 since it's 50 > 45,
        # and exclude expiry observation per "before expiry" wording).
        pre_expiry = paths[:, 1:self.expiry_steps]
        knocked = np.any(pre_expiry < self.barrier, axis=1)
        put_payoff = np.maximum(self.strike - paths[:, self.expiry_steps], 0.0)
        return np.where(knocked, 0.0, put_payoff)


def build_universe(binary_payout: float = 10.0,
                   ko_barrier: float = 45.0) -> dict[str, Product]:
    """Returns the full set of R4 products keyed by symbol name.

    binary_payout: payout amount for AC_40_BP if it triggers (NOT specified in
        the screenshot — defaults to 10 since that aligns with the ~5 mid).
    ko_barrier: knock-out barrier for AC_45_KO (defaults to strike = 45).
    """
    P = {}
    P['AC']        = Underlying ('AC',        49.975, 50.025, 200, WEEKS_3_STEPS)
    P['AC_50_P']   = VanillaPut ('AC_50_P',   12.00,  12.05,  50,  WEEKS_3_STEPS, 50)
    P['AC_50_C']   = VanillaCall('AC_50_C',   12.00,  12.05,  50,  WEEKS_3_STEPS, 50)
    P['AC_35_P']   = VanillaPut ('AC_35_P',   4.33,   4.35,   50,  WEEKS_3_STEPS, 35)
    P['AC_40_P']   = VanillaPut ('AC_40_P',   6.50,   6.55,   50,  WEEKS_3_STEPS, 40)
    P['AC_45_P']   = VanillaPut ('AC_45_P',   9.05,   9.10,   50,  WEEKS_3_STEPS, 45)
    P['AC_60_C']   = VanillaCall('AC_60_C',   8.80,   8.85,   50,  WEEKS_3_STEPS, 60)
    P['AC_50_P_2'] = VanillaPut ('AC_50_P_2', 9.70,   9.75,   50,  WEEKS_2_STEPS, 50)
    P['AC_50_C_2'] = VanillaCall('AC_50_C_2', 9.70,   9.75,   50,  WEEKS_2_STEPS, 50)
    P['AC_50_CO']  = ChooserOption('AC_50_CO', 22.20, 22.30, 50,
                                   expiry_steps=WEEKS_3_STEPS, strike=50,
                                   choice_steps=WEEKS_2_STEPS)
    P['AC_40_BP']  = BinaryPut  ('AC_40_BP',  5.00,   5.10,   50,  WEEKS_3_STEPS,
                                 strike=40, payout=binary_payout)
    P['AC_45_KO']  = KnockOutPut('AC_45_KO',  0.15,   0.175,  500, WEEKS_3_STEPS,
                                 strike=45, barrier=ko_barrier)
    return P
