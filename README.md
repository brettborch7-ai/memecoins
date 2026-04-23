# memecoins

Solana memecoin research + live signal + paper trading toolkit.

## Files
- `memecoin_research_bot.py` - historical research/backtest ranking.
- `live_signal_daemon.py` - live BUY/SELL alerts (Telegram optional).
- `paper_trader.py` - simulated execution engine.
- `report_metrics.py` - metrics from paper trading logs.
- `run_all.py` - orchestrator to run trader + recurring reports.
- `Dockerfile` and `docker-compose.yml` - 24/7 deployment.

## Quick start
1. `cp .env.example .env`
2. Add your API keys to `.env`
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run orchestrator:
   ```bash
   python run_all.py
   ```

Runtime output files are written to `DATA_DIR` (defaults to current directory).

## Docker
```bash
docker compose up -d --build
docker compose logs -f --tail=200
```

Docker persists runtime CSV/JSON artifacts in `./data` on the host.
