"""Telegram signal bot for XAUUSD. It sends ALERTS only - you place the trade yourself
(e.g. in the MT5 phone app). It uses the exact same strategy code as the backtester.

Environment variables:
  TELEGRAM_TOKEN    token from @BotFather
  TELEGRAM_CHAT_ID  your chat id (send /start to the bot and it will tell you)
  TWELVEDATA_KEY    free key from twelvedata.com
  ACCOUNT_BALANCE   optional, used for lot-size suggestions (default 1000)

Run:  python tg_bot.py          (stays running, answers /status, scans each new bar)
      python tg_bot.py --once   (one scan then exit, for cron / GitHub Actions)
"""
import argparse
import math
import os
import time

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
    """Closed bars only, timestamps in UTC (session hours in config.py are then UTC)."""
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
    return df[df.index + pd.Timedelta(minutes=MINS) <= now_utc()]  # drop the forming bar


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
        return  # stale bar, don't alert on old signals
    seen.add(t)
    send(chat, format_signal(row, t))


def status_text() -> str:
    d = add_indicators(fetch_bars(), cfg)
    row, t = d.iloc[-1], d.index[-1]
    trend = "up (fast EMA above slow)" if row["ema_fast"] > row["ema_slow"] else "down (fast EMA below slow)"
    in_session = cfg.session_start <= t.hour < cfg.session_end
    return (f"XAUUSD {row['close']:.2f} at {t:%H:%M} UTC\nTrend: {trend}\nATR: {row['atr']:.2f}\n"
            f"Inside trading session: {'yes' if in_session else 'no'}\n"
            f"Latest bar signal: {['none', 'BUY', 'SELL'][int(row['signal']) if row['signal'] >= 0 else 2]}")


def handle(msg: dict):
    global balance
    text, chat = (msg.get("text") or "").strip(), str(msg["chat"]["id"])
    if text.startswith("/start"):
        send(chat, f"Your chat id is {chat}. Set it as TELEGRAM_CHAT_ID so I send signals to you.\n"
                   f"Commands: /status, /balance 2000")
    elif chat != CHAT:
        return  # ignore everyone else
    elif text.startswith("/status"):
        send(chat, status_text())
    elif text.startswith("/balance"):
        try:
            balance = float(text.split()[1])
            send(chat, f"Balance set to ${balance:,.2f} for lot-size suggestions.")
        except (IndexError, ValueError):
            send(chat, "Usage: /balance 2000")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if not (TOKEN and KEY):
        raise SystemExit("Set TELEGRAM_TOKEN and TWELVEDATA_KEY first.")
    if args.once:
        if not CHAT:
            raise SystemExit("Set TELEGRAM_CHAT_ID first.")
        scan(set(), CHAT)os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and print(tg("sendMessage", chat_id=CHAT, text="Test OK: bot is connected"))
        return

    if CHAT:
        send(CHAT, "XAUUSD signal bot started. Send /status any time.")
    offset, seen, step = None, set(), MINS * 60
    next_scan = 0.0  # scan immediately, then once per new bar (keeps within the free API limit)
    while True:
        try:
            for u in tg("getUpdates", offset=offset, timeout=25).get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    handle(u["message"])
            if CHAT and time.time() >= next_scan:
                next_scan = (time.time() // step + 1) * step + 15
                scan(seen, CHAT)
        except Exception as e:
            print("error:", e)
            time.sleep(10)


if __name__ == "__main__":
    main()
