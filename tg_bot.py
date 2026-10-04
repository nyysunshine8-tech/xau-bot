import math
import os

import pandas as pd
import requests

from config import Config
from strategy import add_indicators

cfg = Config()
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
KEY = os.environ.get("TWELVEDATA_KEY", "")
balance = float(os.environ.get("ACCOUNT_BALANCE", "1000"))

TF = {"M5": (5, "5min"), "M15": (15, "15min"), "M30": (30, "30min"), "H1": (60, "1h")}
MINS, TD_INTERVAL = TF[cfg.timeframe]


def now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_localize(None)


def tg(method: str, **params) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=params, timeout=40)
    return r.json()


def send(chat: str, text: str):
    tg("sendMessage", chat_id=chat, text=text)


def fetch_bars(n: int = 600) -> pd.DataFrame:
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params=dict(symbol="XAU/USD", interval=TD_INTERVAL, outputsize=n,
                    timezone="UTC", order="ASC", apikey=KEY),
        timeout=20,
    ).json()
    if r.get("status") == "error" or "values" not in r:
        raise RuntimeError(r.get("message", "bad response from data provider"))
    df = pd.DataFrame(r["values"])
    df.index = pd.to_datetime(df["datetime"])
    df = df[["open", "high", "low", "close"]].astype(float).sort_index()
    return df[df.index + pd.Timedelta(minutes=MINS) <= now_utc()]


def size_for(stop_dist: float):
    risk_dist = stop_dist + cfg.spread + cfg.slippage
    raw = balance * cfg.risk_per_trade / (risk_dist * cfg.contract_size)
    lots = max(math.floor(raw / cfg.lot_step) * cfg.lot_step, cfg.min_lot)
    risk_pct = lots * risk_dist * cfg.contract_size / balance * 100
    return round(lots, 2), risk_pct


def format_signal(row, t) -> str:
    direction = int(row["signal"])
    price, atr = float(row["close"]), float(row["atr"])
    stop_dist, tp_dist = cfg.sl_atr * atr, cfg.tp_atr * atr
    sl = price - direction * stop_dist
    tp = price + direction * tp_dist
    lots, risk_pct = size_for(stop_dist)
    msg = (
        f"XAUUSD {'BUY' if direction == 1 else 'SELL'} signal ({cfg.timeframe}, bar closed "
        f"{t + pd.Timedelta(minutes=MINS):%Y-%m-%d %H:%M} UTC)\n"
        f"Entry: about {price:.2f}\n"
        f"Stop loss: {sl:.2f} ({stop_dist:.2f} away)\n"
        f"Take profit: {tp:.2f} ({tp_dist:.2f} away)\n"
        f"Suggested size: {lots} lots, risking about {risk_pct:.1f}% of ${balance:,.0f}\n\n"
        f"Set the SL and TP as the same distances from your actual fill. "
        f"Skip it if price has already moved more than ~{0.3 * atr:.2f} from entry."
    )
    if risk_pct > 2:
        msg += (f"\n\nWARNING: the broker's minimum lot already risks {risk_pct:.1f}% "
                f"of your balance. This signal is too large for your account size.")
    return msg


def scan(seen: set, chat: str):
    df = fetch_bars()
    d = add_indicators(df, cfg)
    row, t = d.iloc[-1], d.index[-1]
    if row["signal"] == 0 or t in seen:
        return
    if now_utc() - (t + pd.Timedelta(minutes=MINS)) > pd.Timedelta(minutes=MINS * 1.5):
        return
    seen.add(t)
    send(chat, format_signal(row, t))


def test_message():
    r = tg("sendMessage", chat_id=CHAT, text="Test OK: bot is connected")
    print("telegram reply:", r)
    if not r.get("ok"):
        raise SystemExit(f"Telegram refused the message: {r.get('description')}")


def main():
    if not (TOKEN and KEY and CHAT):
        raise SystemExit("Set TELEGRAM_TOKEN, TELEGRAM_CHAT_ID and TWELVEDATA_KEY first.")
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        test_message()
    scan(set(), CHAT)


if __name__ == "__main__":
    main()
  
