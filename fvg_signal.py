"""XAUUSD FVG signal bot (port of the Pine indicator) -> Telegram.
Runs once per call (for GitHub Actions cron). Needs env vars:
TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TWELVEDATA_API_KEY
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

# ---------------- SETTINGS (same as Pine defaults) ----------------
SYMBOL = "XAU/USD"
FVG_PER_SESSION = 1
TP_DOLLARS = 20.0
SHOW_ASIAN, SHOW_LONDON = True, True
ASIAN = (0, 6)    # UTC hours [start, end)
LONDON = (7, 10)
DELTA_LEN, MOMENTUM_LEN = 1, 2
MIN_FLOW = 65.0
OB_LOOKBACK = 2
SWEEP_LOOKBACK, SWEEP_WINDOW = 5, 8
MSS_LOOKBACK, MSS_WINDOW = 5, 20
HTF_EMA = 65
MIN_HTF_ALIGN = 2
REQUIRE = dict(flow=True, ob=True, sweep=True, mss=True, htf=True)
STATE_FILE = "state.json"

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TD_KEY = os.environ.get("TWELVEDATA_API_KEY", "")


def tg(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text}, timeout=20)
    r.raise_for_status()


def fetch(interval, size, drop_partial, minutes):
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params=dict(symbol=SYMBOL, interval=interval, outputsize=size,
                    timezone="UTC", apikey=TD_KEY), timeout=30)
    j = r.json()
    if "values" not in j:
        raise RuntimeError(f"Twelve Data error ({interval}): {j}")
    df = pd.DataFrame(j["values"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    df["volume"] = df["volume"].astype(float) if "volume" in df else 1.0
    df = df.sort_values("datetime").reset_index(drop=True)
    if drop_partial:
        now = datetime.now(timezone.utc)
        if df["datetime"].iloc[-1] + timedelta(minutes=minutes) > now:
            df = df.iloc[:-1].reset_index(drop=True)
    return df


def htf_bias(df):
    ema = df["close"].ewm(span=HTF_EMA, adjust=False).mean()
    c, e = df["close"].iloc[-1], ema.iloc[-1]
    return (1 if c > e else -1 if c < e else 0)


def session_of(ts):
    h = ts.hour
    if SHOW_ASIAN and ASIAN[0] <= h < ASIAN[1]:
        return "Asian", ts.normalize() + pd.Timedelta(hours=ASIAN[0])
    if SHOW_LONDON and LONDON[0] <= h < LONDON[1]:
        return "London", ts.normalize() + pd.Timedelta(hours=LONDON[0])
    return None, None


def flow_series(df):
    rng = df["high"] - df["low"]
    buy_p = np.where(rng == 0, 0.5, (df["close"] - df["low"]) / rng.replace(0, np.nan))
    buy_p = pd.Series(buy_p, index=df.index).fillna(0.5)
    vol = df["volume"].replace(0, 1.0)
    buy_v, sell_v = vol * buy_p, vol * (1 - buy_p)
    delta = buy_v - sell_v
    sb, ss = buy_v.rolling(DELTA_LEN).mean(), sell_v.rolling(DELTA_LEN).mean()
    bias = (sb / (sb + ss)).fillna(0.5) * 100
    cum = delta.cumsum()
    mom = cum - cum.shift(MOMENTUM_LEN)
    mom_pct = (mom > 0).astype(float) * 100
    mom_score = mom_pct.rolling(MOMENTUM_LEN).mean().fillna(0)
    bull = (bias + mom_score) / 2
    return bull, 100 - bull


def find_ob(df, i, want_bull):
    for k in range(2, OB_LOOKBACK + 2):
        o, c = df["open"][i - k], df["close"][i - k]
        if (want_bull and c < o) or (not want_bull and c > o):
            return df["low"][i - k], df["high"][i - k]
    return None


def find_sweep(df, i, want_bull):
    for k in range(2, SWEEP_WINDOW + 2):
        if i - k - SWEEP_LOOKBACK < 0:
            break
        rng = range(i - k - SWEEP_LOOKBACK, i - k)
        if want_bull:
            lvl = min(df["low"][j] for j in rng)
            if df["low"][i - k] < lvl and df["close"][i - k] > lvl:
                return lvl
        else:
            lvl = max(df["high"][j] for j in rng)
            if df["high"][i - k] > lvl and df["close"][i - k] < lvl:
                return lvl
    return None


def find_mss(df, i, want_bull):
    for k in range(2, MSS_WINDOW + 2):
        if i - k - MSS_LOOKBACK < 0:
            break
        rng = range(i - k - MSS_LOOKBACK, i - k)
        if want_bull:
            lvl = max(df["high"][j] for j in rng)
            if df["close"][i - k] > lvl and df["close"][i - k - 1] <= lvl:
                return lvl
        else:
            lvl = min(df["low"][j] for j in rng)
            if df["close"][i - k] < lvl and df["close"][i - k - 1] >= lvl:
                return lvl
    return None


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    if "--test" in sys.argv:
        tg("✅ FVG signal bot: Test OK")
        return

    df = fetch("5min", 400, True, 5)
    i = len(df) - 1
    last_ts = df["datetime"].iloc[i]
    sess, sess_start = session_of(last_ts)
    if sess is None:
        print("Outside sessions")
        return

    # count FVG triggers earlier in this session (Pine counter)
    count = 0
    trigger = False
    for j in range(max(2, 0), i + 1):
        ts = df["datetime"].iloc[j]
        s, st = session_of(ts)
        if s != sess or st != sess_start:
            continue
        bull = df["low"][j] > df["high"][j - 2]
        bear = df["high"][j] < df["low"][j - 2]
        if (bull or bear) and count < FVG_PER_SESSION:
            count += 1
            if j == i:
                trigger = True
    if not trigger:
        print("No FVG trigger on last bar")
        return

    bull = df["low"][i] > df["high"][i - 2]
    top = df["low"][i] if bull else df["low"][i - 2]
    bottom = df["high"][i - 2] if bull else df["high"][i]

    bull_flow, bear_flow = flow_series(df)
    flow = float((bull_flow if bull else bear_flow).iloc[i])
    flow_ok = flow >= MIN_FLOW if REQUIRE["flow"] else True

    ob = find_ob(df, i, bull)
    ob_ok = ob is not None if REQUIRE["ob"] else True
    sw = find_sweep(df, i, bull)
    sw_ok = sw is not None if REQUIRE["sweep"] else True
    ms = find_mss(df, i, bull)
    ms_ok = ms is not None if REQUIRE["mss"] else True

    biases = [htf_bias(df)]  # 5m
    for iv, mins in (("15min", 15), ("30min", 30), ("1h", 60), ("4h", 240)):
        biases.append(htf_bias(fetch(iv, 200, False, mins)))
    want = 1 if bull else -1
    htf_cnt = sum(1 for b in biases if b == want)
    htf_ok = htf_cnt >= MIN_HTF_ALIGN if REQUIRE["htf"] else True

    print(dict(bull=bull, flow=flow, ob=ob, sweep=sw, mss=ms, htf=htf_cnt))
    if not (flow_ok and ob_ok and sw_ok and ms_ok and htf_ok):
        print("FVG found but confirmations failed")
        return

    state = load_state()
    key = str(last_ts)
    if state.get("last_signal") == key:
        print("Already sent")
        return

    entry = float(df["close"][i])
    sl = float(bottom if bull else top)
    tp = entry + TP_DOLLARS if bull else entry - TP_DOLLARS
    f = lambda v: f"{v:.2f}"
    txt = (
        f"{'🟢 BUY' if bull else '🔴 SELL'} XAUUSD ({sess})\n"
        f"Entry: {f(entry)}\nTP: {f(tp)}\nSL: {f(sl)}\n\n"
        "មូលហេតុ:\n"
        f"• FVG {'Bullish' if bull else 'Bearish'} ទើបបង្កើត\n"
        f"• Order Flow: {flow:.1f}%\n"
        f"• Order Block: {f(ob[0])} - {f(ob[1])}\n"
        f"• Liquidity Sweep: កម្រិត {f(sw)}\n"
        f"• MSS: {'ដាច់ឡើងលើ' if bull else 'ដាច់ចុះក្រោម'} (close) កម្រិត {f(ms)}\n"
        f"• HTF Trend តាម: {htf_cnt}/5 timeframe"
    )
    tg(txt)
    with open(STATE_FILE, "w") as fh:
        json.dump({"last_signal": key}, fh)
    print("Signal sent")


if __name__ == "__main__":
    main()
      
