import os
import time
import json
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

API_KEY = os.getenv("SOLANATRACKER_API_KEY", "")
BASE = "https://data.solanatracker.io"
HEADERS = {"x-api-key": API_KEY} if API_KEY else {}

STARTING_CAPITAL = 5000.0
RISK_PER_TRADE = 0.01
MAX_CONCURRENT_POSITIONS = 3
FEE_SLIP = 0.005

DATA_DIR = os.getenv("DATA_DIR", ".")
STATE_FILE = os.path.join(DATA_DIR, "paper_state.json")
TRADES_CSV = os.path.join(DATA_DIR, "paper_trades.csv")
EQUITY_CSV = os.path.join(DATA_DIR, "paper_equity.csv")

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

def append_csv(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pd.DataFrame([row]).to_csv(path, mode="a", header=not os.path.exists(path), index=False)

def get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def safe_get(path, params=None):
    try:
        return get(path, params)
    except Exception:
        return None

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - (100/(1+rs))

def macd_h(close):
    m = ema(close, 12) - ema(close, 26)
    s = ema(m, 9)
    return m-s

def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([(df["high"]-df["low"]).abs(), (df["high"]-pc).abs(), (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def get_tokens(limit=30):
    j = safe_get("/tokens/trending", {"limit": limit})
    if not j:
        return []
    items = j if isinstance(j, list) else j.get("data", j.get("tokens", []))
    out = []
    for it in items:
        m = it.get("tokenAddress") or it.get("mint") or ((it.get("token") or {}).get("mint"))
        if m:
            out.append(m)
    return list(dict.fromkeys(out))[:limit]

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

def signal(df):
    x = df.copy()
    x["ema20"] = ema(x["close"], 20)
    x["ema50"] = ema(x["close"], 50)
    x["rsi"] = rsi(x["close"], 14)
    x["macd_h"] = macd_h(x["close"])
    x["atrp"] = atr(x,14)/x["close"]*100
    x["volma"] = x["volume"].rolling(20).mean()
    r = x.iloc[-1]
    buy = (r["ema20"] > r["ema50"]) and (r["rsi"] > 55) and (r["macd_h"] > 0) and (r["atrp"] > 1.0) and (r["volume"] > r["volma"]*1.4)
    sell = (r["ema20"] < r["ema50"]) and (r["rsi"] < 45) and (r["macd_h"] < 0)
    return buy, sell, float(r["close"])

def main():
    if not API_KEY:
        raise RuntimeError("Set SOLANATRACKER_API_KEY")
    state = load_json(STATE_FILE, {"cash": STARTING_CAPITAL, "positions": {}})

    while True:
        market = {}
        for mint in get_tokens():
            info = get_info(mint)
            if not info:
                continue
            pools = info.get("pools", [])
            if not pools:
                continue
            liq = max((((p.get("liquidity") or {}).get("usd") or 0) for p in pools), default=0)
            if liq < 100000:
                continue
            df = get_chart(mint)
            if df is None or len(df) < 120:
                continue
            buy, sell, px = signal(df)
            symbol = info.get("token", {}).get("symbol", mint[:6])
            market[mint] = {"buy": buy, "sell": sell, "price": px, "symbol": symbol}

        # exits
        for mint in list(state["positions"].keys()):
            p = state["positions"][mint]
            if mint not in market:
                continue
            px = market[mint]["price"]
            p["bars"] += 1
            stop = px <= p["entry"] * 0.92
            tp = px >= p["entry"] * 1.2
            time_exit = p["bars"] >= 72
            if market[mint]["sell"] or stop or tp or time_exit:
                exit_eff = px*(1-FEE_SLIP)
                proceeds = p["qty"]*exit_eff
                pnl = proceeds - p["cost"]
                state["cash"] += proceeds
                append_csv(TRADES_CSV, {"time": now_iso(), "mint": mint, "symbol": p["symbol"], "side": "SELL", "price_raw": px, "price_eff": exit_eff, "qty": p["qty"], "notional": proceeds, "pnl": pnl})
                del state["positions"][mint]

        # entries
        slots = MAX_CONCURRENT_POSITIONS - len(state["positions"])
        if slots > 0:
            for mint, v in list(market.items()):
                if slots <= 0:
                    break
                if mint in state["positions"] or not v["buy"]:
                    continue
                entry = v["price"]*(1+FEE_SLIP)
                risk_dollars = state["cash"]*RISK_PER_TRADE
                qty = risk_dollars/max(entry*0.08, 1e-12)
                cost = qty*entry
                if cost > state["cash"]:
                    cost = state["cash"]*0.95
                    qty = cost/entry
                if cost < 25:
                    continue
                state["cash"] -= cost
                state["positions"][mint] = {"symbol": v["symbol"], "entry": entry, "qty": qty, "cost": cost, "bars": 0}
                append_csv(TRADES_CSV, {"time": now_iso(), "mint": mint, "symbol": v["symbol"], "side": "BUY", "price_raw": v["price"], "price_eff": entry, "qty": qty, "notional": cost, "pnl": 0.0})
                slots -= 1

        equity = state["cash"]
        for mint, p in state["positions"].items():
            px = market.get(mint, {}).get("price", p["entry"])
            equity += p["qty"]*px
        append_csv(EQUITY_CSV, {"time": now_iso(), "cash": state["cash"], "open_positions": len(state["positions"]), "equity": equity})
        save_json(STATE_FILE, state)
        print(f"[{now_iso()}] equity={equity:.2f} cash={state['cash']:.2f} open={len(state['positions'])}")
        time.sleep(60)

if __name__ == "__main__":
    main()
