from dataclasses import dataclass


@dataclass
class Config:
    # --- instrument ---
    symbol: str = "XAUUSD"
    timeframe: str = "M15"          # M5, M15, M30, H1
    contract_size: float = 100.0    # oz per 1.00 lot (check your broker)
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 5.0

    # --- strategy (trend filter + Donchian breakout, ATR stops) ---
    atr_period: int = 14
    donchian: int = 48              # breakout lookback in bars
    ema_fast: int = 50
    ema_slow: int = 200
    sl_atr: float = 1.5             # stop distance in ATRs
    tp_atr: float = 3.0             # target distance in ATRs
    session_start: int = 7          # hour of broker-server time (inclusive)
    session_end: int = 20           # hour of broker-server time (exclusive)
    max_bars: int = 0               # time stop in bars, 0 = off

    # --- costs (USD price units per oz) ---
    spread: float = 0.30            # typical XAUUSD spread; use your broker's real number
    slippage: float = 0.05
    commission_per_lot: float = 0.0  # round-turn, account currency

    # --- risk ---
    initial_equity: float = 10_000.0
    risk_per_trade: float = 0.005   # 0.5% of equity per trade
    daily_loss_limit: float = 0.02  # stop opening trades for the day at -2%
    max_dd_kill: float = 0.15       # stop trading entirely at -15% from peak

    # --- live ---
    magic: int = 240101
    deviation: int = 30             # max slippage in points on market orders
  
