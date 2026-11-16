import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000/api"

def main():
    print("=== LIVE SERVER VERIFICATION (PHASE 3) ===")
    
    # 1. Health
    h = requests.get(f"{BASE_URL}/health").json()
    print("1. /api/health:", h["status"], "| MySQL:", h["components"]["mysql"]["status"])
    
    # 2. News & Blackout
    news = requests.get(f"{BASE_URL}/ai/news?symbol=GOLD#").json()
    print(f"2. /api/ai/news: Found {news['total_events']} scheduled events. Blackout status:")
    print("   Symbol:", news["blackout_check"]["symbol"])
    print("   Is Blackout:", news["blackout_check"]["is_blackout"])
    print("   Reason:", news["blackout_check"]["blackout_reason"])
    
    # 3. Update Scan Intervals
    int_res = requests.post(
        f"{BASE_URL}/ai/interval",
        json={"global_scan_interval_sec": 180, "pair_intervals": {"GOLD#": 60, "BTCUSD#": 45}},
    ).json()
    print("3. /api/ai/interval:", int_res["status"], "-", int_res["message"])
    
    # 4. Trigger Manual Scan on GOLD#
    print("4. Triggering POST /api/ai/scan/GOLD# ...")
    scan_gold = requests.post(f"{BASE_URL}/ai/scan/GOLD#").json()
    print("   Result:", scan_gold.get("status"), "| Symbol:", scan_gold.get("symbol"))
    print("   Regime:", scan_gold.get("market_regime"), "| Decision:", scan_gold.get("decision"))
    print("   Execution Status:", scan_gold.get("execution_status"))
    print("   Thesis:", scan_gold.get("thesis_text"))
    
    # 5. Trigger Scan-All Across Active XM Pairs
    print("5. Triggering POST /api/ai/scan-all ...")
    scan_all = requests.post(f"{BASE_URL}/ai/scan-all").json()
    print(f"   Scanned {scan_all.get('scanned_count')} pairs across XM Global:")
    for res in scan_all.get("results", []):
        print(f"   • {res['symbol']}: Regime={res['regime']} | Decision={res['decision']} | Status={res['status']}")
        
    # 6. List AI Reports
    reports = requests.get(f"{BASE_URL}/ai/reports?limit=10").json()
    print(f"6. /api/ai/reports: Found {len(reports)} persisted reports in MySQL.")
    if reports:
        latest = reports[0]
        print(f"   Latest Report #{latest['id']} ({latest['symbol']}): {latest['decision']} [{latest['market_regime']}] - {latest['scanned_at_ist']}")

if __name__ == "__main__":
    main()

