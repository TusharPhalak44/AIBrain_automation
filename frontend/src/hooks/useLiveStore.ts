import { useState, useEffect, useCallback, useRef } from "react";
import { safeArr } from "../utils/format";
import { api } from "../services/api";

export interface OpenPosition {
  ticket: number;
  symbol: string;
  magic: number;
  type: number; // 0 = BUY, 1 = SELL
  volume: number;
  price_open: number;
  sl: number;
  tp: number;
  price_current: number;
  profit: number;
  comment?: string;
}

export interface PlannedTrade {
  id: number;
  symbol: string;
  mode: string;
  direction: string;
  lots: number;
  entry_price: number;
  sl: number;
  tp1: number;
  tp2: number;
  ai_analysis_summary?: string;
  opened_at_ist?: string;
}

export interface PendingOrder {
  ticket: number;
  symbol: string;
  type: number;
  type_desc: string;
  volume: number;
  price_open: number;
  sl: number;
  tp: number;
  magic: number;
  comment: string;
}

export interface PairSchedule {
  interval_sec: number;
  last_scan_ist?: string;
  last_decision?: string;
  status: string;
  next_scan_seconds?: number;
}

export interface QuoteData {
  symbol: string;
  bid: number;
  ask: number;
  spread_points: number;
  time: number;
  next_scan_sec?: number;
  ea_heartbeat_ok?: boolean;
}

export function useLiveStore() {
  const [isWsConnected, setIsWsConnected] = useState(false);
  const [accountType, setAccountType] = useState<string>("DEMO");
  const [executionMode, setExecutionMode] = useState<string>("AUTO");
  const [isMt5Connected, setIsMt5Connected] = useState(false);
  const [dbHealthy, setDbHealthy] = useState(true);

  const [balance, setBalance] = useState(0.0);
  const [equity, setEquity] = useState(0.0);
  const [marginUsagePct, setMarginUsagePct] = useState(0.0);
  const [dailyDdPct, setDailyDdPct] = useState(0.0);
  const [weeklyDdPct, setWeeklyDdPct] = useState(0.0);
  const [riskState, setRiskState] = useState("NORMAL");
  const [floatingPnl, setFloatingPnl] = useState(0.0);
  const [todayClosedNetPnl, setTodayClosedNetPnl] = useState(0.0);

  const [openPositions, setOpenPositions] = useState<OpenPosition[]>([]);
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([]);
  const [plannedTrades, setPlannedTrades] = useState<PlannedTrade[]>([]);
  const [pairSchedules, setPairSchedules] = useState<Record<string, PairSchedule>>({});
  const [quotes, setQuotes] = useState<Record<string, QuoteData>>({});

  const [selectedSymbol, setSelectedSymbol] = useState("GOLD#");
  const [selectedTimeframe, setSelectedTimeframe] = useState("M15");

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  const applyLiveState = useCallback((data: any) => {
    if (!data) return;
    if (data.account_type) setAccountType(data.account_type);
    if (data.execution_mode) setExecutionMode(data.execution_mode);
    setIsMt5Connected(Boolean(data.is_connected || data.mt5_connected));
    setDbHealthy(Boolean(data.db_healthy));
    if (typeof data.balance === "number") setBalance(data.balance);
    if (typeof data.equity === "number") setEquity(data.equity);
    if (typeof data.margin_usage_pct === "number") setMarginUsagePct(data.margin_usage_pct);
    if (typeof data.daily_dd_pct === "number") setDailyDdPct(data.daily_dd_pct);
    if (typeof data.weekly_dd_pct === "number") setWeeklyDdPct(data.weekly_dd_pct);
    if (data.risk_state) setRiskState(data.risk_state);
    if (typeof data.floating_pnl === "number") setFloatingPnl(data.floating_pnl);
    if (typeof data.today_closed_net_pnl === "number") setTodayClosedNetPnl(data.today_closed_net_pnl);
    if (data.open_positions) setOpenPositions(safeArr(data.open_positions));
    if (data.pending_orders) setPendingOrders(safeArr(data.pending_orders));
    if (data.planned_trades) setPlannedTrades(safeArr(data.planned_trades));
    if (data.pair_schedules) setPairSchedules(data.pair_schedules);
    if (data.quotes && typeof data.quotes === "object") setQuotes(data.quotes);
  }, []);

  // Immediate REST snapshot fetch
  const fetchLiveSnapshot = useCallback(async () => {
    try {
      const state = await api.accounts.getLiveState();
      applyLiveState(state);
    } catch {
      // Ignore background fetch error
    }
  }, [applyLiveState]);

  const connectWs = useCallback(() => {
    try {
      const explicitWs = (import.meta.env.VITE_WS_URL || "").trim().replace(/\/+$/, "");
      let url: string;
      if (explicitWs) {
        url = `${explicitWs}/ws/live`;
      } else {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        // Connect through Vite proxy /ws to eliminate CORS / cross-origin issues
        url = `${protocol}//${window.location.host}/ws/live`;
      }

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsWsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "LIVE_TICK") {
            applyLiveState(data);
          }
        } catch (e) {
          console.error("Error parsing WS telemetry:", e);
        }
      };

      ws.onclose = () => {
        setIsWsConnected(false);
        reconnectTimeoutRef.current = window.setTimeout(() => {
          connectWs();
        }, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (e) {
      console.error("Failed to establish live WebSocket:", e);
    }
  }, [applyLiveState]);

  useEffect(() => {
    fetchLiveSnapshot();
    connectWs();

    // 2.5-second polling fallback in case WS takes time or drops
    const pollInterval = window.setInterval(() => {
      fetchLiveSnapshot();
    }, 2500);

    return () => {
      clearInterval(pollInterval);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connectWs, fetchLiveSnapshot]);

  // Actions routed through centralized api client
  const panicFlatten = async () => {
    return api.trades.panicFlatten();
  };

  const switchAccount = async (newType: string) => {
    const data = await api.accounts.switch(newType);
    setAccountType(newType);
    return data;
  };

  const switchMode = async (newMode: string) => {
    const data = await api.settings.update({ execution_mode: newMode });
    setExecutionMode(newMode);
    return data;
  };

  const approveCopilot = async (tradeId: number) => {
    return api.ai.approveCopilot(tradeId);
  };

  const rejectCopilot = async (tradeId: number) => {
    return api.ai.rejectCopilot(tradeId);
  };

  return {
    isWsConnected,
    isMt5Connected,
    dbHealthy,
    accountType,
    executionMode,
    balance,
    equity,
    marginUsagePct,
    dailyDdPct,
    weeklyDdPct,
    riskState,
    floatingPnl,
    todayClosedNetPnl,
    openPositions,
    pendingOrders,
    plannedTrades,
    pairSchedules,
    quotes,
    selectedSymbol,
    selectedTimeframe,
    setSelectedSymbol,
    setSelectedTimeframe,
    panicFlatten,
    switchAccount,
    switchMode,
    approveCopilot,
    rejectCopilot,
  };
}

