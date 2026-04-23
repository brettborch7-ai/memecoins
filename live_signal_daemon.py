import os
import time
import json
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

BASE = "https://data.solanatracker.io"
API_KEY = os.getenv("SOLANATRACKER_API_KEY", "")
HEADERS = {"x-api-key": API_KEY} if API_KEY else {}
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DATA_DIR = os.getenv("DATA_DIR", ".")
STATE_FILE = os.path.join(DATA_DIR, "daemon_state.json")
BLACKLIST_FILE = os.path.join(DATA_DIR, "blacklist.json")

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def tg(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(msg)
        return
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=15)

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def safe_get(path, params=None):
    try:
        return get(path, params)
    except Exception:
        return None

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def macd_h(close):
    m = ema(close, 12) - ema(close, 26)
    s = ema(m, 9)
    return m - s

def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([(df["high"]-df["low"]).abs(), (df["high"]-pc).abs(), (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def get_tokens(limit=40):
    j = safe_get("/tokens/trending", {"limit": limit})
    if not j:
        return []
    items = j if isinstance(j, list) else j.get("data", j.get("tokens", []))
    out = []
    for it in items:
        m = it.get("tokenAddress") or it.get("mint") or ((it.get("token") or {}).get("mint"))
        if m:
            out.append(m)
    return list(dict.fromkeys(out))

def get_info(mint):
    return safe_get(f"/tokens/{mint}")

def get_chart(mint, tf="5m", bars=300):
    j = safe_get(f"/chart/{mint}", {"type": tf})
    if not j:
        return None
    raw = j.get("oclhv", j.get("ohlcv", j.get("data", [])))
    if not raw:
        return None
    df = pd.DataFrame(raw).sort_values("time").tail(bars)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna().reset_index(drop=True)

def compute_signal(df):
    x = df.copy()
    x["ema20"] = ema(x["close"], 20)
    x["ema50"] = ema(x["close"], 50)
    x["rsi"] = rsi(x["close"], 14)
    x["macd_h"] = macd_h(x["close"])
    x["atrp"] = atr(x, 14) / x["close"] * 100
    x["volma"] = x["volume"].rolling(20).mean()
    r = x.iloc[-1]
    buy = (r["ema20"] > r["ema50"]) and (r["rsi"] > 55) and (r["macd_h"] > 0) and (r["atrp"] > 1.0) and (r["volume"] > r["volma"] * 1.4)
    sell = (r["ema20"] < r["ema50"]) and (r["rsi"] < 45) and (r["macd_h"] < 0)
    return buy, sell, float(r["close"])

def main():
    if not API_KEY:
        raise RuntimeError("Set SOLANATRACKER_API_KEY")
    state = load_json(STATE_FILE, {"last": {}})
    blacklist = load_json(BLACKLIST_FILE, {})
    tg("Signal daemon started")
    while True:
        for mint in get_tokens():
            if mint in blacklist:
                continue
            info = get_info(mint)
            if not info:
                continue
            pools = info.get("pools", [])
            if not pools:
                blacklist[mint] = {"reason": "no_pools", "ts": now_iso()}
                continue
            pool = max(pools, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))
            liq = ((pool.get("liquidity") or {}).get("usd") or 0)
            if liq < 50000:
                blacklist[mint] = {"reason": "low_liq", "ts": now_iso()}
                continue
            df = get_chart(mint)
            if df is None or len(df) < 120:
                continue
            buy, sell, px = compute_signal(df)
            key = f"{mint}"
            prev = state["last"].get(key)
            if buy and prev != "BUY":
                tg(f"BUY {mint} @ {px}")
                state["last"][key] = "BUY"
            elif sell and prev != "SELL":
                tg(f"SELL {mint} @ {px}")
                state["last"][key] = "SELL"
        save_json(STATE_FILE, state)
        save_json(BLACKLIST_FILE, blacklist)
        time.sleep(60)

if __name__ == "__main__":
    main()
