Act as a Principal Quantitative Trading Architect and Senior Python/MySQL Engineer. Continuing our V2 build in `E:\AIBrain` (strictly adhering to `@AGENTS.md` and our XAMPP MySQL models in `@backend/app/db/models.py`), implement **Phase 2: Pasteable Python Strategy Sandbox, Realistic XM Global Fee Engine, and $100 Strategy Tester**.

Strictly ZERO Indian/US stock market or equity F&O feeds—focus exclusively on XM Global MT5 instruments (Gold, Forex majors, BTC, ETH, and SOL).

---
### DELIVERABLE 1: AST-GUARDED PYTHON STRATEGY SANDBOX (`/backend/app/strategy_lab/sandbox.py`)
1. **Standard Strategy Contract:**
   Every strategy script defines `DEFAULT_PARAMS: dict` and:
   `def evaluate(df: pd.DataFrame, params: dict) -> dict | None:`
   where `df` has columns `["time", "open", "high", "low", "close", "tick_volume", "spread"]` and returns `None` or:
   `{"signal": "BUY" | "SELL", "mode": "SCALP" | "SWING", "entry": float, "sl": float, "tp1": float, "tp2": float, "reason": str}`.
2. **AST Security & Indicator Helper Injection:**
   - Parse user-pasted strategy code via Python `ast` BEFORE compilation/execution and block any dangerous AST nodes (`Import`, `ImportFrom`, `Exec`, `Eval`, attribute access starting with `__`, and calls to `open`, `exec`, `eval`, `compile`, `__import__`, `getattr`, `setattr`, `delattr`, `globals`, `locals`, `vars`).
   - Inject pre-vetted, vectorized helper functions into the strategy execution globals:
     * `atr(df, period=14)` (Wilder/EMA True Range)
     * `ema(series, period)`
     * `rsi(series, period=14)`
     * `swing_highs(df, left=3, right=3)` & `swing_lows(df, left=3, right=3)`
     * `detect_fvg(df)` (3-candle Fair Value Gap imbalance detector)
     * `detect_liquidity_sweep(df, lookback=20)` (wick beyond range high/low with close back inside)
     * `np` (read-only numpy math helpers) and `pd` (pandas).
   - Enforce a 2-second execution timeout guard per backtest and validate signal geometry (`BUY`: `sl < entry < tp1 <= tp2`; `SELL`: `sl > entry > tp1 >= tp2`) before accepting any signal.

---
### DELIVERABLE 2: XM GLOBAL BROKERAGE FEE & CONTRACT ENGINE (`/backend/app/strategy_lab/xm_fee_model.py`)
1. Load exact symbol specs from `TradingPairBot` in XAMPP MySQL (`contract_size`, `tick_size`, `tick_value`, `digits`, `volume_min`, `volume_step`, `swap_long`, `swap_short`, `three_day_swap_day`), with accurate XM Ultra Low (`#`) / Standard / Micro defaults if MT5 has not yet synced that symbol.
2. Calculate realistic XM execution friction on every simulated trade:
   - **Bid/Ask Spread Deduction:** Use historical bar `spread` points (or `max_spread_points * 0.6` baseline if bar spread is `0`): `BUY` enters at `Ask = open + spread_price` and exits at `Bid`; `SELL` enters at `Bid = open` and exits at `Ask = exit + spread_price`.
   - **Slippage:** Deduct configurable slippage points (`default: 2 pts` Metals/Forex, `15 pts` Crypto CFDs).
   - **Overnight Swap & Wednesday 3x Triple-Swap:** Whenever an open trade crosses `00:00` broker server midnight (`clock_sync`), apply `swap_long` or `swap_short` per lot per night, automatically multiplying by **3x** on `three_day_swap_day` (default Wednesday `2`).
   - **Commission:** `$0.00` default for XM Ultra Low / Standard accounts (or configurable `commission_per_lot`).

---
### DELIVERABLE 3: $100 STRATEGY TESTER ENGINE (`/backend/app/strategy_lab/backtester.py`)
1. **Zero Look-Ahead Bar-by-Bar Execution:**
   - Fetch historical OHLCV bars from XM Global MT5 via `mt5_actor` (supporting `M1`, `M5`, `M15`, `H1`, `H4`, `D1`), or accept uploaded/cached OHLCV DataFrames when MT5 terminal is offline—NEVER generate fake random-walk candles.
   - Call `evaluate(df.iloc[:i+1], params)` at bar `i` close and execute on bar `i+1` open.
   - Mirror `PairChartBot.mq5` exit behavior identically:
     * **Micro-Lot Tier (`lots < 2 * volume_step`, e.g., `0.01` lot):** Skip partial split; at `tp1` (`+1.5R`), shift SL to `Break-Even + spread_buffer` and hold/trail 100% to `tp2`.
     * **Standard Tier (`lots >= 2 * volume_step`, e.g., `>= 0.02` lots):** Close `50%` at `tp1` (`+1.5R`), move SL to Break-Even, and hold/trail remaining `50%` to `tp2`.
2. **Two Selectable $100 Test Modes (`test_mode`):**
   - `PER_TRADE_100` (**$100 Trade Profitability Mode**): Allocates `$100.00` capital/margin budget per setup so every strategy is benchmarked on a `$100` trade basis, reporting exact **Profitability %** (`net_pnl_usd / 100.0 * 100`), Win Rate %, Profit Factor, Gross PnL ($), Spread Cost ($), Swap Cost ($), Commission ($), Net PnL ($), and per-trade R-multiples.
   - `ACCOUNT_100` (**$100 Realistic Account Mode**): Starts with `$100.00` equity, computes dynamic lot size from risk % + SL distance, enforces XM margin requirements (`18%` cap / leverage) and minimum `0.01` lot constraints (logging skipped setups when `$100` margin cannot cover `0.01` lot on standard 100-oz Gold), and outputs compounding equity curve + Max Drawdown %.
3. Persist every completed test into `BacktestRun` in XAMPP MySQL (`xm_trading_v2`).

---
### DELIVERABLE 4: 4 BUILT-IN STARTER STRATEGIES & REST ROUTES (`/api/strategies/*`)
1. Auto-seed 4 built-in starter strategies into `StrategyScript` (`is_builtin=True`) during startup if missing:
   - `Liquidity Sweep + FVG Reversal` (`SCALP`)
   - `London & NY Session Breakout` (`SCALP`)
   - `H1/H4 EMA Trend Pullback + ATR` (`SWING`)
   - `24/7 Crypto Volatility Squeeze` (`BOTH` — tuned for `BTCUSD#`, `ETHUSD#`, `SOLUSD#`)
2. Implement `/backend/app/api/routes/strategies.py` and register in `server.py`:
   - `GET /api/strategies` (list all built-in + custom strategies)
   - `POST /api/strategies/validate` (dry-run AST security + syntax check on pasted code)
   - `POST /api/strategies` & `PUT /api/strategies/{strategy_id}` & `DELETE /api/strategies/{strategy_id}` (save/update/delete custom user strategies in MySQL; protect built-ins from deletion)
   - `POST /api/strategies/backtest` (execute `$100` backtest, save `BacktestRun`, return full KPIs, XM fee breakdown, equity curve, and trade-by-trade log)
   - `GET /api/strategies/backtests` (list historical backtest runs with filters by symbol/strategy)
   - `POST /api/pairs/{symbol}/assign-strategy` (assign `scalp_strategy_id` and/or `swing_strategy_id` to a `TradingPairBot` row in MySQL).

---
### VERIFICATION GATE
Write `/backend/tests/test_phase2_strategy_lab.py` using isolated `xm_trading_v2_test` DB verifying:
1. AST sandbox rejects `import os` / `eval()` while executing valid indicator math cleanly.
2. XM spread + Wednesday 3x overnight swap fee calculations deduct accurately from Gross PnL.
3. Both `PER_TRADE_100` and `ACCOUNT_100` backtest runs persist to `BacktestRun` and verify both `0.01` micro-lot break-even logic and `>=0.02` 50% partial-close logic.
4. Saving a custom pasted strategy script and assigning it to `GOLD#` (`SCALP`) and `BTCUSD#` (`SWING`) persists in MySQL.
Run `pytest -v` until 100% green and verify `/api/strategies` and `/api/strategies/backtest` respond cleanly on `:8000`.