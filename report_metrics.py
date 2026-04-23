import os
import numpy as np
import pandas as pd

DATA_DIR = os.getenv("DATA_DIR", ".")
TRADES_FILE = os.path.join(DATA_DIR, "paper_trades.csv")
EQUITY_FILE = os.path.join(DATA_DIR, "paper_equity.csv")
OUT_SUMMARY = os.path.join(DATA_DIR, "paper_report_summary.csv")
OUT_DAILY = os.path.join(DATA_DIR, "paper_report_daily.csv")

def max_drawdown(equity):
    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    return float(dd.min())

def sharpe_like(returns, periods_per_year=365):
    mu = returns.mean()
    sd = returns.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return 0.0
    return float((mu / sd) * np.sqrt(periods_per_year))

def main():
    if not os.path.exists(TRADES_FILE) or not os.path.exists(EQUITY_FILE):
        raise FileNotFoundError("Need paper_trades.csv and paper_equity.csv first")
    trades = pd.read_csv(TRADES_FILE)
    equity = pd.read_csv(EQUITY_FILE)
    trades["time"] = pd.to_datetime(trades["time"], utc=True, errors="coerce")
    equity["time"] = pd.to_datetime(equity["time"], utc=True, errors="coerce")
    trades = trades.dropna(subset=["time"]).sort_values("time")
    equity = equity.dropna(subset=["time"]).sort_values("time")

    equity["ret"] = equity["equity"].pct_change().fillna(0.0)
    start_eq = float(equity["equity"].iloc[0])
    end_eq = float(equity["equity"].iloc[-1])
    total_return_pct = (end_eq/start_eq - 1)*100
    mdd = max_drawdown(equity["equity"])*100
    sharpe = sharpe_like(equity["ret"])

    sells = trades[trades["side"].str.upper()=="SELL"].copy()
    sells["pnl"] = pd.to_numeric(sells.get("pnl", 0.0), errors="coerce").fillna(0.0)
    n = len(sells)
    wins = int((sells["pnl"]>0).sum())
    losses = int((sells["pnl"]<0).sum())
    win_rate = (wins/n*100) if n else 0.0
    gross_profit = float(sells.loc[sells["pnl"]>0, "pnl"].sum())
    gross_loss = float(-sells.loc[sells["pnl"]<0, "pnl"].sum())
    net_profit = float(sells["pnl"].sum())
    profit_factor = (gross_profit/gross_loss) if gross_loss > 0 else np.inf
    avg_win = float(sells.loc[sells["pnl"]>0, "pnl"].mean()) if wins else 0.0
    avg_loss = float(sells.loc[sells["pnl"]<0, "pnl"].mean()) if losses else 0.0
    expectancy = (wins/n*avg_win + losses/n*avg_loss) if n else 0.0

    summary = pd.DataFrame([{
        "start_equity": round(start_eq,2),
        "end_equity": round(end_eq,2),
        "total_return_pct": round(total_return_pct,2),
        "max_drawdown_pct": round(mdd,2),
        "sharpe_like": round(sharpe,3),
        "closed_trades": int(n),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate,2),
        "gross_profit": round(gross_profit,2),
        "gross_loss": round(gross_loss,2),
        "net_profit": round(net_profit,2),
        "profit_factor": round(float(profit_factor),3) if np.isfinite(profit_factor) else "inf",
        "avg_win": round(avg_win,2),
        "avg_loss": round(avg_loss,2),
        "expectancy_per_trade": round(expectancy,2),
    }])

    daily = equity.set_index("time")["equity"].resample("1D").last().dropna().to_frame()
    daily["daily_ret_pct"] = daily["equity"].pct_change().fillna(0.0)*100
    daily = daily.reset_index()

    summary.to_csv(OUT_SUMMARY, index=False)
    daily.to_csv(OUT_DAILY, index=False)
    print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
