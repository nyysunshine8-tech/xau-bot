import numpy as np
import pandas as pd

from config import Config


def add_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Adds atr and signal (+1 long, -1 short, 0 none), evaluated at each bar's close.
    The same function is used by the backtester and the live bot, so they cannot diverge."""
    d = df.copy()
    prev_close = d["close"].shift(1)
    tr = pd.concat(
        [d["high"] - d["low"], (d["high"] - prev_close).abs(), (d["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / cfg.atr_period, adjust=False).mean()
    d["ema_fast"] = d["close"].ewm(span=cfg.ema_fast, adjust=False).mean()
    d["ema_slow"] = d["close"].ewm(span=cfg.ema_slow, adjust=False).mean()
    d["hh"] = d["high"].rolling(cfg.donchian).max().shift(1)
    d["ll"] = d["low"].rolling(cfg.donchian).min().shift(1)

    hour = d.index.hour
    in_session = (hour >= cfg.session_start) & (hour < cfg.session_end)

    long_ = (d["close"] > d["hh"]) & (d["ema_fast"] > d["ema_slow"]) & in_session
    short_ = (d["close"] < d["ll"]) & (d["ema_fast"] < d["ema_slow"]) & in_session
    d["signal"] = np.where(long_, 1, np.where(short_, -1, 0))
    return d
  
