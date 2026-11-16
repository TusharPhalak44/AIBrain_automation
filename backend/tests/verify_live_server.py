import requests
import json
import datetime
import numpy as np

BASE_URL = "http://127.0.0.1:8000/api"

def main():
    print("Testing Live Server at", BASE_URL)
    
    # 1. Health
    h = requests.get(f"{BASE_URL}/health").json()
    print("1. /api/health:", h)
    
    # 2. List Strategies
    strats = requests.get(f"{BASE_URL}/strategies").json()
    print(f"2. /api/strategies: Found {len(strats)} strategies:")
    for s in strats:
        print(f"   [{s['id']}] {s['name']} ({s['target_mode']}) - Builtin: {s['is_builtin']}")
        
    # 3. Validate
    v1 = requests.post(f"{BASE_URL}/strategies/validate", json={"python_code": "DEFAULT_PARAMS={}\ndef evaluate(df, params):\n    return None"}).json()
    print("3a. Validation valid code:", v1["valid"], "-", v1["message"])
    v2 = requests.post(f"{BASE_URL}/strategies/validate", json={"python_code": "import os"}).json()
    print("3b. Validation bad code rejected:", not v2["valid"], "-", v2["error"])
    
    # 4. Execute Backtest
    base_time = datetime.datetime(2026, 11, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
    bars = []
    for i in range(60):
        t = (base_time + datetime.timedelta(hours=i)).isoformat()
        c = 2650.0 + float(np.sin(i * 0.2) * 15.0 + i * 0.5)
        bars.append({
            "time": t,
            "open": c - 0.5,
            "high": c + 2.5,
            "low": c - 2.5,
            "close": c,
            "tick_volume": 100,
            "spread": 25
        })
    bt_payload = {
        "strategy_id": strats[0]["id"],
        "symbol": "GOLD#",
        "timeframe": "H1",
        "test_mode": "PER_TRADE_100",
        "bars_data": bars
    }
    bt_res = requests.post(f"{BASE_URL}/strategies/backtest", json=bt_payload)
    print("4. /api/strategies/backtest status:", bt_res.status_code)
    if bt_res.status_code == 200:
        data = bt_res.json()
        print("   Returned Keys:", list(data.keys()))
        print("   Symbol:", data.get("symbol"))
        print("   Mode:", data.get("test_mode"))
        print("   Capital ($):", data.get("capital_usd"))
        print("   Profitability (%):", data.get("profitability_pct"))
        print("   Gross PnL ($):", data.get("gross_pnl_usd"))
        print("   Spread Cost ($):", data.get("spread_cost_usd"))
        print("   Swap Cost ($):", data.get("swap_cost_usd"))
        print("   Commission ($):", data.get("commission_usd"))
        print("   Net PnL ($):", data.get("net_pnl_usd"))
        print("   Total Trades:", data.get("total_trades"))
        print("   Win Rate (%):", data.get("win_rate_pct"))
        print("   Profit Factor:", data.get("profit_factor"))
        print("   Trades Log Count:", len(data.get("trades", [])))
    else:
        print("   Backtest Error:", bt_res.text)

    # 5. Query Backtests
    history = requests.get(f"{BASE_URL}/strategies/backtests?symbol=GOLD#").json()
    print(f"5. /api/strategies/backtests: Found {len(history)} recorded runs in MySQL.")

    # 6. Assign Strategy to Pairs: GOLD# (SCALP) and BTCUSD# (SWING)
    assign_gold = requests.post(f"{BASE_URL}/pairs/GOLD/assign-strategy", json={"scalp_strategy_id": 1}).json()
    print("6a. Assigned GOLD# Scalp Strategy:", assign_gold.get("symbol"), "scalp_strategy_id:", assign_gold.get("scalp_strategy_id"))
    assign_btc = requests.post(f"{BASE_URL}/pairs/BTCUSD/assign-strategy", json={"swing_strategy_id": 4}).json()
    print("6b. Assigned BTCUSD# Swing Strategy:", assign_btc.get("symbol"), "swing_strategy_id:", assign_btc.get("swing_strategy_id"))

if __name__ == "__main__":
    main()
