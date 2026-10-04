"""Taker fee formulas. Both venues use coef * C * P * (1-P), rounded up to the cent."""
import math


def _ceil_cent(x: float) -> float:
    # Guard against float noise like 0.0175000000001 -> 0.02 is fine, but 0.0100000001 -> 0.02 is not.
    return math.ceil(round(x * 100, 6)) / 100


def kalshi_fee(contracts: float, price: float, coef: float = 0.07, multiplier: float = 1.0) -> float:
    if contracts <= 0:
        return 0.0
    return _ceil_cent(coef * multiplier * contracts * price * (1 - price))


def pmus_fee(contracts: float, price: float, coef: float = 0.0695) -> float:
    if contracts <= 0:
        return 0.0
    return _ceil_cent(coef * contracts * price * (1 - price))
