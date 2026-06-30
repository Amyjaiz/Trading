# Trading Project — Claude Context

## Repository
- GitHub: `amyjaiz/trading`
- Active dev branch: `claude/trade-project-hm-portal-aez1sk`
- All pushes go to this branch via `mcp__github__push_files` (local git proxy is read-only for direct API; use git push via local proxy instead)

## User's Windows Machine Layout
```
C:\Trade\
├── hm\                  ← hm/hm_backtest.py from repo
├── nse200\              ← nse200/nse200_backtest.py from repo
├── triple_screen\       ← triple_screen scripts
└── dashboard\           ← dashboard/hm_dashboard.py + templates/ + static/
```

## Deployment Workflow (how user updates their machine)
1. `git pull origin claude/trade-project-hm-portal-aez1sk`  (or clone fresh)
2. Copy files to correct locations:
   - `repo\hm\hm_backtest.py`          → `C:\Trade\hm\hm_backtest.py`
   - `repo\nse200\nse200_backtest.py`  → `C:\Trade\nse200\nse200_backtest.py`
   - `repo\dashboard\hm_dashboard.py`  → `C:\Trade\dashboard\hm_dashboard.py`
   - `repo\dashboard\templates\*`      → `C:\Trade\dashboard\templates\`
   - `repo\dashboard\static\*`         → `C:\Trade\dashboard\static\`
3. Run: `python C:\Trade\dashboard\hm_dashboard.py`
4. Open browser at `http://localhost:5000`

## Tech Stack Constraints (NEVER break these)
- Flask + Flask-SocketIO `async_mode="threading"` — NEVER eventlet
- Python 3.13 with `from __future__ import annotations`
- `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1` in subprocess env
- Per-model subprocess management: `_backtest_procs`, `_backtest_status`, `_backtest_locks` (all dicts keyed by model)

## Security Rules (hardcoded, never change)
- `TRADING_ENABLED = False` by default
- `MAX_ORDER_VALUE = 25_000` hard cap — cannot be overridden from UI
- TOTP required on every order
- Angel One credentials hardcoded in scripts (user preference)
- Password stored as PBKDF2 hash in `dashboard_auth.json`
- All WebSocket connections rejected if session not authenticated

## File Locations on Windows
- HM bot:            `C:\Trade\hm\`
- NSE200 bot:        `C:\Trade\nse200\`
- Triple Screen bot: `C:\Trade\triple_screen\`
- Dashboard:         `C:\Trade\dashboard\`

## Backtest Output Files (dashboard reads these)
- `C:\Trade\hm\hm_trades.csv`         — trade log (columns: date, symbol, action, qty, price, pnl, pnl_pct, held_days, model)
- `C:\Trade\hm\hm_metrics.json`       — CAGR/Sharpe/MaxDD saved by hm_backtest.py
- `C:\Trade\nse200\nse200_trades.csv` — trade log
- `C:\Trade\nse200\nse200_metrics.json` — CAGR/Sharpe/MaxDD saved by nse200_backtest.py

## Universe Customisation
- `C:\Trade\dashboard\custom_universe.json` — stores add/remove/extra per model
- HM model: adds → `--extra-stocks`, removes → `--exclude` flags passed to subprocess
- NSE model: adds → `--stocks` flag passed to subprocess
