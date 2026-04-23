import os
import time
import requests
import numpy as np
import pandas as pd

API_KEY = os.getenv("SOLANATRACKER_API_KEY", "")
BASE = "https://data.solanatracker.io"
HEADERS = {"x-api-key": API_KEY} if API_KEY else {}
DATA_DIR = os.getenv("DATA_DIR", ".")

def _get(path: str, params=None):
    if not API_KEY:
        raise RuntimeError("Set SOLANATRACKER_API_KEY")
    r = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def safe_get(path: str, params=None):
    try:
        return _get(path, params)
    except Exception as e:
        print(f"[WARN] {path} failed: {e}")
        return None

def get_tokens(limit=50):
    out = []
    for ep in ("/tokens/trending", "/tokens/volume"):
        j = safe_get(ep, {"limit": limit})
        if not j:
            continue
        items = j if isinstance(j, list) else j.get("data", j.get("tokens", []))
        for it in items:
            mint = it.get("tokenAddress") or it.get("mint") or ((it.get("token") or {}).get("mint"))
            if mint:
                out.append(mint)
    return list(dict.fromkeys(out))[:limit]

def get_info(mint: str):
    return safe_get(f"/tokens/{mint}")

def get_ohlcv(mint: str, tf="5m", bars=1000):
    j = safe_get(f"/chart/{mint}", {"type": tf})
    if not j:
        return None
    raw = j.get("oclhv", j.get("ohlcv", j.get("data", [])))
    if not raw:
        return None
    df = pd.DataFrame(raw)
    needed = {"open", "high", "low", "close", "volume", "time"}
    if not needed.issubset(df.columns):
        return None
    df = df.sort_values("time").tail(bars).copy()
    df["time"] = pd.to_datetime(df["time"], unit="s", errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna().reset_index(drop=True)

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def macd_hist(close, fast=12, slow=26, sig=9):
    m = ema(close, fast) - ema(close, slow)
    return m - ema(m, sig)

def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def score_strategy(df):
    x = df.copy()
    x["ema20"] = ema(x["close"], 20)
    x["ema50"] = ema(x["close"], 50)
    x["rsi"] = rsi(x["close"], 14)
    x["macd_h"] = macd_hist(x["close"])
    x["atrp"] = atr(x, 14) / x["close"] * 100
    x["volma"] = x["volume"].rolling(20).mean()

    x["buy"] = (x["ema20"] > x["ema50"]) & (x["rsi"] > 55) & (x["macd_h"] > 0) & (x["volume"] > x["volma"] * 1.5) & (x["atrp"] >= 1.2)
    x["sell"] = (x["ema20"] < x["ema50"]) & (x["rsi"] < 45) & (x["macd_h"] < 0)

    eq = 1.0
    in_pos = False
    entry = 0.0
    fees = 0.005
    rets = []
    for _, r in x.iterrows():
        p = float(r["close"])
        if not in_pos and r["buy"]:
            entry = p * (1 + fees)
            in_pos = True
        elif in_pos and r["sell"]:
            exit_p = p * (1 - fees)
            ret = exit_p / entry - 1
            rets.append(ret)
            eq *= 1 + ret
            in_pos = False
    if not rets:
        return None
    return {
        "trades": len(rets),
        "win_rate": 100 * sum(v > 0 for v in rets) / len(rets),
        "total_return_pct": (eq - 1) * 100,
        "avg_trade_pct": np.mean(rets) * 100,
    }

def main():
    rows = []
    for mint in get_tokens(60):
        info = get_info(mint)
        if not info:
            continue
        df = get_ohlcv(mint)
        if df is None or len(df) < 120:
            continue
        s = score_strategy(df)
        if s and s["trades"] >= 5:
            rows.append({"mint": mint, **s})
        time.sleep(0.05)
    if not rows:
        print("No results")
        return
    out = pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)
    os.makedirs(DATA_DIR, exist_ok=True)
    out.to_csv(os.path.join(DATA_DIR, "research_results.csv"), index=False)
    print(out.head(20).to_string(index=False))

if __name__ == "__main__":
    main()
