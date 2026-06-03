"""Technical indicators and rule-based confirmation logic."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pandas_ta as ta

from src.config import DEFAULT_RSI_OVERBOUGHT, DEFAULT_RSI_OVERSOLD


@dataclass(frozen=True)
class IndicatorSignals:
    bullish: tuple[str, ...]
    bearish: tuple[str, ...]
    values: dict[str, float | None]


def compute_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Append RSI, MACD, EMA, and Bollinger columns to an OHLCV frame."""
    enriched = frame.copy()
    close = enriched["close"]

    enriched["rsi_14"] = ta.rsi(close, length=14)
    macd = ta.macd(close, fast=12, slow=26, signal=9)
    if macd is not None:
        enriched = enriched.join(macd)

    enriched["ema_20"] = ta.ema(close, length=20)
    enriched["ema_50"] = ta.ema(close, length=50)

    bbands = ta.bbands(close, length=20, std=2)
    if bbands is not None:
        enriched = enriched.join(bbands)

    return enriched


def _column(frame: pd.DataFrame, *candidates: str) -> str | None:
    for name in candidates:
        if name in frame.columns:
            return name
    return None


def evaluate_indicator_signals(
    frame: pd.DataFrame,
    *,
    rsi_oversold: float = DEFAULT_RSI_OVERSOLD,
    rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT,
) -> IndicatorSignals:
    """Evaluate bullish/bearish confirmations on the latest daily candles."""
    if len(frame) < 2:
        return IndicatorSignals(bullish=(), bearish=(), values={})

    latest = frame.iloc[-1]
    previous = frame.iloc[-2]
    bullish: list[str] = []
    bearish: list[str] = []
    values: dict[str, float | None] = {}

    rsi = latest.get("rsi_14")
    if pd.notna(rsi):
        rsi_value = float(rsi)
        values["rsi_14"] = rsi_value
        if rsi_value < rsi_oversold:
            bullish.append(f"RSI oversold ({rsi_value:.0f})")
        elif rsi_value > rsi_overbought:
            bearish.append(f"RSI overbought ({rsi_value:.0f})")
    else:
        values["rsi_14"] = None

    macd_col = _column(frame, "MACD_12_26_9")
    signal_col = _column(frame, "MACDs_12_26_9")
    if macd_col and signal_col:
        prev_macd = previous[macd_col]
        prev_signal = previous[signal_col]
        curr_macd = latest[macd_col]
        curr_signal = latest[signal_col]
        if pd.notna(prev_macd) and pd.notna(prev_signal) and pd.notna(curr_macd) and pd.notna(curr_signal):
            values["macd"] = float(curr_macd)
            values["macd_signal"] = float(curr_signal)
            if prev_macd <= prev_signal and curr_macd > curr_signal:
                bullish.append("MACD bullish cross")
            elif prev_macd >= prev_signal and curr_macd < curr_signal:
                bearish.append("MACD bearish cross")

    ema_20 = latest.get("ema_20")
    ema_50 = latest.get("ema_50")
    close = latest.get("close")
    if pd.notna(ema_20) and pd.notna(ema_50) and pd.notna(close):
        values["ema_20"] = float(ema_20)
        values["ema_50"] = float(ema_50)
        values["close"] = float(close)
        if close > ema_20 > ema_50:
            bullish.append("EMA uptrend")
        elif close < ema_20 < ema_50:
            bearish.append("EMA downtrend")

    lower_band_col = _column(frame, "BBL_20_2.0_2.0", "BBL_20_2.0")
    if lower_band_col and pd.notna(close) and pd.notna(latest[lower_band_col]):
        lower_band = float(latest[lower_band_col])
        values["bb_lower"] = lower_band
        if close <= lower_band:
            bullish.append("Price at lower Bollinger band")

    return IndicatorSignals(
        bullish=tuple(bullish),
        bearish=tuple(bearish),
        values=values,
    )
