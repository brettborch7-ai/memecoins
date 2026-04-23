import os
import time
import signal
import subprocess
from datetime import datetime, timezone
import pandas as pd
import requests

REPORT_EVERY_MIN = 30
DAILY_SUMMARY_HOUR_UTC = 0
TRADER_CMD = ["python", "paper_trader.py"]
REPORT_CMD = ["python", "report_metrics.py"]
DATA_DIR = os.getenv("DATA_DIR", ".")
SUMMARY_FILE = os.path.join(DATA_DIR, "paper_report_summary.csv")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(msg)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as exc:
        print(f"[WARN] telegram send failed: {exc}")

def run_report():
    p = subprocess.run(REPORT_CMD, capture_output=True, text=True)
    print(p.stdout)
    if p.stderr:
        print(p.stderr)
    return p.returncode == 0

def load_summary_line():
    if not os.path.exists(SUMMARY_FILE):
        return "No summary yet"
    df = pd.read_csv(SUMMARY_FILE)
    if df.empty:
        return "Summary empty"
    r = df.iloc[0].to_dict()
    return (
        "📊 Daily Paper Trading Summary\n"
        f"Start Equity: ${r.get('start_equity')}\n"
        f"End Equity: ${r.get('end_equity')}\n"
        f"Total Return: {r.get('total_return_pct')}%\n"
        f"Max Drawdown: {r.get('max_drawdown_pct')}%\n"
        f"Sharpe-like: {r.get('sharpe_like')}\n"
        f"Closed Trades: {r.get('closed_trades')}\n"
        f"Win Rate: {r.get('win_rate_pct')}%\n"
        f"Profit Factor: {r.get('profit_factor')}\n"
        f"Expectancy/Trade: ${r.get('expectancy_per_trade')}\n"
        f"Net Profit: ${r.get('net_profit')}"
    )

def start_trader():
    # Let child logs go directly to stdout/stderr to avoid blocking readline loops.
    return subprocess.Popen(TRADER_CMD)

def stop_trader(proc):
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    send_telegram("🟢 Orchestrator started")
    trader = start_trader()
    last_bucket = None
    last_daily = None

    try:
        while True:
            now = datetime.now(timezone.utc)
            if trader.poll() is not None:
                send_telegram("⚠️ paper_trader.py crashed; restarting")
                trader = start_trader()

            bucket = (now.hour * 60 + now.minute) // REPORT_EVERY_MIN
            if bucket != last_bucket:
                ok = run_report()
                if not ok:
                    print("[WARN] report_metrics.py failed for this interval")
                last_bucket = bucket

            today = now.date().isoformat()
            if now.hour == DAILY_SUMMARY_HOUR_UTC and now.minute < 5 and last_daily != today:
                send_telegram(load_summary_line())
                last_daily = today

            time.sleep(15)
    except KeyboardInterrupt:
        pass
    finally:
        stop_trader(trader)
        send_telegram("🔴 Orchestrator stopped")

if __name__ == "__main__":
    main()
