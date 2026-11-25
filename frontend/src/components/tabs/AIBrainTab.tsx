import React, { useState, useEffect, useCallback, useMemo } from "react";
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
  EyeOff,
  Bell,
  Save,
  Filter,
  Columns,
  Activity,
  Percent,
  Play,
  X,
  FileCode,
  Sparkles,
  Copy,
  CheckCircle2,
} from "lucide-react";
import { fmtPct, fmtConfidence, safeArr, safeStr, fmtUsd } from "../../utils/format";
import { PairSchedule } from "../../hooks/useLiveStore";
import { INSTRUMENTS, getInstrument, isMarketOpen, formatSymbolPrice } from "../../constants/instruments";
import { api } from "../../services/api";
import { useToast } from "../Toast";
import { StrategyLabTab } from "./StrategyLabTab";

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
  pairs: string[];
}

type BrainSubTab = "RADAR" | "RULES" | "STRATEGY" | "HYGIENE";

export const AIBrainTab: React.FC<AIBrainTabProps> = ({
  selectedSymbol,
  pairSchedules,
}) => {
  // Primary 4 Sub-Tabs State
  const [activeSubTab, setActiveSubTab] = useState<BrainSubTab>("RADAR");

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

  // Asset Class & Rules Filters
  const [assetClassFilter, setAssetClassFilter] = useState<"ALL" | "FOREX" | "COMMODITIES" | "CRYPTO">("ALL");
  const [rulesSymbolFilter, setRulesSymbolFilter] = useState<string>("");
  const [rulesClassFilter, setRulesClassFilter] = useState<"ALL" | "FOREX" | "COMMODITIES" | "CRYPTO">("ALL");
  const [rulesStatusFilter, setRulesStatusFilter] = useState<string>("ALL");

  // Cache Hygiene State
  const [cacheStatus, setCacheStatus] = useState<CacheStatus | null>(null);
  const [cacheClearing, setCacheClearing] = useState(false);

  // Telegram Alert Center State
  const [telegramConfig, setTelegramConfig] = useState<{
    enabled: boolean;
    bot_token_masked: string;
    bot_username: string;
    admin_chat_id: string;
    thread_id: string;
    notify_pre_trigger: boolean;
    notify_executions: boolean;
    notify_be_and_partials: boolean;
    notify_closures: boolean;
    notify_system_alerts: boolean;
    silent_pre_trigger: boolean;
    is_configured: boolean;
  }>({
    enabled: true,
    bot_token_masked: "",
    bot_username: "",
    admin_chat_id: "",
    thread_id: "",
    notify_pre_trigger: true,
    notify_executions: true,
    notify_be_and_partials: true,
    notify_closures: true,
    notify_system_alerts: true,
    silent_pre_trigger: true,
    is_configured: false,
  });
  const [telegramLoading, setTelegramLoading] = useState(false);
  const [telegramSaving, setTelegramSaving] = useState(false);
  const [showTokenInput, setShowTokenInput] = useState(false);
  const [newTokenInput, setNewTokenInput] = useState("");
  const [chatIdInput, setChatIdInput] = useState("");
  const [threadIdInput, setThreadIdInput] = useState("");
  const [testTemplate, setTestTemplate] = useState("EXECUTION");
  const [testSymbol, setTestSymbol] = useState("GOLD#");
  const [testSending, setTestSending] = useState(false);

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

  // Institutional Prompt Preview Modal / Inspector
  const [promptModalOpen, setPromptModalOpen] = useState(false);
  const [promptPreviewText, setPromptPreviewText] = useState<string>("");
  const [promptLoading, setPromptLoading] = useState(false);
  const [copiedPrompt, setCopiedPrompt] = useState(false);

  const toast = useToast();

  const fetchTelegramConfig = useCallback(async () => {
    try {
      setTelegramLoading(true);
      const res = await api.telegram.getConfig();
      if (res) {
        setTelegramConfig(res);
        setChatIdInput(res.admin_chat_id || "");
        setThreadIdInput(res.thread_id || "");
      }
    } catch (e) {
      console.debug("Failed to fetch Telegram config:", e);
    } finally {
      setTelegramLoading(false);
    }
  }, []);

  const handleSaveTelegramConfig = async () => {
    setTelegramSaving(true);
    try {
      const payload: any = {
        enabled: telegramConfig.enabled,
        admin_chat_id: chatIdInput.trim(),
        thread_id: threadIdInput.trim() || null,
        notify_pre_trigger: telegramConfig.notify_pre_trigger,
        notify_executions: telegramConfig.notify_executions,
        notify_be_and_partials: telegramConfig.notify_be_and_partials,
        notify_closures: telegramConfig.notify_closures,
        notify_system_alerts: telegramConfig.notify_system_alerts,
        silent_pre_trigger: telegramConfig.silent_pre_trigger,
      };
      if (newTokenInput.trim()) {
        payload.bot_token = newTokenInput.trim();
      }
      const updated = await api.telegram.updateConfig(payload);
      setTelegramConfig(updated);
      setNewTokenInput("");
      setShowTokenInput(false);
      toast.success("Telegram Settings Saved", "Alert channels and notifications updated.");
    } catch (e: any) {
      toast.error("Save Failed", e.message || String(e));
    } finally {
      setTelegramSaving(false);
    }
  };

  const handleSendTestPreview = async () => {
    setTestSending(true);
    try {
      const res = await api.telegram.sendTestPreview({
        template_type: testTemplate,
        symbol: testSymbol,
        chat_id: chatIdInput.trim() || undefined,
      });
      toast.success("Telegram Test Sent", res.message || `Dispatched ${testTemplate} alert preview.`);
    } catch (e: any) {
      toast.error("Test Failed", e.message || String(e));
    } finally {
      setTestSending(false);
    }
  };

  const handleSendTelegramAlert = async (item: any) => {
    try {
      await api.telegram.sendTestPreview({
        template_type: "SETUP",
        symbol: item.symbol,
      });
      toast.success("Radar Alert Sent", `Dispatched setup alert for ${item.symbol} to Telegram.`);
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
      const rawRules = Array.isArray(rulesData) ? rulesData : (rulesData as any)?.rules || [];
      setLearnedRules(safeArr(rawRules));
      setUpcomingData(upcomingPayload || { actionable_setups: [], watchlist_radar: [] });
      setPatternMemory(safeArr(patternsPayload));
      await Promise.all([fetchCacheStatus(), fetchScannerConfig(), fetchTelegramConfig()]);
    } catch (e: any) {
      console.error("Failed to fetch AI supervisor data:", e);
    } finally {
      setIsLoading(false);
    }
  }, [selectedSymbol, fetchCacheStatus, fetchScannerConfig, fetchTelegramConfig]);

  useEffect(() => {
    fetchBrainData();

    // 4-second live radar refresh for distance points and price updates
    const radarTimer = window.setInterval(async () => {
      try {
        const up = await api.ai.getUpcomingSetups();
        if (up) setUpcomingData(up);
      } catch (e) {
        // silent background polling
      }
    }, 4000);

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
      toast.success(
        "Scanner Configuration Saved",
        `Cadence set to ${selectedInterval}s. Timeframes persisted.`
      );
    } catch (e: any) {
      toast.error("Save Failed", e.message || String(e));
    } finally {
      setIsSavingConfig(false);
    }
  };

  const handleOpenPromptModal = async () => {
    setPromptModalOpen(true);
    if (!promptPreviewText) {
      setPromptLoading(true);
      try {
        const res = await api.ai.getPromptPreview();
        setPromptPreviewText(res?.system_prompt || "No prompt preview available.");
      } catch (e: any) {
        setPromptPreviewText("Failed to load prompt preview: " + (e.message || String(e)));
      } finally {
        setPromptLoading(false);
      }
    }
  };

  const handleCopyPrompt = () => {
    if (promptPreviewText) {
      navigator.clipboard.writeText(promptPreviewText);
      setCopiedPrompt(true);
      setTimeout(() => setCopiedPrompt(false), 2000);
      toast.info("Prompt Copied", "5-Gate System Prompt copied to clipboard.");
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

  const actionableLimits = upcomingData?.actionable_setups || [];
  const liveRulesCount = useMemo(() => {
    return learnedRules.filter((r) => r.status === "LIVE").length;
  }, [learnedRules]);

  return (
    <div className="space-y-4 font-sans max-w-7xl mx-auto pb-10">
      {/* =========================================================================
          TIER 1: SUB-NAVIGATION TABS (4 FOCUSED WORKSPACES WITH LIVE COUNT BADGES)
          ========================================================================= */}
      <div className="bg-[#0b101b] border border-slate-800/80 rounded-2xl p-1.5 flex flex-wrap items-center justify-between gap-2 shadow-lg">
        <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-none">
          {/* Sub-Tab A: Radar & Scanner */}
          <button
            onClick={() => setActiveSubTab("RADAR")}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-mono font-bold transition ${
              activeSubTab === "RADAR"
                ? "bg-cyan-500 text-slate-950 shadow-[0_0_12px_rgba(6,182,212,0.3)]"
                : "text-slate-400 hover:text-white hover:bg-slate-800/50"
            }`}
          >
            <Compass className="w-4 h-4" />
            <span>LIVE RADAR & SCANNER</span>
            <span
              className={`px-1.5 py-0.2 rounded text-[10px] font-mono ${
                activeSubTab === "RADAR"
                  ? "bg-slate-950 text-cyan-300 font-black"
                  : "bg-slate-800 text-slate-300"
              }`}
            >
              {upcomingData?.watchlist_radar?.length || 0}
            </span>
          </button>

          {/* Sub-Tab B: Rules Vault */}
          <button
            onClick={() => setActiveSubTab("RULES")}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-mono font-bold transition ${
              activeSubTab === "RULES"
                ? "bg-cyan-500 text-slate-950 shadow-[0_0_12px_rgba(6,182,212,0.3)]"
                : "text-slate-400 hover:text-white hover:bg-slate-800/50"
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>RULES VAULT</span>
            <span
              className={`px-1.5 py-0.2 rounded text-[10px] font-mono ${
                activeSubTab === "RULES"
                  ? "bg-slate-950 text-emerald-400 font-black"
                  : "bg-emerald-950/60 text-emerald-300 border border-emerald-800/40"
              }`}
            >
              {liveRulesCount} LIVE
            </span>
          </button>

          {/* Sub-Tab C: Strategy Lab & Prompt Studio */}
          <button
            onClick={() => setActiveSubTab("STRATEGY")}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-mono font-bold transition ${
              activeSubTab === "STRATEGY"
                ? "bg-cyan-500 text-slate-950 shadow-[0_0_12px_rgba(6,182,212,0.3)]"
                : "text-slate-400 hover:text-white hover:bg-slate-800/50"
            }`}
          >
            <FileCode className="w-4 h-4" />
            <span>STRATEGY LAB & PROMPT STUDIO</span>
            <span
              className={`px-1.5 py-0.2 rounded text-[10px] font-mono ${
                activeSubTab === "STRATEGY"
                  ? "bg-slate-950 text-purple-300 font-black"
                  : "bg-purple-950/60 text-purple-300 border border-purple-800/40"
              }`}
            >
              5-GATE AI
            </span>
          </button>

          {/* Sub-Tab D: System Hygiene & Telegram */}
          <button
            onClick={() => setActiveSubTab("HYGIENE")}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-mono font-bold transition ${
              activeSubTab === "HYGIENE"
                ? "bg-cyan-500 text-slate-950 shadow-[0_0_12px_rgba(6,182,212,0.3)]"
                : "text-slate-400 hover:text-white hover:bg-slate-800/50"
            }`}
          >
            <Bell className="w-4 h-4" />
            <span>SYSTEM HYGIENE & TELEGRAM</span>
            <span
              className={`px-1.5 py-0.2 rounded text-[10px] font-mono ${
                activeSubTab === "HYGIENE"
                  ? "bg-slate-950 text-blue-300 font-black"
                  : "bg-blue-950/60 text-blue-300 border border-blue-800/40"
              }`}
            >
              TELEMETRY
            </span>
          </button>
        </div>

        {/* Global Quick Action: Scan All Triggers */}
        <div className="flex items-center gap-2 px-2">
          <button
            disabled={isScanning}
            onClick={handleScanAll}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 active:bg-cyan-700 text-slate-950 font-mono font-bold text-xs rounded-xl shadow-md transition disabled:opacity-50"
          >
            <Zap className={`w-3.5 h-3.5 ${isScanning ? "animate-spin" : ""}`} />
            <span>{isScanning ? "Scanning 14 Pairs..." : "Scan All Pairs"}</span>
          </button>
        </div>
      </div>

      {/* =========================================================================
          SUB-TAB A: LIVE RADAR & ACTIVE SCANNER
          ========================================================================= */}
      {activeSubTab === "RADAR" && (
        <div className="space-y-4">
          {/* Top Banner: Tier-1 Macro News & Quick Scan Triggers */}
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2">
                <Brain className="w-5 h-5 text-cyan-400" />
                <h3 className="font-bold text-white text-sm tracking-wide font-mono">
                  GEMINI SUPERVISORY RADAR: {selectedSymbol}
                </h3>
                {isBlackout ? (
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse font-mono">
                    HIGH-IMPACT NEWS BLACKOUT ACTIVE
                  </span>
                ) : (
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-mono">
                    AUTONOMOUS RADAR READY
                  </span>
                )}
              </div>

              {/* Quick Scan Triggers */}
              <div className="flex items-center gap-2">
                <button
                  disabled={isScanning}
                  onClick={() => handleScanSpecificPair(selectedSymbol)}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-mono font-semibold rounded-lg border border-slate-700 transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isScanning ? "animate-spin" : ""}`} />
                  <span>Scan {selectedSymbol}</span>
                </button>
              </div>
            </div>

            {/* Macro Releases Horizon */}
            <div className="mt-3 flex flex-wrap items-center justify-between text-xs text-slate-400 gap-2 font-mono">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-slate-500" />
                <span>Next Release Horizon:</span>
                {newsData?.events?.length > 0 ? (
                  <span className="text-slate-200 font-semibold">
                    {newsData.events[0].title} ({newsData.events[0].currency}) - {newsData.events[0].impact} Impact
                  </span>
                ) : (
                  <span className="text-slate-500">No high-impact releases within ±30 min window.</span>
                )}
              </div>
              <div className="text-[11px] text-slate-500">
                14-Pair Packet Cadence: <strong className="text-cyan-400">{selectedInterval}s</strong>
              </div>
            </div>
          </div>

          {/* 14-Pair Universe Chips */}
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-3 shadow-md space-y-2">
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2 font-mono text-slate-400">
                <Target className="w-4 h-4 text-cyan-400" />
                <span className="font-bold text-white">14-PAIR UNIVERSE:</span>
              </div>

              {/* Asset Class Filter Pills */}
              <div className="flex items-center gap-1">
                {(["ALL", "FOREX", "COMMODITIES", "CRYPTO"] as const).map((cls) => (
                  <button
                    key={cls}
                    onClick={() => setAssetClassFilter(cls)}
                    className={`text-[10px] px-2.5 py-0.5 rounded-lg font-mono font-semibold transition ${
                      assetClassFilter === cls
                        ? "bg-cyan-500 text-slate-950 font-bold"
                        : "bg-slate-900 text-slate-400 hover:text-white"
                    }`}
                  >
                    {cls}
                  </button>
                ))}
              </div>
            </div>

            {/* Symbol Chips */}
            <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-none py-1">
              {INSTRUMENTS.map((inst) => {
                const isSelected = selectedSymbol === inst.symbol;
                const openState = isMarketOpen(inst.symbol);

                return (
                  <button
                    key={inst.symbol}
                    onClick={() => handleScanSpecificPair(inst.symbol)}
                    className={`px-2.5 py-1 rounded-xl text-xs font-mono font-bold whitespace-nowrap transition flex items-center gap-1.5 ${
                      isSelected
                        ? "bg-cyan-500 text-slate-950 shadow-md"
                        : "bg-slate-900/90 text-slate-300 hover:bg-slate-800 border border-slate-800"
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        openState ? "bg-emerald-400" : "bg-slate-500"
                      }`}
                    />
                    <span>{inst.symbol}</span>
                    {inst.is24_7 && (
                      <span className="text-[8px] px-1 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-800">
                        24/7
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Developing Radar Cards (Scalp vs Swing) */}
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2">
                <Compass className="w-5 h-5 text-cyan-400" />
                <h3 className="font-bold text-white text-sm tracking-wide font-mono">
                  PRE-TRIGGER RADAR SETUPS (SCALP VS SWING)
                </h3>
              </div>

              <div className="flex items-center gap-2">
                {/* Segmented Sub-View */}
                <div className="flex bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-[10px] font-mono">
                  {(["ALL", "SCALP", "SWING", "ACTIONABLE"] as const).map((view) => (
                    <button
                      key={view}
                      onClick={() => setRadarSubView(view)}
                      className={`px-2.5 py-1 rounded-md font-bold transition ${
                        radarSubView === view
                          ? "bg-cyan-500 text-slate-950"
                          : "text-slate-400 hover:text-white"
                      }`}
                    >
                      {view === "ALL"
                        ? `All (${filteredWatchlist.length})`
                        : view === "SCALP"
                        ? `⚡ Scalp (${scalpSetups.length})`
                        : view === "SWING"
                        ? `🌊 Swing (${swingSetups.length})`
                        : `Actionable (${actionableLimits.length})`}
                    </button>
                  ))}
                </div>

                {/* Split View Toggle */}
                <button
                  onClick={() => setSplitView((v) => !v)}
                  className={`hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono font-semibold border transition ${
                    splitView
                      ? "bg-cyan-950 text-cyan-300 border-cyan-800"
                      : "bg-slate-900 text-slate-400 border-slate-800 hover:text-white"
                  }`}
                >
                  <Columns className="w-3.5 h-3.5" />
                  <span>{splitView ? "Side-by-Side" : "Stacked"}</span>
                </button>
              </div>
            </div>

            {/* Actionable Limits Section (if any) */}
            {actionableLimits.length > 0 && (radarSubView === "ALL" || radarSubView === "ACTIONABLE") && (
              <div className="space-y-2">
                <div className="text-xs font-bold text-amber-400 font-mono uppercase tracking-wider flex items-center gap-1.5">
                  <AlertTriangle className="w-4 h-4" />
                  <span>Actionable Limit Approvals ({actionableLimits.length})</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {actionableLimits.map((item: any, idx: number) => {
                    const isBuy = item.direction === "BUY";
                    const entryVal = item.planned_entry ?? item.entry_price;
                    const slVal = item.planned_sl ?? item.sl;
                    const tp2Val = item.planned_tp2 ?? item.tp2;
                    return (
                      <div
                        key={item.id || idx}
                        className="p-3 bg-amber-950/20 border border-amber-500/40 rounded-xl space-y-2 font-mono text-xs"
                      >
                        <div className="flex justify-between items-center gap-2">
                          <div className="flex items-center gap-1.5">
                            <span className="font-bold text-white">{item.symbol}</span>
                            {item.direction && (
                              <span
                                className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                                  isBuy
                                    ? "bg-emerald-950 text-emerald-300 border border-emerald-700/60"
                                    : "bg-rose-950 text-rose-300 border border-rose-700/60"
                                }`}
                              >
                                {item.direction}
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-amber-300 font-bold px-1.5 py-0.5 rounded bg-amber-900/40">
                            {item.setup_mode || item.mode || "SCALP"}
                          </span>
                        </div>

                        <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-2 space-y-1 text-[11px]">
                          <div className="flex justify-between">
                            <span className="text-slate-500">Trigger Zone:</span>
                            <span className="text-amber-300 font-bold">
                              {item.trigger_zone_low != null && item.trigger_zone_high != null
                                ? `${formatSymbolPrice(item.symbol, item.trigger_zone_low)} - ${formatSymbolPrice(item.symbol, item.trigger_zone_high)}`
                                : entryVal != null
                                ? formatSymbolPrice(item.symbol, entryVal)
                                : "-"}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500">Planned Entry:</span>
                            <span className="text-white font-bold">
                              {entryVal != null ? formatSymbolPrice(item.symbol, entryVal) : "-"}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500">SL / TP2:</span>
                            <span>
                              <span className="text-rose-400">
                                {slVal != null ? formatSymbolPrice(item.symbol, slVal) : "-"}
                              </span>
                              <span className="text-slate-600 mx-1">/</span>
                              <span className="text-emerald-400">
                                {tp2Val != null ? formatSymbolPrice(item.symbol, tp2Val) : "-"}
                              </span>
                            </span>
                          </div>
                        </div>

                        <div className="text-[11px] text-slate-400 flex justify-between items-center">
                          <span>Distance: {Math.abs(item.distance_points ?? 0)} pts</span>
                          {item.lots && <span className="text-slate-300">{item.lots} lots</span>}
                          <span className="text-emerald-400 font-bold">RR: {item.rr_ratio}R</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Developing Radar Cards Grid */}
            {filteredWatchlist.length === 0 ? (
              <div className="py-12 text-center text-slate-500 font-mono text-xs">
                No active setups currently developing. Next packet evaluation scheduled in {selectedInterval}s.
              </div>
            ) : splitView ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Scalp Column */}
                <div className="space-y-3">
                  <div className="text-xs font-bold font-mono text-cyan-400 uppercase tracking-wider flex items-center gap-1.5 pb-1 border-b border-cyan-900/40">
                    <Zap className="w-4 h-4" />
                    <span>⚡ SCALP RADAR ({scalpSetups.length})</span>
                  </div>
                  {scalpSetups.length === 0 ? (
                    <div className="py-8 text-center text-slate-600 font-mono text-xs">
                      No scalping setups on radar.
                    </div>
                  ) : (
                    scalpSetups.map((item: any, idx: number) => renderRadarCard(item, idx, "SCALP"))
                  )}
                </div>

                {/* Swing Column */}
                <div className="space-y-3">
                  <div className="text-xs font-bold font-mono text-indigo-400 uppercase tracking-wider flex items-center gap-1.5 pb-1 border-b border-indigo-900/40">
                    <Compass className="w-4 h-4" />
                    <span>🌊 SWING RADAR ({swingSetups.length})</span>
                  </div>
                  {swingSetups.length === 0 ? (
                    <div className="py-8 text-center text-slate-600 font-mono text-xs">
                      No swing setups on radar.
                    </div>
                  ) : (
                    swingSetups.map((item: any, idx: number) => renderRadarCard(item, idx, "SWING"))
                  )}
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {filteredWatchlist
                  .filter((item: any) => {
                    if (radarSubView === "SCALP") return (item.trade_style || item.setup_mode) === "SCALP";
                    if (radarSubView === "SWING") return (item.trade_style || item.setup_mode) === "SWING";
                    return true;
                  })
                  .map((item: any, idx: number) =>
                    renderRadarCard(
                      item,
                      idx,
                      (item.trade_style || item.setup_mode) === "SWING" ? "SWING" : "SCALP"
                    )
                  )}
              </div>
            )}
          </div>

          {/* Scanner Cadence & Timeframe Configuration Bar */}
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <Clock className="w-5 h-5 text-cyan-400" />
              <div>
                <div className="font-bold text-white text-xs font-mono">AUTONOMOUS SCANNER CADENCE</div>
                <div className="text-[10px] text-slate-400">Select multi-pair packet polling interval</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {[30, 60, 120, 300, 900, 1800].map((sec) => (
                <button
                  key={sec}
                  onClick={() => setSelectedInterval(sec)}
                  className={`px-3 py-1 rounded-lg text-xs font-mono font-bold transition ${
                    selectedInterval === sec
                      ? "bg-cyan-500 text-slate-950 shadow-md"
                      : "bg-slate-900 text-slate-400 hover:text-white border border-slate-800"
                  }`}
                >
                  {sec < 60 ? `${sec}s` : `${sec / 60}m`}
                </button>
              ))}

              <button
                onClick={handleSaveScannerConfig}
                disabled={isSavingConfig}
                className="ml-2 px-3.5 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold font-mono text-xs rounded-xl shadow-md transition disabled:opacity-50"
              >
                {isSavingConfig ? "Saving..." : "Save Cadence"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          SUB-TAB B: SELF-LEARNED RULES VAULT & FORENSICS
          ========================================================================= */}
      {activeSubTab === "RULES" && (
        <div className="space-y-4">
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl space-y-4">
            {/* Header & Filter Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <BookOpen className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white font-mono flex items-center gap-2">
                    <span>SELF-LEARNED RULES VAULT ({learnedRules.length} Total · {liveRulesCount} LIVE)</span>
                  </h3>
                  <p className="text-xs text-slate-400 font-sans">
                    Post-mortem forensic rules generated automatically from real SL hits to immunize future trades.
                  </p>
                </div>
              </div>

              {/* Status & Symbol Filters */}
              <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
                {/* Asset Class Filter */}
                <div className="flex bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-[10px]">
                  {(["ALL", "FOREX", "COMMODITIES", "CRYPTO"] as const).map((cls) => (
                    <button
                      key={cls}
                      onClick={() => setRulesClassFilter(cls)}
                      className={`px-2 py-0.5 rounded font-bold transition ${
                        rulesClassFilter === cls
                          ? "bg-cyan-500 text-slate-950"
                          : "text-slate-400 hover:text-white"
                      }`}
                    >
                      {cls}
                    </button>
                  ))}
                </div>

                {/* Symbol Dropdown */}
                <select
                  value={rulesSymbolFilter}
                  onChange={(e) => setRulesSymbolFilter(e.target.value)}
                  className="bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-2.5 py-1 text-xs font-mono focus:outline-none"
                >
                  <option value="">All 14 Pairs</option>
                  {INSTRUMENTS.map((inst) => (
                    <option key={inst.symbol} value={inst.symbol}>
                      {inst.symbol}
                    </option>
                  ))}
                </select>

                {/* Status Dropdown */}
                <select
                  value={rulesStatusFilter}
                  onChange={(e) => setRulesStatusFilter(e.target.value)}
                  className="bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-2.5 py-1 text-xs font-mono focus:outline-none"
                >
                  <option value="ALL">All Statuses</option>
                  <option value="LIVE">LIVE Only ({liveRulesCount})</option>
                  <option value="LOCKED">LOCKED Only</option>
                  <option value="RETIRED">RETIRED Only</option>
                </select>
              </div>
            </div>

            {/* Rules Cards Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {learnedRules
                .filter((r) => {
                  if (rulesSymbolFilter && r.symbol !== rulesSymbolFilter) return false;
                  if (rulesStatusFilter !== "ALL" && r.status !== rulesStatusFilter) return false;
                  if (rulesClassFilter !== "ALL") {
                    const inst = getInstrument(r.symbol);
                    if (inst.assetClass !== rulesClassFilter) return false;
                  }
                  return true;
                })
                .map((r) => {
                  const isLive = r.status === "LIVE";
                  const isLocked = r.status === "LOCKED";

                  return (
                    <div
                      key={r.id}
                      className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800/90 text-xs font-mono space-y-2 hover:border-slate-700 transition shadow-md"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-white text-xs tracking-tight">{r.rule_code}</span>
                        <span
                          className={`text-[9px] px-2 py-0.5 rounded-md font-bold ${
                            isLive
                              ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                              : isLocked
                              ? "bg-blue-950 text-blue-300 border border-blue-800"
                              : "bg-slate-800 text-slate-400 border border-slate-700"
                          }`}
                        >
                          {r.status}
                        </span>
                      </div>

                      <div className="text-[11px] text-slate-400">
                        Pair: <strong className="text-white">{r.symbol}</strong> | Mode:{" "}
                        <strong className="text-white">{r.mode}</strong> | Delta:{" "}
                        <strong className="text-emerald-400">+{r.backtest_net_improvement_pct}%</strong>
                      </div>

                      {/* Plain-English Condition */}
                      <div className="text-[10px] text-slate-300 bg-slate-950/80 p-2 rounded-lg border border-slate-800/80 line-clamp-2 font-sans">
                        {r.failure_reason || r.rule_description || "Blocks trade entry when high-risk divergence detected."}
                      </div>

                      {/* Shadow Scorecard Matrix */}
                      <div className="bg-slate-950 p-2 rounded-lg border border-slate-800 grid grid-cols-2 gap-1.5 text-[10px]">
                        <div>
                          <span className="text-slate-500">PF: </span>
                          <span className="text-amber-400">{r.profit_factor_before ?? 1.0}</span>
                          <span className="text-slate-600"> → </span>
                          <span className="text-emerald-400 font-bold">{r.profit_factor_after ?? 1.5}</span>
                        </div>
                        <div>
                          <span className="text-slate-500">Net R: </span>
                          <span className="text-cyan-400 font-bold">+{r.net_r_delta ?? 0.0}R</span>
                        </div>
                        <div>
                          <span className="text-slate-500">Winners: </span>
                          <span className="text-slate-200">{r.winners_preserved_pct ?? 100}% kept</span>
                        </div>
                        <div>
                          <span className="text-slate-500">Avoided: </span>
                          <span className="text-emerald-400 font-bold">${r.avoided_losses_usd ?? 0.0}</span>
                        </div>
                      </div>

                      {/* Action Buttons */}
                      <div className="flex justify-end gap-1.5 pt-1">
                        {isLive ? (
                          <button
                            disabled={ruleActionLoading === r.id}
                            onClick={() => handleUpdateRuleStatus(r.id, "RETIRED")}
                            className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] rounded-lg transition"
                          >
                            Retire
                          </button>
                        ) : (
                          <button
                            disabled={ruleActionLoading === r.id}
                            onClick={() => handleUpdateRuleStatus(r.id, "LIVE")}
                            className="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-500 text-white text-[10px] font-bold rounded-lg transition shadow"
                          >
                            Promote LIVE
                          </button>
                        )}
                        <button
                          disabled={ruleActionLoading === r.id}
                          onClick={() => handleUpdateRuleStatus(r.id, "LOCKED")}
                          className="px-2.5 py-1 bg-blue-900/60 hover:bg-blue-800 text-blue-200 text-[10px] rounded-lg transition border border-blue-800"
                        >
                          Lock
                        </button>
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>

          {/* Per-Pair Pattern Win/Loss Memory Table */}
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl space-y-3">
            <div className="flex items-center gap-2 border-b border-slate-800/80 pb-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              <h4 className="font-bold text-white text-xs font-mono uppercase">
                Per-Pair Pattern Win/Loss Memory Scorecard
              </h4>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono divide-y divide-slate-800">
                <thead className="bg-[#070b13] text-slate-400 text-[10px] uppercase">
                  <tr>
                    <th className="py-2 px-3">Symbol</th>
                    <th className="py-2 px-3">Pattern Type</th>
                    <th className="py-2 px-3">Mode</th>
                    <th className="py-2 px-3">Win Count</th>
                    <th className="py-2 px-3">Loss Count</th>
                    <th className="py-2 px-3">Win Rate</th>
                    <th className="py-2 px-3">Net PnL</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50 text-slate-300">
                  {patternMemory.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-6 text-center text-slate-500 font-mono">
                        No pattern memory records populated yet. Real trade closes dynamically hydrate this scorecard.
                      </td>
                    </tr>
                  ) : (
                    patternMemory.map((p, idx) => (
                      <tr key={idx} className="hover:bg-slate-800/20">
                        <td className="py-2 px-3 font-bold text-white">{p.symbol}</td>
                        <td className="py-2 px-3 text-cyan-300">{p.pattern_type}</td>
                        <td className="py-2 px-3">{p.trade_mode || "SCALP"}</td>
                        <td className="py-2 px-3 text-emerald-400">{p.win_count ?? 0}</td>
                        <td className="py-2 px-3 text-rose-400">{p.loss_count ?? 0}</td>
                        <td className="py-2 px-3 font-bold text-slate-200">
                          {p.win_count + p.loss_count > 0
                            ? ((p.win_count / (p.win_count + p.loss_count)) * 100).toFixed(1)
                            : "0.0"}%
                        </td>
                        <td className={`py-2 px-3 font-bold ${
                          (p.net_pnl || 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                        }`}>
                          {fmtUsd(p.net_pnl || 0, true)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          SUB-TAB C: STRATEGY LAB & PROMPT STUDIO
          ========================================================================= */}
      {activeSubTab === "STRATEGY" && (
        <div className="space-y-4">
          {/* Quick Header Bar with Prompt Inspector Button */}
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
                <FileCode className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white font-mono">
                  PYTHON STRATEGY SANDBOX & 5-GATE PROMPT STUDIO
                </h3>
                <p className="text-xs text-slate-400">
                  AST-guarded Python strategy backtesting, XM Ultra Low fee engine, and Gemini Supervisor Prompt Inspector.
                </p>
              </div>
            </div>

            <button
              onClick={handleOpenPromptModal}
              className="flex items-center gap-2 px-4 py-2 bg-purple-900/40 hover:bg-purple-900/60 border border-purple-700/60 text-purple-200 text-xs font-mono font-bold rounded-xl transition shadow-lg"
            >
              <Sparkles className="w-4 h-4 text-purple-400" />
              <span>Inspect 5-Gate AI System Prompt</span>
            </button>
          </div>

          {/* Strategy Lab Tab Component Embedded */}
          <StrategyLabTab selectedSymbol={selectedSymbol} />
        </div>
      )}

      {/* =========================================================================
          SUB-TAB D: SYSTEM HYGIENE & TELEGRAM CENTER
          ========================================================================= */}
      {activeSubTab === "HYGIENE" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Column 1: Daily Cache Hygiene */}
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2.5">
                <Database className="w-5 h-5 text-cyan-400" />
                <div>
                  <h4 className="font-bold text-white text-xs font-mono uppercase">
                    Daily Cache Hygiene & Memory Control
                  </h4>
                  <div className="text-[10px] text-slate-400">
                    Purges stale tick buffers, radar hashes and market packet caches.
                  </div>
                </div>
              </div>

              <button
                onClick={handleClearCacheNow}
                disabled={cacheClearing}
                className="px-3 py-1.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/40 rounded-xl text-xs font-mono font-bold transition flex items-center gap-1.5 disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>{cacheClearing ? "Clearing..." : "Clear Cache Now"}</span>
              </button>
            </div>

            {/* Cache Telemetry Metrics Grid */}
            <div className="grid grid-cols-2 gap-3 text-xs font-mono">
              <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800/80">
                <span className="text-slate-500 text-[10px] uppercase">Cached Entries:</span>
                <div className="text-lg font-bold text-white mt-1">
                  {cacheStatus?.cached_entries_count ?? 0}
                </div>
              </div>
              <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800/80">
                <span className="text-slate-500 text-[10px] uppercase">Buffer Footprint:</span>
                <div className="text-lg font-bold text-cyan-400 mt-1">
                  {cacheStatus?.estimated_size_kb ?? 0} KB
                </div>
              </div>
              <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800/80">
                <span className="text-slate-500 text-[10px] uppercase">Auto Daily Purge:</span>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`w-2 h-2 rounded-full ${
                    cacheStatus?.auto_daily_enabled ? "bg-emerald-400" : "bg-slate-500"
                  }`} />
                  <span className="font-bold text-white">
                    {cacheStatus?.auto_daily_enabled ? "ENABLED (00:05 UTC)" : "DISABLED"}
                  </span>
                </div>
              </div>
              <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800/80">
                <span className="text-slate-500 text-[10px] uppercase">Health Status:</span>
                <div className="text-xs font-bold text-emerald-400 mt-1">
                  {cacheStatus?.health_badge || "OPTIMAL"}
                </div>
              </div>
            </div>

            {/* Auto Policy Toggle */}
            <div className="pt-2">
              <button
                onClick={handleToggleAutoDailyCache}
                className={`w-full py-2 px-3 rounded-xl text-xs font-mono font-bold transition flex items-center justify-center gap-2 border ${
                  cacheStatus?.auto_daily_enabled
                    ? "bg-slate-900 text-slate-300 border-slate-800 hover:bg-slate-800"
                    : "bg-emerald-600 hover:bg-emerald-500 text-white border-transparent"
                }`}
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>
                  {cacheStatus?.auto_daily_enabled
                    ? "Disable Automated Daily Purge"
                    : "Enable Automated Daily Purge (00:05 UTC / 05:35 IST)"}
                </span>
              </button>
            </div>
          </div>

          {/* Column 2: Telegram Alert Center */}
          <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2.5">
                <Bell className="w-5 h-5 text-blue-400" />
                <div>
                  <h4 className="font-bold text-white text-xs font-mono uppercase">
                    Telegram Notification Center
                  </h4>
                  <div className="text-[10px] text-slate-400">
                    HTML-formatted instant alerts for pre-triggers, orders & closes.
                  </div>
                </div>
              </div>

              <button
                onClick={handleSaveTelegramConfig}
                disabled={telegramSaving}
                className="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 text-slate-950 rounded-xl text-xs font-mono font-bold transition flex items-center gap-1.5 shadow disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                <span>{telegramSaving ? "Saving..." : "Save Telegram"}</span>
              </button>
            </div>

            {/* Form Inputs: Bot Token & Chat ID */}
            <div className="space-y-3 text-xs font-mono">
              <div>
                <label className="text-[10px] text-slate-400 uppercase">Admin Chat ID / Channel ID</label>
                <input
                  type="text"
                  placeholder="e.g. -100123456789 or 987654321"
                  value={chatIdInput}
                  onChange={(e) => setChatIdInput(e.target.value)}
                  className="w-full mt-1 px-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <div className="flex justify-between items-center text-[10px] text-slate-400 uppercase">
                  <span>Bot Token</span>
                  <button
                    onClick={() => setShowTokenInput((v) => !v)}
                    className="text-cyan-400 hover:underline"
                  >
                    {showTokenInput ? "Cancel" : "Update Token"}
                  </button>
                </div>
                {showTokenInput ? (
                  <input
                    type="password"
                    placeholder="Enter new Telegram Bot Token..."
                    value={newTokenInput}
                    onChange={(e) => setNewTokenInput(e.target.value)}
                    className="w-full mt-1 px-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-white focus:outline-none focus:border-cyan-500"
                  />
                ) : (
                  <div className="w-full mt-1 px-3 py-1.5 bg-slate-950 border border-slate-800/80 rounded-lg text-slate-400">
                    {telegramConfig.bot_token_masked || "Configured in backend (.env / MySQL)"}
                  </div>
                )}
              </div>

              {/* Event Toggles Matrix */}
              <div className="pt-2 border-t border-slate-800/80 space-y-2">
                <span className="text-[10px] text-slate-400 uppercase font-bold">Subscribed Events</span>
                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={telegramConfig.notify_pre_trigger}
                      onChange={(e) =>
                        setTelegramConfig({ ...telegramConfig, notify_pre_trigger: e.target.checked })
                      }
                      className="rounded bg-slate-900 border-slate-800 text-cyan-500 focus:ring-0"
                    />
                    <span>Pre-Trigger Radar</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={telegramConfig.notify_executions}
                      onChange={(e) =>
                        setTelegramConfig({ ...telegramConfig, notify_executions: e.target.checked })
                      }
                      className="rounded bg-slate-900 border-slate-800 text-cyan-500 focus:ring-0"
                    />
                    <span>Order Executions</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={telegramConfig.notify_be_and_partials}
                      onChange={(e) =>
                        setTelegramConfig({ ...telegramConfig, notify_be_and_partials: e.target.checked })
                      }
                      className="rounded bg-slate-900 border-slate-800 text-cyan-500 focus:ring-0"
                    />
                    <span>BE & Partials (+1.5R)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={telegramConfig.notify_closures}
                      onChange={(e) =>
                        setTelegramConfig({ ...telegramConfig, notify_closures: e.target.checked })
                      }
                      className="rounded bg-slate-900 border-slate-800 text-cyan-500 focus:ring-0"
                    />
                    <span>Trade Closes & Scorecard</span>
                  </label>
                </div>
              </div>

              {/* Template Test Simulator */}
              <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between gap-2">
                <select
                  value={testTemplate}
                  onChange={(e) => setTestTemplate(e.target.value)}
                  className="bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-2.5 py-1 text-xs focus:outline-none"
                >
                  <option value="PRE_TRIGGER">1. Pre-Trigger Radar Alert</option>
                  <option value="EXECUTION">2. Order Executed Alert</option>
                  <option value="BREAKEVEN">3. Break-Even Profit Lock</option>
                  <option value="PARTIAL_TP1">4. Partial Scale-Out TP1</option>
                  <option value="CLOSE">5. Trade Closed & Scorecard</option>
                  <option value="GUARDRAIL">6. Guardrail Circuit Breaker</option>
                </select>

                <button
                  disabled={testSending}
                  onClick={handleSendTestPreview}
                  className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-cyan-800/60 rounded-lg text-xs font-bold transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  <Send className={`w-3 h-3 ${testSending ? "animate-spin" : ""}`} />
                  <span>Send Test Preview</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          MODAL: 5-GATE INSTITUTIONAL PROMPT INSPECTOR
          ========================================================================= */}
      {promptModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0f1623] border border-slate-700 rounded-2xl max-w-4xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden font-sans">
            {/* Modal Header */}
            <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-[#0a0f19]">
              <div className="flex items-center gap-2.5">
                <Sparkles className="w-5 h-5 text-purple-400" />
                <h3 className="font-bold text-white text-sm font-mono">
                  INSTITUTIONAL 5-GATE GEMINI SUPERVISOR SYSTEM PROMPT
                </h3>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopyPrompt}
                  className="flex items-center gap-1.5 px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-mono font-semibold transition"
                >
                  {copiedPrompt ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                      <span className="text-emerald-400">Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 text-slate-400" />
                      <span>Copy Prompt</span>
                    </>
                  )}
                </button>

                <button
                  onClick={() => setPromptModalOpen(false)}
                  className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Content */}
            <div className="p-4 overflow-y-auto flex-1 font-mono text-xs bg-[#080c14] space-y-3">
              {promptLoading ? (
                <div className="py-20 text-center text-slate-500">Loading prompt schema...</div>
              ) : (
                <pre className="text-slate-300 whitespace-pre-wrap leading-relaxed select-text font-mono text-[11px] bg-slate-950 p-4 rounded-xl border border-slate-800/80">
                  {promptPreviewText}
                </pre>
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-3 border-t border-slate-800 bg-[#0a0f19] flex justify-between items-center text-[11px] text-slate-500 font-mono">
              <span>Deterministic JSON audit enforced via Pydantic response schema.</span>
              <button
                onClick={() => setPromptModalOpen(false)}
                className="px-3 py-1 bg-slate-800 text-slate-300 rounded-lg hover:text-white"
              >
                Close
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
