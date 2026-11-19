import React, { useState, useEffect, useCallback } from "react";
import {
  Brain,
  Zap,
  Sliders,
  AlertTriangle,
  Clock,
  ShieldCheck,
  CheckCircle,
  XCircle,
  BookOpen,
  RefreshCw,
  Target,
  Compass,
  TrendingUp,
  TrendingDown,
  Crosshair,
  ArrowUpRight,
  ArrowDownRight,
  Send,
  Trash2,
  Database,
  Layers,
  Check,
  Code,
  Eye,
  Filter,
  Columns,
  Activity,
  Percent,
  Play,
  X,
} from "lucide-react";
import { fmtPct, fmtConfidence, safeArr, safeStr } from "../../utils/format";
import { PairSchedule } from "../../hooks/useLiveStore";
import { api } from "../../services/api";
import { useToast } from "../Toast";

interface AIBrainTabProps {
  selectedSymbol: string;
  pairSchedules: Record<string, PairSchedule>;
}

interface CacheStatus {
  health_badge: string;
  is_purge_due: boolean;
  auto_daily_enabled: boolean;
  daily_purge_hour_utc: number;
  daily_purge_minute_utc: number;
  last_cleared_at_ist: string;
  next_scheduled_at_ist: string;
  seconds_until_next_purge: number;
  cached_entries_count: number;
  estimated_size_kb: number;
  last_purge_summary: any;
}

interface ScannerConfig {
  global_scan_interval_sec: number;
  scalp_planning_tf: string;
  scalp_execution_tf: string;
  swing_planning_tf: string;
  swing_execution_tf: string;
  pairs: Array<{
    symbol: string;
    asset_class: string;
    enabled: boolean;
    scalp_enabled: boolean;
    swing_enabled: boolean;
    scan_interval_sec: number;
    max_spread_points: number;
  }>;
}

const ALL_INSTRUMENTS = [
  { symbol: "EURUSD#", asset_class: "FOREX", name: "EUR/USD" },
  { symbol: "USDJPY#", asset_class: "FOREX", name: "USD/JPY" },
  { symbol: "GBPUSD#", asset_class: "FOREX", name: "GBP/USD" },
  { symbol: "USDCAD#", asset_class: "FOREX", name: "USD/CAD" },
  { symbol: "AUDUSD#", asset_class: "FOREX", name: "AUD/USD" },
  { symbol: "GBPJPY#", asset_class: "FOREX", name: "GBP/JPY" },
  { symbol: "GOLD#", asset_class: "COMMODITIES", name: "Spot Gold" },
  { symbol: "SILVER#", asset_class: "COMMODITIES", name: "Spot Silver" },
  { symbol: "OILCash#", asset_class: "COMMODITIES", name: "WTI Crude Oil" },
  { symbol: "BRENTCash#", asset_class: "COMMODITIES", name: "Brent Crude Oil" },
  { symbol: "BTCUSD#", asset_class: "CRYPTO", name: "Bitcoin 24/7" },
  { symbol: "ETHUSD#", asset_class: "CRYPTO", name: "Ethereum 24/7" },
  { symbol: "SOLUSD#", asset_class: "CRYPTO", name: "Solana 24/7" },
  { symbol: "XRPUSD#", asset_class: "CRYPTO", name: "Ripple 24/7" },
];

export const AIBrainTab: React.FC<AIBrainTabProps> = ({
  selectedSymbol,
  pairSchedules,
}) => {
  const [reports, setReports] = useState<any[]>([]);
  const [newsData, setNewsData] = useState<any>({ events: [], blackout_check: null });
  const [learnedRules, setLearnedRules] = useState<any[]>([]);
  const [patternMemory, setPatternMemory] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [ruleActionLoading, setRuleActionLoading] = useState<number | null>(null);

  // Radar Setups & Segmentation
  const [upcomingData, setUpcomingData] = useState<any>({
    actionable_setups: [],
    watchlist_radar: [],
    scalp_setups: [],
    swing_setups: [],
  });
  const [radarSubView, setRadarSubView] = useState<"ALL" | "SCALP" | "SWING" | "ACTIONABLE">("ALL");
  const [splitView, setSplitView] = useState<boolean>(false);

  // Asset Class Filter
  const [assetClassFilter, setAssetClassFilter] = useState<"ALL" | "FOREX" | "COMMODITIES" | "CRYPTO">("ALL");

  // Cache Hygiene State
  const [cacheStatus, setCacheStatus] = useState<CacheStatus | null>(null);
  const [cacheClearing, setCacheClearing] = useState(false);

  // Scanner & Timeframe Planning Config
  const [scannerConfig, setScannerConfig] = useState<ScannerConfig>({
    global_scan_interval_sec: 300,
    scalp_planning_tf: "M15",
    scalp_execution_tf: "M5",
    swing_planning_tf: "H4",
    swing_execution_tf: "H1",
    pairs: [],
  });
  const [selectedInterval, setSelectedInterval] = useState<number>(300);
  const [isSavingConfig, setIsSavingConfig] = useState(false);

  // Institutional Prompt Preview Modal
  const [promptModalOpen, setPromptModalOpen] = useState(false);
  const [promptPreviewText, setPromptPreviewText] = useState<string>("");
  const [promptLoading, setPromptLoading] = useState(false);

  const toast = useToast();

  const handleSendTelegramAlert = async (item: any) => {
    try {
      await api.telegram.testMessage();
      toast.success("Alert Sent", `Dispatched setup alert for ${item.symbol} to Telegram.`);
    } catch (e: any) {
      toast.error("Alert Failed", e.message || String(e));
    }
  };

  const fetchCacheStatus = useCallback(async () => {
    try {
      const res = await api.ai.getCacheStatus();
      if (res) setCacheStatus(res);
    } catch (e) {
      console.debug("Failed to fetch cache status:", e);
    }
  }, []);

  const fetchScannerConfig = useCallback(async () => {
    try {
      const res = await api.ai.getScannerConfig();
      if (res) {
        setScannerConfig(res);
        if (res.global_scan_interval_sec) {
          setSelectedInterval(res.global_scan_interval_sec);
        }
      }
    } catch (e) {
      console.debug("Failed to fetch scanner config:", e);
    }
  }, []);

  const fetchBrainData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [repData, newsPayload, rulesData, upcomingPayload, patternsPayload] = await Promise.all([
        api.ai.getReports({ limit: 25 }),
        api.ai.getNews(selectedSymbol),
        api.ai.getRules(),
        api.ai.getUpcomingSetups(),
        api.ai.getPatternMemory(),
      ]);

      setReports(safeArr(repData));
      setNewsData(newsPayload || { events: [], blackout_check: null });
      setLearnedRules(safeArr(rulesData));
      setUpcomingData(upcomingPayload || { actionable_setups: [], watchlist_radar: [] });
      setPatternMemory(safeArr(patternsPayload));
      await Promise.all([fetchCacheStatus(), fetchScannerConfig()]);
    } catch (e: any) {
      console.error("Failed to fetch AI supervisor data:", e);
    } finally {
      setIsLoading(false);
    }
  }, [selectedSymbol, fetchCacheStatus, fetchScannerConfig]);

  useEffect(() => {
    fetchBrainData();

    // 3-second live radar refresh for distance points and price updates
    const radarTimer = window.setInterval(async () => {
      try {
        const up = await api.ai.getUpcomingSetups();
        if (up) setUpcomingData(up);
      } catch (e) {
        // silent
      }
    }, 3000);

    return () => clearInterval(radarTimer);
  }, [fetchBrainData]);

  const handleScanSpecificPair = async (sym: string) => {
    setIsScanning(true);
    try {
      const res = await api.ai.scanPair(sym);
      toast.success("Scan Complete", res.message || `${sym} scanned by Gemini Supervisor.`);
      await fetchBrainData();
    } catch (e: any) {
      toast.error("Pair Scan Failed", e.message || String(e));
    } finally {
      setIsScanning(false);
    }
  };

  const handleScanAll = async () => {
    setIsScanning(true);
    try {
      const res = await api.ai.scanAll();
      toast.success("All Pairs Scanned", res.message || "Cross-pair supervisory scan completed.");
      await fetchBrainData();
    } catch (e: any) {
      toast.error("Scan All Failed", e.message || String(e));
    } finally {
      setIsScanning(false);
    }
  };

  // Cache Hygiene Actions
  const handleClearCacheNow = async () => {
    setCacheClearing(true);
    try {
      const res = await api.ai.clearCache(true);
      toast.success("Cache Cleared", res.message || "All in-memory buffers purged successfully.");
      await fetchCacheStatus();
    } catch (e: any) {
      toast.error("Cache Clear Failed", e.message || String(e));
    } finally {
      setCacheClearing(false);
    }
  };

  const handleToggleAutoDailyCache = async () => {
    if (!cacheStatus) return;
    try {
      const newEnabled = !cacheStatus.auto_daily_enabled;
      await api.ai.updateCacheConfig({ auto_daily_enabled: newEnabled });
      setCacheStatus({ ...cacheStatus, auto_daily_enabled: newEnabled });
      toast.success(
        "Cache Policy Updated",
        `Automated daily cache purge is now ${newEnabled ? "ENABLED (00:05 UTC)" : "DISABLED"}.`
      );
    } catch (e: any) {
      toast.error("Update Failed", e.message || String(e));
    }
  };

  // Scanner & Timeframe Actions
  const handleSaveScannerConfig = async () => {
    setIsSavingConfig(true);
    try {
      await api.ai.updateScannerConfig({
        global_scan_interval_sec: selectedInterval,
        scalp_planning_tf: scannerConfig.scalp_planning_tf,
        scalp_execution_tf: scannerConfig.scalp_execution_tf,
        swing_planning_tf: scannerConfig.swing_planning_tf,
        swing_execution_tf: scannerConfig.swing_execution_tf,
      });
      toast.success("Configuration Hot-Reloaded", `Scan cadence set to ${selectedInterval}s without server restart.`);
      await fetchScannerConfig();
    } catch (e: any) {
      toast.error("Config Save Failed", e.message || String(e));
    } finally {
      setIsSavingConfig(false);
    }
  };

  const handleTogglePairScanner = async (sym: string) => {
    try {
      const res = await api.ai.togglePair(sym);
      toast.success("Pair Updated", res.message || `Toggled ${sym}`);
      await fetchScannerConfig();
    } catch (e: any) {
      toast.error("Toggle Failed", e.message || String(e));
    }
  };

  const handleOpenPromptPreview = async (sym: string = selectedSymbol) => {
    setPromptLoading(true);
    setPromptModalOpen(true);
    try {
      const res = await api.ai.getPromptPreview(sym || "GOLD#");
      setPromptPreviewText(res.rendered_prompt || res.prompt_template || "");
    } catch (e: any) {
      setPromptPreviewText(`Failed to load prompt preview: ${e.message || String(e)}`);
    } finally {
      setPromptLoading(false);
    }
  };

  const handleUpdateRuleStatus = async (ruleId: number, status: string) => {
    setRuleActionLoading(ruleId);
    try {
      await api.ai.updateRuleStatus(ruleId, status);
      toast.success("Rule Updated", `Rule #${ruleId} status changed to ${status}.`);
      await fetchBrainData();
    } catch (e: any) {
      toast.error("Rule Update Failed", e.message || String(e));
    } finally {
      setRuleActionLoading(null);
    }
  };

  const isBlackout = newsData?.blackout_check?.is_blackout;

  // Filter watchlist items by asset class
  const filteredWatchlist = (upcomingData?.watchlist_radar || []).filter((item: any) => {
    if (assetClassFilter === "ALL") return true;
    return item.asset_class?.toUpperCase() === assetClassFilter;
  });

  const scalpSetups = filteredWatchlist.filter(
    (item: any) => (item.trade_style || item.setup_mode) === "SCALP"
  );
  const swingSetups = filteredWatchlist.filter(
    (item: any) => (item.trade_style || item.setup_mode) === "SWING"
  );

  // Compute countdown ring to next scan
  const currentSched = pairSchedules[selectedSymbol] || Object.values(pairSchedules)[0];
  const secsRemaining = currentSched?.seconds_remaining ?? selectedInterval;
  const progressPct = Math.min(
    100,
    Math.max(0, 100 - (secsRemaining / Math.max(1, selectedInterval)) * 100)
  );

  return (
    <div className="space-y-4">
      {/* 1. TOP BANNER: TIER-1 MACRO NEWS & QUICK SCAN TRIGGERS */}
      <div
        className={`p-3.5 rounded-xl border flex flex-wrap items-center justify-between gap-3 text-xs transition ${
          isBlackout
            ? "bg-red-950/40 border-red-500/60 text-red-200"
            : "bg-[#121824] border-slate-800 text-slate-300"
        }`}
      >
        <div className="flex items-center gap-3">
          <div
            className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold ${
              isBlackout ? "bg-red-900/60 text-red-300" : "bg-blue-900/40 text-blue-400"
            }`}
          >
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <div className="font-bold flex items-center gap-2">
              <span>TIER-1 MACRO NEWS BLACKOUT GUARD</span>
              {isBlackout ? (
                <span className="bg-red-600 text-white font-black px-2 py-0.5 rounded text-[10px] animate-pulse">
                  BLACKOUT ACTIVE (±15m BLACKOUT)
                </span>
              ) : (
                <span className="bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded text-[10px] font-bold">
                  PASS - ENTRIES ALLOWED
                </span>
              )}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              {newsData?.blackout_check?.reason ||
                "No Tier-1 news releases (CPI, Core PCE, NFP, FOMC) within ±15m window."}
            </div>
          </div>
        </div>

        {/* Global Quick Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => handleOpenPromptPreview(selectedSymbol)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-purple-300 font-bold rounded-lg text-xs border border-purple-900/40 shadow transition"
            title="Inspect Institutional 5-Gate Gemini System Prompt"
          >
            <Code className="w-3.5 h-3.5 text-purple-400" />
            <span>5-Gate Prompt</span>
          </button>
          <button
            disabled={isScanning}
            onClick={() => handleScanSpecificPair(selectedSymbol)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white font-bold rounded-lg text-xs shadow transition disabled:opacity-50"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>Scan {selectedSymbol}</span>
          </button>
          <button
            disabled={isScanning}
            onClick={handleScanAll}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold rounded-lg text-xs border border-slate-700 transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? "animate-spin" : ""}`} />
            <span>Scan All Universe</span>
          </button>
        </div>
      </div>

      {/* 2. TASK 1: MULTI-ASSET HIGH-LIQUIDITY UNIVERSE & ASSET CLASS FILTER */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-3.5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-cyan-400" />
            <span className="font-bold text-white text-xs uppercase tracking-wider">
              Asset Class Filters & MT5 Symbol Universe (14 Pairs)
            </span>
          </div>

          {/* Filter Pills */}
          <div className="flex items-center gap-1.5 bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs">
            {(["ALL", "FOREX", "COMMODITIES", "CRYPTO"] as const).map((ac) => {
              const count =
                ac === "ALL"
                  ? ALL_INSTRUMENTS.length
                  : ALL_INSTRUMENTS.filter((i) => i.asset_class === ac).length;
              return (
                <button
                  key={ac}
                  onClick={() => setAssetClassFilter(ac)}
                  className={`px-3 py-1 rounded font-bold text-xs transition ${
                    assetClassFilter === ac
                      ? "bg-blue-600 text-white shadow"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  {ac} ({count})
                </button>
              );
            })}
          </div>
        </div>

        {/* Symbol Quick Chips with Weekend Indicators */}
        <div className="flex flex-wrap gap-2 pt-1">
          {ALL_INSTRUMENTS.filter(
            (i) => assetClassFilter === "ALL" || i.asset_class === assetClassFilter
          ).map((item) => {
            const isSelected = selectedSymbol === item.symbol;
            const isCrypto = item.asset_class === "CRYPTO";
            const pairCfg = scannerConfig.pairs.find((p) => p.symbol === item.symbol);
            const isEnabled = pairCfg ? pairCfg.enabled : true;

            return (
              <div
                key={item.symbol}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-mono transition ${
                  isSelected
                    ? "bg-blue-950/80 border-blue-500 text-blue-200"
                    : isEnabled
                    ? "bg-slate-950 border-slate-800 text-slate-300 hover:border-slate-700"
                    : "bg-slate-950/40 border-slate-900 text-slate-600"
                }`}
              >
                <button
                  onClick={() => handleScanSpecificPair(item.symbol)}
                  className="font-bold flex items-center gap-1 hover:text-amber-400"
                  title={`Click to trigger manual scan for ${item.symbol}`}
                >
                  <span>{item.symbol}</span>
                </button>
                <span
                  className={`text-[9px] px-1 py-0.2 rounded font-black ${
                    isCrypto
                      ? "bg-orange-950 text-orange-400 border border-orange-800/60"
                      : "bg-slate-900 text-slate-400"
                  }`}
                >
                  {isCrypto ? "24/7" : item.asset_class.slice(0, 3)}
                </span>
                <button
                  onClick={() => handleTogglePairScanner(item.symbol)}
                  className={`text-[10px] ml-1 font-bold ${
                    isEnabled ? "text-emerald-400 hover:text-emerald-300" : "text-slate-600 hover:text-slate-400"
                  }`}
                  title={isEnabled ? "Active - click to pause scanner" : "Paused - click to enable scanner"}
                >
                  {isEnabled ? "●" : "○"}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* 3. TASK 2: SYSTEM HYGIENE & DAILY CACHE CONTROL PANEL */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Database className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-white text-sm tracking-wide">
                  SYSTEM HYGIENE & DAILY CACHE ENGINE
                </h3>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    cacheStatus?.health_badge === "Healthy"
                      ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                      : "bg-amber-950 text-amber-400 border border-amber-800 animate-pulse"
                  }`}
                >
                  {cacheStatus?.health_badge || "Healthy"}
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Automated daily flush at 00:05 UTC. In-memory DFs, expired pre-trigger radar TTLs (&gt;2h Scalp, &gt;24h Swing), and payload buffers. Never touches closed trades or learned rules.
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs">
              <span className="text-slate-400 font-semibold">Auto-Daily:</span>
              <button
                onClick={handleToggleAutoDailyCache}
                className={`font-black text-xs px-2 py-0.5 rounded transition ${
                  cacheStatus?.auto_daily_enabled
                    ? "bg-emerald-900/60 text-emerald-300 border border-emerald-700"
                    : "bg-slate-800 text-slate-400"
                }`}
              >
                {cacheStatus?.auto_daily_enabled ? "ON (00:05 UTC)" : "OFF"}
              </button>
            </div>

            <button
              disabled={cacheClearing}
              onClick={handleClearCacheNow}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-950/60 hover:bg-red-900/80 text-red-300 border border-red-800/80 font-bold rounded-lg text-xs shadow transition disabled:opacity-50"
            >
              <Trash2 className={`w-3.5 h-3.5 ${cacheClearing ? "animate-spin" : ""}`} />
              <span>Clear Cache Now</span>
            </button>
          </div>
        </div>

        {/* Cache Telemetry Metrics Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-3">
          <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-2.5">
            <div className="text-[10px] text-slate-500 font-mono">Last Cleared</div>
            <div className="text-xs font-bold text-white mt-0.5">
              {cacheStatus?.last_cleared_at_ist || "Never"}
            </div>
          </div>
          <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-2.5">
            <div className="text-[10px] text-slate-500 font-mono">Next Auto-Purge</div>
            <div className="text-xs font-bold text-cyan-400 mt-0.5">
              {cacheStatus?.next_scheduled_at_ist || "00:05 UTC"}
            </div>
          </div>
          <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-2.5">
            <div className="text-[10px] text-slate-500 font-mono">Cached In-Memory Objects</div>
            <div className="text-xs font-bold text-amber-400 mt-0.5">
              {cacheStatus?.cached_entries_count ?? 0} Objects (~{cacheStatus?.estimated_size_kb ?? 0} KB)
            </div>
          </div>
          <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-2.5">
            <div className="text-[10px] text-slate-500 font-mono">Last Purge Summary</div>
            <div className="text-xs font-bold text-emerald-400 mt-0.5 truncate" title={cacheStatus?.last_purge_summary?.reason}>
              {cacheStatus?.last_purge_summary?.items_cleared ?? 0} purged ({cacheStatus?.last_purge_summary?.reason || "Active"})
            </div>
          </div>
        </div>
      </div>

      {/* 4. TASK 3: UPCOMING TRADES & PRE-TRIGGER SETUPS RADAR (SCALP VS SWING) */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-4 space-y-4">
        {/* Header & Segmented Tabs */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <Target className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-white text-sm tracking-wide">
                  UPCOMING TRADES & PRE-TRIGGER SETUPS RADAR
                </h3>
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  AUTO ROUTED
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Institutional setups forecasted by Gemini with live tick proximity tracking, TTL expiry guards, and spread drag impact.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Desktop Side-by-Side Split View Toggle */}
            <button
              onClick={() => setSplitView(!splitView)}
              className={`hidden md:flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold border transition ${
                splitView
                  ? "bg-purple-900/40 border-purple-500/60 text-purple-200"
                  : "bg-slate-950 border-slate-800 text-slate-400 hover:text-white"
              }`}
            >
              <Columns className="w-3.5 h-3.5" />
              <span>{splitView ? "↔ Side-by-Side Split" : "Single Tab View"}</span>
            </button>

            {/* Segmented Tab Bar */}
            <div className="flex items-center gap-1 bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs">
              <button
                onClick={() => setRadarSubView("ALL")}
                className={`px-3 py-1 rounded font-bold transition ${
                  radarSubView === "ALL"
                    ? "bg-amber-500/20 text-amber-300"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                All Radar ({filteredWatchlist.length})
              </button>
              <button
                onClick={() => setRadarSubView("SCALP")}
                className={`px-3 py-1 rounded font-bold transition flex items-center gap-1 ${
                  radarSubView === "SCALP"
                    ? "bg-cyan-500/20 text-cyan-300"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                <Zap className="w-3 h-3 text-cyan-400" />
                <span>Scalp ({scalpSetups.length})</span>
              </button>
              <button
                onClick={() => setRadarSubView("SWING")}
                className={`px-3 py-1 rounded font-bold transition flex items-center gap-1 ${
                  radarSubView === "SWING"
                    ? "bg-indigo-500/20 text-indigo-300"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                <Compass className="w-3 h-3 text-indigo-400" />
                <span>Swing ({swingSetups.length})</span>
              </button>
              <button
                onClick={() => setRadarSubView("ACTIONABLE")}
                className={`px-3 py-1 rounded font-bold transition ${
                  radarSubView === "ACTIONABLE"
                    ? "bg-emerald-500/20 text-emerald-300"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Limits ({upcomingData?.actionable_setups?.length || 0})
              </button>
            </div>
          </div>
        </div>

        {/* Section A: Actionable Limits */}
        {(radarSubView === "ALL" || radarSubView === "ACTIONABLE") && (
          <div className="space-y-2.5">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-emerald-400 flex items-center gap-1.5">
                <Crosshair className="w-4 h-4" />
                <span>Actionable Setups Ready for Execution ({upcomingData?.actionable_setups?.length || 0})</span>
              </span>
              <span className="text-[11px] text-slate-500 font-mono">Autonomous MT5 Market & Pending Limit Routing</span>
            </div>

            {upcomingData?.actionable_setups && upcomingData.actionable_setups.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {upcomingData.actionable_setups.map((setup: any) => {
                  const isBuy = setup.direction === "BUY";
                  return (
                    <div
                      key={setup.id}
                      className="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 space-y-3 hover:border-slate-700 transition"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white text-sm font-mono">{setup.symbol}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              isBuy
                                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                : "bg-red-500/20 text-red-300 border border-red-500/30"
                            }`}
                          >
                            {setup.direction} {setup.mode}
                          </span>
                          <span className="text-slate-400 text-xs font-mono">{setup.lots} Lots</span>
                        </div>

                        {/* Live Distance Pill */}
                        <div
                          className={`px-2 py-0.5 rounded text-[10px] font-bold flex items-center gap-1 font-mono ${
                            setup.in_trigger_zone
                              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse"
                              : "bg-slate-800 text-slate-300"
                          }`}
                        >
                          {setup.in_trigger_zone ? (
                            <span>🎯 IN TRIGGER ZONE</span>
                          ) : (
                            <span>{Math.abs(setup.distance_points)} pts away</span>
                          )}
                        </div>
                      </div>

                      {/* Coordinates Grid */}
                      <div className="grid grid-cols-5 gap-1.5 bg-slate-900/60 p-2 rounded-lg font-mono text-[11px]">
                        <div>
                          <div className="text-[10px] text-slate-500">Entry</div>
                          <div className="text-white font-bold">{setup.entry_price}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-500">Stop Loss</div>
                          <div className="text-red-400">{setup.sl}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-500">TP1 (+1.5R)</div>
                          <div className="text-emerald-400">{setup.tp1}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-500">TP2 (+3R)</div>
                          <div className="text-emerald-300 font-bold">{setup.tp2}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-500">R:R</div>
                          <div className="text-cyan-400 font-bold">{setup.rr_ratio}R</div>
                        </div>
                      </div>

                      {/* Proximity Progress Bar */}
                      <div>
                        <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                          <span>Proximity to Trigger</span>
                          <span className="font-bold text-emerald-400">{setup.proximity_pct ?? 90}%</span>
                        </div>
                        <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
                          <div
                            style={{ width: `${setup.proximity_pct ?? 90}%` }}
                            className="bg-emerald-500 h-full rounded-full transition-all"
                          />
                        </div>
                      </div>

                      <p className="text-[11px] text-slate-400 line-clamp-2 italic">
                        "{setup.thesis || "Algorithmic setup confirmed by Gemini Supervisor."}"
                      </p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-3 bg-slate-950/40 border border-slate-800/60 rounded-lg text-slate-500 text-xs text-center font-mono">
                No active limit orders currently pending execution.
              </div>
            )}
          </div>
        )}

        {/* Section B: Developing Radar Cards (Segmented or Side-by-Side Split) */}
        {radarSubView !== "ACTIONABLE" && (
          <div className="space-y-4 pt-2">
            {splitView ? (
              /* Desktop Side-by-Side View */
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Scalp Column */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-xs font-bold text-cyan-400 border-b border-slate-800 pb-1.5">
                    <span className="flex items-center gap-1.5">
                      <Zap className="w-4 h-4 text-cyan-400" />
                      <span>⚡ Intraday Scalp Setups ({scalpSetups.length})</span>
                    </span>
                    <span className="text-[10px] text-slate-500">TTL: &lt; 2h</span>
                  </div>
                  {scalpSetups.length === 0 ? (
                    <div className="text-slate-500 text-xs py-6 text-center bg-slate-950/40 rounded-lg">
                      No developing scalp setups detected.
                    </div>
                  ) : (
                    scalpSetups.map((item: any, idx: number) => renderRadarCard(item, idx, "SCALP"))
                  )}
                </div>

                {/* Swing Column */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-xs font-bold text-indigo-400 border-b border-slate-800 pb-1.5">
                    <span className="flex items-center gap-1.5">
                      <Compass className="w-4 h-4 text-indigo-400" />
                      <span>🌊 Structural Swing Setups ({swingSetups.length})</span>
                    </span>
                    <span className="text-[10px] text-slate-500">TTL: &lt; 24h</span>
                  </div>
                  {swingSetups.length === 0 ? (
                    <div className="text-slate-500 text-xs py-6 text-center bg-slate-950/40 rounded-lg">
                      No developing swing setups detected.
                    </div>
                  ) : (
                    swingSetups.map((item: any, idx: number) => renderRadarCard(item, idx, "SWING"))
                  )}
                </div>
              </div>
            ) : (
              /* Single Tab Filter View */
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {filteredWatchlist
                  .filter((item: any) => {
                    if (radarSubView === "SCALP") return (item.trade_style || item.setup_mode) === "SCALP";
                    if (radarSubView === "SWING") return (item.trade_style || item.setup_mode) === "SWING";
                    return true;
                  })
                  .map((item: any, idx: number) =>
                    renderRadarCard(item, idx, (item.trade_style || item.setup_mode) === "SWING" ? "SWING" : "SCALP")
                  )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 5. TASK 4: DYNAMIC AI SCANNING INTERVAL & TIMEFRAME PLANNING CONTROLS */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3 mb-4">
          <div className="flex items-center gap-2.5">
            <Sliders className="w-5 h-5 text-blue-400" />
            <div>
              <h3 className="font-bold text-white text-sm">
                DYNAMIC AI SCANNING INTERVAL & TIMEFRAME MATRIX
              </h3>
              <p className="text-xs text-slate-400">
                Hot-reloads scanning interval & multi-timeframe planning rules into scheduler without server restarts.
              </p>
            </div>
          </div>

          <button
            disabled={isSavingConfig}
            onClick={handleSaveScannerConfig}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg text-xs shadow transition disabled:opacity-50"
          >
            <Check className="w-3.5 h-3.5" />
            <span>Apply Changes</span>
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          {/* Column A: Scan Cadence Quick Pills */}
          <div className="space-y-2 bg-slate-950 p-3 rounded-xl border border-slate-800/80">
            <div className="flex items-center justify-between text-slate-300 font-bold">
              <span>Scan Cadence</span>
              <span className="text-cyan-400 font-mono">{selectedInterval}s ({Math.round(selectedInterval / 60)}m)</span>
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              {[
                { label: "1m", sec: 60 },
                { label: "3m", sec: 180 },
                { label: "5m", sec: 300 },
                { label: "15m", sec: 900 },
                { label: "30m", sec: 1800 },
                { label: "1h", sec: 3600 },
              ].map((pill) => (
                <button
                  key={pill.sec}
                  onClick={() => setSelectedInterval(pill.sec)}
                  className={`py-1.5 rounded-lg font-bold font-mono text-xs transition ${
                    selectedInterval === pill.sec
                      ? "bg-blue-600 text-white shadow"
                      : "bg-slate-900 text-slate-400 hover:text-white"
                  }`}
                >
                  {pill.label}
                </button>
              ))}
            </div>

            {/* Countdown Progress Ring Bar */}
            <div className="pt-2">
              <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                <span>Cycle Progress ({selectedSymbol})</span>
                <span className="font-mono text-amber-400 font-bold">{secsRemaining}s remaining</span>
              </div>
              <div className="w-full bg-slate-900 rounded-full h-2 overflow-hidden border border-slate-800">
                <div
                  style={{ width: `${progressPct}%` }}
                  className="bg-cyan-500 h-full rounded-full transition-all duration-1000"
                />
              </div>
            </div>
          </div>

          {/* Column B: Scalp Timeframe Matrix */}
          <div className="space-y-2.5 bg-slate-950 p-3 rounded-xl border border-slate-800/80">
            <div className="font-bold text-cyan-400 flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5" />
              <span>Scalp Timeframe Matrix</span>
            </div>
            <div className="space-y-2">
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Planning / Structural Bias TF</label>
                <select
                  value={scannerConfig.scalp_planning_tf}
                  onChange={(e) =>
                    setScannerConfig({ ...scannerConfig, scalp_planning_tf: e.target.value })
                  }
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                >
                  <option value="M15">M15 (Default Scalp Bias)</option>
                  <option value="H1">H1 (Higher Intraday Confluence)</option>
                  <option value="M30">M30</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Execution Trigger TF</label>
                <select
                  value={scannerConfig.scalp_execution_tf}
                  onChange={(e) =>
                    setScannerConfig({ ...scannerConfig, scalp_execution_tf: e.target.value })
                  }
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                >
                  <option value="M5">M5 (Default Fast Scalp Trigger)</option>
                  <option value="M1">M1 (Micro Structure Sweep)</option>
                  <option value="M15">M15 (Conservative Trigger)</option>
                </select>
              </div>
            </div>
          </div>

          {/* Column C: Swing Timeframe Matrix */}
          <div className="space-y-2.5 bg-slate-950 p-3 rounded-xl border border-slate-800/80">
            <div className="font-bold text-indigo-400 flex items-center gap-1.5">
              <Compass className="w-3.5 h-3.5" />
              <span>Swing Timeframe Matrix</span>
            </div>
            <div className="space-y-2">
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Planning / Structural Bias TF</label>
                <select
                  value={scannerConfig.swing_planning_tf}
                  onChange={(e) =>
                    setScannerConfig({ ...scannerConfig, swing_planning_tf: e.target.value })
                  }
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                >
                  <option value="H4">H4 (Default Swing Bias)</option>
                  <option value="D1">D1 (Macro Structure)</option>
                  <option value="H1">H1</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 block mb-1">Execution Trigger TF</label>
                <select
                  value={scannerConfig.swing_execution_tf}
                  onChange={(e) =>
                    setScannerConfig({ ...scannerConfig, swing_execution_tf: e.target.value })
                  }
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                >
                  <option value="H1">H1 (Default Swing Trigger)</option>
                  <option value="M30">M30 (Earlier Retest Entry)</option>
                  <option value="H4">H4 (Full Candle Close)</option>
                </select>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 6. RULES VAULT & AI SUPERVISORY ANALYSIS FEED */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column: Self-Learned Rules Vault (5 cols) */}
        <div className="lg:col-span-5 bg-[#121824] border border-slate-800 rounded-xl p-4">
          <div className="font-bold text-white text-xs flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-emerald-400" />
              <span>SELF-LEARNED RULES VAULT ({learnedRules.length})</span>
            </div>
            <span className="text-[10px] text-slate-400 font-mono">Immune System</span>
          </div>

          <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
            {learnedRules.length === 0 ? (
              <div className="text-slate-500 text-xs py-6 text-center">
                No self-learned rules created yet.
              </div>
            ) : (
              learnedRules.map((r) => {
                const isLive = r.status === "LIVE";
                return (
                  <div
                    key={r.id}
                    className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-bold text-slate-200">{r.rule_code}</span>
                      <span
                        className={`text-[9px] px-1.5 py-0.2 rounded font-black ${
                          isLive
                            ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                            : "bg-amber-950 text-amber-400 border border-amber-800"
                        }`}
                      >
                        {r.status}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400 mt-1">
                      Symbol: <strong className="text-white">{r.symbol}</strong> | Mode:{" "}
                      <strong className="text-white">{r.mode}</strong> | Expectancy:{" "}
                      <strong className="text-emerald-400">+{r.backtest_net_improvement_pct}%</strong>
                    </div>

                    <div className="bg-slate-950/90 rounded p-2 mt-1.5 border border-slate-800/80 text-[10px] grid grid-cols-2 gap-1.5 font-mono">
                      <div>
                        <span className="text-slate-500">PF: </span>
                        <span className="text-amber-400 font-bold">{r.profit_factor_before ?? 1.0}</span>
                        <span className="text-slate-600"> → </span>
                        <span className="text-emerald-400 font-bold">{r.profit_factor_after ?? 1.5}</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Net R: </span>
                        <span className="text-cyan-400 font-bold">+{r.net_r_delta ?? 0.0}R</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Winners: </span>
                        <span className="text-slate-200 font-bold">{r.winners_preserved_pct ?? 100}% kept</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Avoided: </span>
                        <span className="text-emerald-400 font-bold">${r.avoided_losses_usd ?? 0.0}</span>
                      </div>
                    </div>

                    <div className="flex justify-end gap-1.5 mt-2">
                      {isLive ? (
                        <button
                          disabled={ruleActionLoading === r.id}
                          onClick={() => handleUpdateRuleStatus(r.id, "RETIRED")}
                          className="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] rounded"
                        >
                          Retire
                        </button>
                      ) : (
                        <button
                          disabled={ruleActionLoading === r.id}
                          onClick={() => handleUpdateRuleStatus(r.id, "LIVE")}
                          className="px-2 py-0.5 bg-emerald-600 hover:bg-emerald-500 text-white text-[10px] font-bold rounded"
                        >
                          Promote LIVE
                        </button>
                      )}
                      <button
                        disabled={ruleActionLoading === r.id}
                        onClick={() => handleUpdateRuleStatus(r.id, "LOCKED")}
                        className="px-2 py-0.5 bg-blue-900 hover:bg-blue-800 text-blue-200 text-[10px] rounded"
                      >
                        Lock
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: AI Supervisory Analysis Cards (7 cols) */}
        <div className="lg:col-span-7 bg-[#121824] border border-slate-800 rounded-xl p-4 flex flex-col">
          <div className="font-bold text-white text-xs flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
            <div className="flex items-center gap-2">
              <Brain className="w-4 h-4 text-purple-400" />
              <span>GEMINI SUPERVISORY ANALYSIS FEED</span>
            </div>
            <span className="text-[10px] text-slate-400 font-mono">Official google-genai SDK</span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-3 max-h-[380px] pr-1">
            {reports.length === 0 ? (
              <div className="text-slate-500 text-xs py-8 text-center">
                No supervisory reports logged yet.
              </div>
            ) : (
              reports.map((rep) => {
                const isBuy = rep.decision?.includes("BUY") || rep.decision?.includes("SCALP") || rep.decision?.includes("SWING");
                return (
                  <div
                    key={rep.id}
                    className="p-3 rounded-xl bg-slate-900/90 border border-slate-800 text-xs space-y-2"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-sm font-mono">{rep.symbol}</span>
                        <span
                          className={`font-black px-2 py-0.5 rounded text-[10px] ${
                            rep.decision?.startsWith("EXECUTE")
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                              : rep.decision === "WAIT"
                              ? "bg-slate-800 text-slate-300 border border-slate-700"
                              : "bg-red-950 text-red-400 border border-red-800"
                          }`}
                        >
                          {rep.decision}
                        </span>
                        <span className="text-[11px] text-slate-400">
                          Regime: <strong className="text-white">{rep.market_regime}</strong>
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-[10px] text-slate-400">{rep.scanned_at_ist}</span>
                        <div className="text-[11px] font-bold text-blue-400">
                          Confidence: {fmtConfidence(rep.confidence)}
                        </div>
                      </div>
                    </div>

                    {rep.entry_price && rep.stop_loss ? (
                      <div className="bg-[#0A0E17] border border-blue-900/40 rounded-lg p-2.5 flex flex-wrap items-center justify-between gap-2 font-mono text-[11px]">
                        <div className="flex flex-wrap items-center gap-3">
                          <span className="text-slate-400">Entry: <strong className="text-white">{rep.entry_price}</strong></span>
                          <span className="text-red-400">SL: <strong className="text-red-300">{rep.stop_loss}</strong></span>
                          <span className="text-emerald-400">TP1 (+1.5R): <strong className="text-emerald-300">{rep.tp1 ?? "-"}</strong></span>
                          {rep.tp2 && <span className="text-emerald-500">TP2: <strong className="text-emerald-400">{rep.tp2}</strong></span>}
                        </div>
                      </div>
                    ) : null}

                    {rep.thesis_text && (
                      <p className="text-slate-300 text-xs leading-relaxed bg-[#0B0E14] p-2.5 rounded-lg border border-slate-800/80">
                        {rep.thesis_text}
                      </p>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* 7. PER-PAIR PATTERN WIN/LOSS MEMORY SCORECARD */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-4 space-y-3">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-purple-400" />
            <div>
              <h3 className="font-bold text-white text-sm">PER-PAIR PATTERN WIN/LOSS MEMORY</h3>
              <p className="text-[11px] text-slate-400">
                Self-learning closed-loop pattern telemetry. Patterns with ≥60% win rate qualify as PROVEN_EDGE; degraded setups isolated as BLOCKED_TRAP.
              </p>
            </div>
          </div>
          <button
            onClick={fetchBrainData}
            className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg"
          >
            Refresh Memory
          </button>
        </div>

        {patternMemory.length === 0 ? (
          <div className="text-slate-500 text-xs py-6 text-center">
            No pattern memory records loaded yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/80 text-[10px] text-slate-400 uppercase font-mono border-b border-slate-800">
                <tr>
                  <th className="py-2 px-3">Symbol</th>
                  <th className="py-2 px-3">Pattern Signature</th>
                  <th className="py-2 px-3">Mode</th>
                  <th className="py-2 px-3">Trades (W/L)</th>
                  <th className="py-2 px-3">Win Rate</th>
                  <th className="py-2 px-3">Avg R:R</th>
                  <th className="py-2 px-3">Net PnL</th>
                  <th className="py-2 px-3">Edge Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                {patternMemory.map((p) => {
                  const isEdge = p.status === "PROVEN_EDGE";
                  const isTrap = p.status === "BLOCKED_TRAP";
                  return (
                    <tr key={p.id} className="hover:bg-slate-900/40 transition">
                      <td className="py-2.5 px-3 font-bold text-white font-sans">{p.symbol}</td>
                      <td className="py-2.5 px-3 text-cyan-300 font-bold">{p.pattern_signature}</td>
                      <td className="py-2.5 px-3 text-slate-400">{p.mode}</td>
                      <td className="py-2.5 px-3 text-slate-200">
                        {p.wins}W / {p.losses}L ({p.total_trades})
                      </td>
                      <td
                        className={`py-2.5 px-3 font-bold ${
                          p.win_rate_pct >= 60.0
                            ? "text-emerald-400"
                            : p.win_rate_pct <= 35.0
                            ? "text-red-400"
                            : "text-amber-300"
                        }`}
                      >
                        {fmtPct(p.win_rate_pct)}
                      </td>
                      <td className="py-2.5 px-3 text-blue-300 font-bold">
                        {p.avg_r_multiple > 0 ? `+${p.avg_r_multiple}R` : `${p.avg_r_multiple}R`}
                      </td>
                      <td
                        className={`py-2.5 px-3 font-bold ${
                          p.net_pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"
                        }`}
                      >
                        {p.net_pnl_usd >= 0 ? `+$${p.net_pnl_usd.toFixed(2)}` : `-$${Math.abs(p.net_pnl_usd).toFixed(2)}`}
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            isEdge
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                              : isTrap
                              ? "bg-red-950 text-red-400 border border-red-800 animate-pulse"
                              : "bg-blue-950 text-blue-400 border border-blue-800"
                          }`}
                        >
                          {p.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 8. MODAL: 5-GATE INSTITUTIONAL PROMPT PREVIEW */}
      {promptModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-[#0f172a] border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Code className="w-5 h-5 text-purple-400" />
                <h3 className="font-bold text-white text-sm">
                  Institutional 5-Gate Gemini Supervisory System Prompt
                </h3>
              </div>
              <button
                onClick={() => setPromptModalOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 flex-1 overflow-y-auto font-mono text-xs text-slate-300 leading-relaxed bg-[#0b0f19]">
              {promptLoading ? (
                <div className="py-12 text-center text-slate-400">Loading prompt preview...</div>
              ) : (
                <pre className="whitespace-pre-wrap">{promptPreviewText}</pre>
              )}
            </div>
            <div className="p-3 border-t border-slate-800 flex justify-end">
              <button
                onClick={() => setPromptModalOpen(false)}
                className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-white font-bold rounded-lg text-xs"
              >
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // Helper function to render a Scalp or Swing Radar Card
  function renderRadarCard(item: any, idx: number, cardType: "SCALP" | "SWING") {
    const isBull = item.watch_bias === "BULLISH_WATCH";
    const isScalp = cardType === "SCALP";

    return (
      <div
        key={`${item.symbol}-${idx}`}
        className={`bg-slate-950 rounded-xl p-3.5 space-y-2.5 transition border ${
          isScalp
            ? "border-cyan-900/40 hover:border-cyan-600/60"
            : "border-indigo-900/40 hover:border-indigo-600/60"
        }`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-bold text-white text-sm font-mono">{item.symbol}</span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold flex items-center gap-1 ${
                isBull
                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                  : "bg-red-500/10 text-red-400 border border-red-500/20"
              }`}
            >
              {isBull ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
              <span>{item.watch_bias}</span>
            </span>
            <span
              className={`text-[9px] px-1.5 py-0.2 rounded font-black ${
                isScalp
                  ? "bg-cyan-950 text-cyan-300 border border-cyan-800"
                  : "bg-indigo-950 text-indigo-300 border border-indigo-800"
              }`}
            >
              {isScalp ? "⚡ SCALP" : "🌊 SWING"}
            </span>
          </div>

          {/* Proximity / Status Tag */}
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono ${
              item.status === "TRIGGER_READY"
                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse"
                : item.status === "APPROACHING"
                ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                : "bg-slate-800 text-slate-400"
            }`}
          >
            {item.status === "TRIGGER_READY"
              ? "🎯 TRIGGER READY"
              : item.status === "APPROACHING"
              ? `⚡ ${Math.abs(item.distance_points)} pts away`
              : `⏳ ${Math.abs(item.distance_points)} pts away`}
          </span>
        </div>

        {/* Dynamic Context Header (Scalp TTL + Spread Impact VS Swing HTF + Multi-Day R:R) */}
        <div className="flex items-center justify-between text-[10px] font-mono px-2 py-1 bg-slate-900/60 rounded">
          {isScalp ? (
            <>
              <span className="text-cyan-400">
                TF: {item.planning_tf || "M15"} → {item.execution_tf || "M5"}
              </span>
              <span className="text-amber-400">
                Spread drag: {item.spread_impact_pct ?? "4.2"}% of SL
              </span>
            </>
          ) : (
            <>
              <span className="text-indigo-400">
                TF: {item.planning_tf || "H4"} → {item.execution_tf || "H1"}
              </span>
              <span className="text-emerald-400 font-bold">
                Target: +{item.projected_rr ?? "3.0"}R Structure
              </span>
            </>
          )}
        </div>

        {/* Trigger Zone & Planned Coordinates */}
        <div className="bg-slate-900/80 p-2.5 rounded-lg border border-slate-800/80 font-mono text-[11px] space-y-1.5">
          <div className="flex justify-between text-slate-400">
            <span>Trigger Zone:</span>
            <span className="text-amber-400 font-bold">
              {item.trigger_zone_low} - {item.trigger_zone_high}
            </span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>Planned Entry:</span>
            <span className="text-white font-bold">{item.planned_entry}</span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>SL / TP2:</span>
            <span>
              <span className="text-red-400">{item.planned_sl}</span>
              <span className="text-slate-600 mx-1">/</span>
              <span className="text-emerald-400 font-bold">{item.planned_tp2}</span>
            </span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>Risk / Reward:</span>
            <span className="text-cyan-400 font-bold">{item.rr_ratio}R</span>
          </div>
        </div>

        {/* Visual Proximity Progress Bar */}
        <div>
          <div className="flex justify-between text-[10px] text-slate-400 mb-1">
            <span>Proximity to Trigger</span>
            <span className="font-bold text-white">{item.proximity_pct ?? 70}%</span>
          </div>
          <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
            <div
              style={{ width: `${item.proximity_pct ?? 70}%` }}
              className={`h-full rounded-full transition-all ${
                (item.proximity_pct ?? 70) >= 85
                  ? "bg-emerald-500"
                  : (item.proximity_pct ?? 70) >= 60
                  ? "bg-cyan-500"
                  : "bg-amber-500"
              }`}
            />
          </div>
        </div>

        {/* Condition & Expiration Window */}
        <div className="text-[11px] text-slate-300 space-y-0.5">
          <div className="text-slate-400 font-semibold text-[10px]">Trigger Condition:</div>
          <div className="text-[11px] text-slate-300 line-clamp-2">
            {item.trigger_condition || "Waiting for key support/resistance sweep"}
          </div>
          <div className="text-[10px] text-slate-500 mt-1 flex justify-between font-mono">
            <span>Window: {item.expected_window || "Next 1-2 hours"}</span>
            {item.invalidation_price > 0 && (
              <span>Cancel: {item.invalidation_price}</span>
            )}
          </div>
        </div>

        {/* Action Button */}
        <div className="flex gap-2 pt-1 border-t border-slate-800/60">
          <button
            onClick={() => handleSendTelegramAlert(item)}
            className="px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 rounded-lg text-xs font-semibold border border-slate-800 transition flex items-center gap-1.5"
            title="Broadcast setup alert to configured Telegram channel"
          >
            <Send className="w-3.5 h-3.5 text-blue-400" />
            <span>Alert</span>
          </button>
          <div className="flex-1 py-1.5 bg-emerald-950/40 border border-emerald-800/40 text-emerald-300 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 font-mono">
            <Target className="w-3.5 h-3.5 text-emerald-400" />
            <span>AUTO Execution Monitored</span>
          </div>
        </div>
      </div>
    );
  }
};
