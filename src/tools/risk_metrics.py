"""Risk metric helpers computed from daily close series (no external APIs)."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def daily_simple_returns(closes: pd.Series) -> pd.Series:
    """Percent change of closes; drops the first NaN."""
    if closes is None or len(closes) < 2:
        return pd.Series(dtype=float)
    return closes.astype(float).pct_change().dropna()


def annualized_std_pct(returns: pd.Series) -> float | None:
    """Annualized standard deviation of daily returns, in percent."""
    if returns is None or len(returns) < 2:
        return None
    std = float(returns.std(ddof=1))
    if math.isnan(std):
        return None
    return round(std * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0, 4)


def max_drawdown_pct(closes: pd.Series) -> float | None:
    """Worst peak-to-trough decline in percent (negative or zero)."""
    if closes is None or len(closes) < 2:
        return None
    series = closes.astype(float)
    rolling_max = series.cummax()
    # Avoid div-by-zero on bad data
    safe_max = rolling_max.replace(0, pd.NA)
    drawdown = series / safe_max - 1.0
    worst = drawdown.min()
    if pd.isna(worst):
        return None
    return round(float(worst) * 100.0, 4)


def beta_vs_benchmark(asset_returns: pd.Series, benchmark_returns: pd.Series) -> float | None:
    """Beta = Cov(r_a, r_b) / Var(r_b) on aligned daily returns."""
    if asset_returns is None or benchmark_returns is None:
        return None
    if len(asset_returns) < 2 or len(benchmark_returns) < 2:
        return None
    aligned = pd.concat(
        [asset_returns.rename("a"), benchmark_returns.rename("b")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 5:
        return None
    var_b = float(aligned["b"].var(ddof=1))
    if var_b == 0 or math.isnan(var_b):
        return None
    cov = float(aligned["a"].cov(aligned["b"]))
    if math.isnan(cov):
        return None
    return round(cov / var_b, 4)


def compute_risk_metrics(
    closes: pd.Series,
    *,
    benchmark_closes: pd.Series | None = None,
    window: str = "1y",
    benchmark: str | None = None,
) -> dict[str, Any]:
    """Compute std, max drawdown, and optional beta from close series."""
    returns = daily_simple_returns(closes)
    as_of = None
    if len(closes) > 0:
        ts = closes.index[-1]
        as_of = str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]

    payload: dict[str, Any] = {
        "window": window,
        "as_of": as_of,
        "observations": int(len(returns)),
        "std_dev_ann_pct": annualized_std_pct(returns),
        "max_drawdown_pct": max_drawdown_pct(closes),
        "beta": None,
        "benchmark": benchmark,
    }

    if benchmark_closes is not None and benchmark:
        bench_returns = daily_simple_returns(benchmark_closes)
        payload["beta"] = beta_vs_benchmark(returns, bench_returns)

    return payload
