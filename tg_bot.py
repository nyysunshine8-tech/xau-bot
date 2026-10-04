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

