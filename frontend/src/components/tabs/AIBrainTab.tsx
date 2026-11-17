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
} from "lucide-react";
import { fmtPct, fmtConfidence, safeArr, safeStr } from "../../utils/format";
import { PairSchedule } from "../../hooks/useLiveStore";
import { api } from "../../services/api";
import { useToast } from "../Toast";

interface AIBrainTabProps {
  selectedSymbol: string;
  pairSchedules: Record<string, PairSchedule>;
}

export const AIBrainTab: React.FC<AIBrainTabProps> = ({
  selectedSymbol,
  pairSchedules,
}) => {
  const [reports, setReports] = useState<any[]>([]);
  const [newsData, setNewsData] = useState<any>({ events: [], blackout_check: null });
  const [learnedRules, setLearnedRules] = useState<any[]>([]);
  const [patternMemory, setPatternMemory] = useState<any[]>([]);
  const [globalInterval, setGlobalInterval] = useState<number>(300);
  const [isLoading, setIsLoading] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [ruleActionLoading, setRuleActionLoading] = useState<number | null>(null);
  const [upcomingData, setUpcomingData] = useState<any>({ actionable_setups: [], watchlist_radar: [] });
  const [radarSubView, setRadarSubView] = useState<"ALL" | "ACTIONABLE" | "WATCHLIST">("ALL");
  const toast = useToast();

  const handleSendTelegramAlert = async (item: any) => {
    try {
      await api.telegram.testMessage();
      toast.success("Alert Sent", `Dispatched setup alert for ${item.symbol} to Telegram.`);
    } catch (e: any) {
      toast.error("Alert Failed", e.message || String(e));
    }
  };

  const fetchBrainData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [repData, newsPayload, rulesData, upcomingPayload, patternsPayload] = await Promise.all([
        api.ai.getReports({ limit: 20 }),
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
    } catch (e: any) {
      console.error("Failed to fetch AI supervisor data:", e);
    } finally {
      setIsLoading(false);
    }
  }, [selectedSymbol]);

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

  const handleScanPair = async () => {
    await handleScanSpecificPair(selectedSymbol);
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

  const handleSaveInterval = async () => {
    try {
      await api.ai.updateInterval({ global_scan_interval_sec: globalInterval });
      toast.success("Interval Updated", `Global scan interval set to ${globalInterval} seconds.`);
    } catch (e: any) {
      toast.error("Update Failed", e.message || String(e));
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

  return (
    <div className="space-y-4">
      {/* Top Banner: Tier-1 Macro News & Blackout Guard */}
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
                  BLACKOUT ACTIVE
                </span>
              ) : (
                <span className="bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded text-[10px] font-bold">
                  PASS - ENTRIES ALLOWED
                </span>
              )}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              {newsData?.blackout_check?.reason ||
                "No Tier-1 news releases scheduled within +/- 15 minute entry window."}
            </div>
          </div>
        </div>

        {/* Scan Triggers: GOLD#, BTCUSD#, Both */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            disabled={isScanning}
            onClick={() => handleScanSpecificPair("GOLD#")}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white font-bold rounded-lg text-xs shadow transition disabled:opacity-50"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>⚡ Scan GOLD#</span>
          </button>
          <button
            disabled={isScanning}
            onClick={() => handleScanSpecificPair("BTCUSD#")}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-600 hover:bg-orange-500 text-white font-bold rounded-lg text-xs shadow transition disabled:opacity-50"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>⚡ Scan BTCUSD#</span>
          </button>
          <button
            disabled={isScanning}
            onClick={handleScanAll}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold rounded-lg text-xs border border-slate-700 transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? "animate-spin" : ""}`} />
            <span>⚡ Scan Both Pairs</span>
          </button>
        </div>
      </div>

      {/* UPCOMING TRADES & PRE-TRIGGER SETUPS RADAR */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-4 space-y-4">
        {/* Radar Header & Filter Pills */}
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
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  MODE: {upcomingData?.execution_mode || "COPILOT"}
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300">
                  {upcomingData?.account_type || "DEMO"}
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Institutional setups forecasted by Gemini with live tick proximity tracking and auto-execution readiness.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 bg-slate-950 border border-slate-800 rounded-lg p-1 text-xs">
            <button
              onClick={() => setRadarSubView("ALL")}
              className={`px-3 py-1 rounded font-semibold transition ${
                radarSubView === "ALL"
                  ? "bg-amber-500/20 text-amber-300"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              All ({(upcomingData?.actionable_setups?.length || 0) + (upcomingData?.watchlist_radar?.length || 0)})
            </button>
            <button
              onClick={() => setRadarSubView("ACTIONABLE")}
              className={`px-3 py-1 rounded font-semibold transition ${
                radarSubView === "ACTIONABLE"
                  ? "bg-emerald-500/20 text-emerald-300"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Actionable Limits ({upcomingData?.actionable_setups?.length || 0})
            </button>
            <button
              onClick={() => setRadarSubView("WATCHLIST")}
              className={`px-3 py-1 rounded font-semibold transition ${
                radarSubView === "WATCHLIST"
                  ? "bg-cyan-500/20 text-cyan-300"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Watchlist Radar ({upcomingData?.watchlist_radar?.length || 0})
            </button>
          </div>
        </div>

        {/* Section A: Actionable Auto Setups & Pending Limits */}
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

                      {/* Readiness Bar */}
                      <div>
                        <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                          <span>Setup Readiness</span>
                          <span className="font-bold text-emerald-400">{setup.readiness_pct}%</span>
                        </div>
                        <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
                          <div
                            style={{ width: `${setup.readiness_pct}%` }}
                            className="bg-emerald-500 h-full rounded-full transition-all"
                          />
                        </div>
                      </div>

                      <p className="text-[11px] text-slate-400 line-clamp-2 italic">
                        "{setup.thesis || 'Algorithmic setup confirmed by Gemini Supervisor.'}"
                      </p>

                      {/* Autonomous Execution Status */}
                      <div className="flex items-center justify-between text-[11px] bg-slate-900/80 px-3 py-1.5 rounded-lg border border-slate-800 text-slate-300">
                        <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                          <span>🟢 Auto-Armed Execution</span>
                        </span>
                        <span className="font-mono text-slate-400 text-[10px]">
                          Anti-Chase Guard Active
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-3 bg-slate-950/40 border border-slate-800/60 rounded-lg text-slate-500 text-xs text-center font-mono">
                No active limit orders currently pending execution. Setups are routed automatically via AUTO Mode or tracked on the Watchlist Radar below.
              </div>
            )}
          </div>
        )}

        {/* Section B: Watchlist Developing Radar Cards */}
        {(radarSubView === "ALL" || radarSubView === "WATCHLIST") && (
          <div className="space-y-2.5 pt-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-cyan-400 flex items-center gap-1.5">
                <Compass className="w-4 h-4" />
                <span>Developing Watchlist Radar Across Monitored Pairs ({upcomingData?.watchlist_radar?.length || 0})</span>
              </span>
              <span className="text-[11px] text-slate-500 font-mono">Ticking Real-Time against XM MT5 Quotes</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {upcomingData?.watchlist_radar && upcomingData.watchlist_radar.length > 0 ? (
                upcomingData.watchlist_radar.map((item: any, idx: number) => {
                  const isBull = item.watch_bias === "BULLISH_WATCH";
                  return (
                    <div
                      key={idx}
                      className="bg-slate-950 border border-slate-800 rounded-xl p-3.5 space-y-2.5 hover:border-slate-700 transition"
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
                        </div>

                        {/* Proximity Tag */}
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

                      {/* Readiness Bar */}
                      <div>
                        <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                          <span>Readiness</span>
                          <span className="font-bold text-white">{item.readiness_pct}%</span>
                        </div>
                        <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
                          <div
                            style={{ width: `${item.readiness_pct}%` }}
                            className={`h-full rounded-full transition-all ${
                              item.readiness_pct >= 85
                                ? "bg-emerald-500"
                                : item.readiness_pct >= 70
                                ? "bg-cyan-500"
                                : "bg-amber-500"
                            }`}
                          />
                        </div>
                      </div>

                      {/* Condition & Window */}
                      <div className="text-[11px] text-slate-300 space-y-0.5">
                        <div className="text-slate-400 font-semibold text-[10px]">Trigger Condition:</div>
                        <div className="text-[11px] text-slate-300 line-clamp-2">
                          {item.trigger_condition || "Waiting for key support/resistance sweep"}
                        </div>
                        <div className="text-[10px] text-slate-500 mt-1 flex justify-between">
                          <span>Window: {item.expected_window || "Next 1-2 hours"}</span>
                          {item.invalidation_level > 0 && (
                            <span>Cancel: {item.invalidation_level}</span>
                          )}
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex gap-2 pt-1 border-t border-slate-800/60">
                        <button
                          onClick={() => handleSendTelegramAlert(item)}
                          className="px-2.5 py-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 rounded-lg text-xs font-semibold border border-slate-800 transition flex items-center gap-1.5"
                          title="Broadcast setup alert to configured Telegram channel"
                        >
                          <Send className="w-3.5 h-3.5 text-blue-400" />
                          <span>Telegram Alert</span>
                        </button>
                        <div className="flex-1 py-1.5 bg-emerald-950/40 border border-emerald-800/40 text-emerald-300 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 font-mono">
                          <Target className="w-3.5 h-3.5 text-emerald-400" />
                          <span>AUTO Execution Monitored</span>
                        </div>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="col-span-3 py-6 text-center text-slate-500 text-xs">
                  Scanning for high-probability setups... Click "Scan All Pairs" to refresh developing radar.
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Interval Controls & AI Supervisory Feed Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column: Interval Controls & Learned Rules (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          {/* Scan Interval Config */}
          <div className="bg-[#121824] border border-slate-800 rounded-xl p-4">
            <div className="font-bold text-white text-xs flex items-center gap-2 mb-3">
              <Sliders className="w-4 h-4 text-blue-400" />
              <span>LIVE INTERVAL EXECUTION SCHEDULER</span>
            </div>
            <div className="space-y-3 text-xs">
              <div>
                <div className="flex justify-between text-slate-400 mb-1">
                  <span>Global Scan Interval</span>
                  <strong className="text-white font-mono">{globalInterval}s</strong>
                </div>
                <input
                  type="range"
                  min={10}
                  max={600}
                  step={10}
                  value={globalInterval}
                  onChange={(e) => setGlobalInterval(parseInt(e.target.value))}
                  className="w-full accent-blue-500"
                />
              </div>
              <button
                onClick={handleSaveInterval}
                className="w-full py-1.5 bg-slate-800 hover:bg-slate-700 text-white font-bold rounded-lg transition"
              >
                Apply Scan Interval
              </button>
            </div>
          </div>

          {/* Self-Learned Rules Vault */}
          <div className="bg-[#121824] border border-slate-800 rounded-xl p-4">
            <div className="font-bold text-white text-xs flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-emerald-400" />
                <span>SELF-LEARNED RULES VAULT ({learnedRules.length})</span>
              </div>
              <span className="text-[10px] text-slate-400">MySQL xm_trading_v2</span>
            </div>

            <div className="space-y-2 max-h-[360px] overflow-y-auto">
              {learnedRules.length === 0 ? (
                <div className="text-slate-500 text-xs py-4 text-center">
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
                      {/* Headless Shadow-Validation Scorecard */}
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
                      {r.action?.reason && (
                        <div className="text-[10px] text-slate-400 mt-1.5 italic">
                          "{r.action.reason}"
                        </div>
                      )}
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
        </div>

        {/* Right Column: AI Supervisory Analysis Cards (7 cols) */}
        <div className="lg:col-span-7 bg-[#121824] border border-slate-800 rounded-xl p-4 flex flex-col">
          <div className="font-bold text-white text-xs flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
            <div className="flex items-center gap-2">
              <Brain className="w-4 h-4 text-purple-400" />
              <span>GEMINI SUPERVISORY ANALYSIS FEED</span>
            </div>
            <span className="text-[10px] text-slate-400">Official google-genai SDK</span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-3">
            {reports.length === 0 ? (
              <div className="text-slate-500 text-xs py-8 text-center">
                No supervisory reports logged. Click "Scan {selectedSymbol} Now" to execute Gemini analysis.
              </div>
            ) : (
              reports.map((rep) => {
                const isBuy = rep.decision === "BUY";
                const isSell = rep.decision === "SELL";
                return (
                  <div
                    key={rep.id}
                    className="p-3 rounded-xl bg-slate-900/90 border border-slate-800 text-xs space-y-2"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-sm">{rep.symbol}</span>
                        <span
                          className={`font-black px-2 py-0.5 rounded text-[11px] ${
                            isBuy
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                              : isSell
                              ? "bg-red-950 text-red-400 border border-red-800"
                              : "bg-slate-800 text-slate-300 border border-slate-700"
                          }`}
                        >
                          {rep.decision} ({rep.recommended_mode})
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
                          <span className="text-red-400">Hard SL: <strong className="text-red-300">{rep.stop_loss}</strong></span>
                          <span className="text-emerald-400">TP1 (+1.5R): <strong className="text-emerald-300">{rep.tp1 ?? "-"}</strong></span>
                          {rep.tp2 && <span className="text-emerald-500">TP2: <strong className="text-emerald-400">{rep.tp2}</strong></span>}
                        </div>
                        <span className="px-2.5 py-1 bg-emerald-950/60 text-emerald-300 border border-emerald-800/40 font-bold rounded text-[10px] flex items-center gap-1 font-mono">
                          <Zap className="w-3 h-3 text-emerald-400" />
                          <span>AUTO Dispatch Engine</span>
                        </span>
                      </div>
                    ) : null}

                    {rep.thesis_text && (
                      <p className="text-slate-300 text-xs leading-relaxed bg-[#0B0E14] p-2.5 rounded-lg border border-slate-800/80">
                        {rep.thesis_text}
                      </p>
                    )}

                    <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1">
                      <span>Status: <strong className="text-slate-200">{rep.execution_status}</strong></span>
                      <span>Account: <strong className="text-slate-200">{rep.account_type}</strong></span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Per-Pair Pattern Win/Loss Memory (GOLD# vs BTCUSD#) */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-4 space-y-3">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-purple-400" />
            <div>
              <h3 className="font-bold text-white text-sm">PER-PAIR PATTERN WIN/LOSS MEMORY (GOLD# vs BTCUSD#)</h3>
              <p className="text-[11px] text-slate-400">
                Self-learning closed-loop pattern telemetry. Patterns with ≥60% win rate qualify as PROVEN_EDGE, while degraded setups are isolated as BLOCKED_TRAP.
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
                  <th className="py-2 px-3">AI Edge Status</th>
                  <th className="py-2 px-3">Last AI Lesson / Forensic Postmortem</th>
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
                      <td className={`py-2.5 px-3 font-bold ${
                        p.win_rate_pct >= 60.0
                          ? "text-emerald-400"
                          : p.win_rate_pct <= 35.0
                          ? "text-red-400"
                          : "text-amber-300"
                      }`}>
                        {fmtPct(p.win_rate_pct)}
                      </td>
                      <td className="py-2.5 px-3 text-blue-300 font-bold">
                        {p.avg_r_multiple > 0 ? `+${p.avg_r_multiple}R` : `${p.avg_r_multiple}R`}
                      </td>
                      <td className={`py-2.5 px-3 font-bold ${
                        p.net_pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"
                      }`}>
                        {p.net_pnl_usd >= 0 ? `+$${p.net_pnl_usd.toFixed(2)}` : `-$${Math.abs(p.net_pnl_usd).toFixed(2)}`}
                      </td>
                      <td className="py-2.5 px-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          isEdge
                            ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                            : isTrap
                            ? "bg-red-950 text-red-400 border border-red-800 animate-pulse"
                            : "bg-blue-950 text-blue-400 border border-blue-800"
                        }`}>
                          {p.status}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-slate-300 font-sans max-w-md truncate" title={p.last_ai_lesson}>
                        {p.last_ai_lesson}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

