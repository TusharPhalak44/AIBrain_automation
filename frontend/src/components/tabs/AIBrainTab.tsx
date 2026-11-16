import React, { useState, useEffect } from "react";
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
  const [globalInterval, setGlobalInterval] = useState<number>(300);
  const [isLoading, setIsLoading] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [ruleActionLoading, setRuleActionLoading] = useState<number | null>(null);
  const [isStaging, setIsStaging] = useState<number | null>(null);
  const toast = useToast();

  const handleStageReport = async (rep: any) => {
    if (!rep.entry_price || !rep.stop_loss) {
      toast.warning("No Coordinates", "This report does not contain entry or stop-loss prices to stage.");
      return;
    }
    setIsStaging(rep.id);
    try {
      const isSell = String(rep.decision).toUpperCase().includes("SELL");
      const mode = rep.recommended_mode === "SWING" ? "SWING" : "SCALP";
      await api.ai.stageCopilot({
        symbol: rep.symbol,
        mode: mode,
        direction: isSell ? "SELL" : "BUY",
        entry_price: rep.entry_price,
        sl: rep.stop_loss,
        tp1: rep.tp1 || rep.entry_price,
        tp2: rep.tp2 || rep.entry_price,
        lots: 0.01,
        ai_analysis_summary: rep.thesis_text || `Staged from Gemini Report #${rep.id}`,
      });
      toast.success("Trade Staged", `Planned ${isSell ? "SELL" : "BUY"} setup staged into Copilot for ${rep.symbol}.`);
    } catch (e: any) {
      toast.error("Staging Failed", e.message || String(e));
    } finally {
      setIsStaging(null);
    }
  };

  const fetchBrainData = async () => {
    setIsLoading(true);
    try {
      const [repData, newsPayload, rulesData] = await Promise.all([
        api.ai.getReports({ limit: 20 }),
        api.ai.getNews(selectedSymbol),
        api.ai.getRules(),
      ]);

      setReports(safeArr(repData));
      setNewsData(newsPayload || { events: [], blackout_check: null });
      setLearnedRules(safeArr(rulesData));
    } catch (e: any) {
      console.error("Failed to fetch AI supervisor data:", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchBrainData();
  }, [selectedSymbol]);

  const handleScanPair = async () => {
    setIsScanning(true);
    try {
      const res = await api.ai.scanPair(selectedSymbol);
      toast.success("Scan Complete", res.message || `${selectedSymbol} scanned by Gemini Supervisor.`);
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

        {/* Scan Triggers */}
        <div className="flex items-center gap-2">
          <button
            disabled={isScanning}
            onClick={handleScanPair}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg text-xs shadow transition disabled:opacity-50"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>{isScanning ? "Scanning..." : `Scan ${selectedSymbol} Now`}</span>
          </button>
          <button
            disabled={isScanning}
            onClick={handleScanAll}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold rounded-lg text-xs border border-slate-700 transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? "animate-spin" : ""}`} />
            <span>Scan All Pairs</span>
          </button>
        </div>
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
                      {r.action?.reason && (
                        <div className="text-[10px] text-slate-400 mt-1 italic">
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
                        <button
                          disabled={isStaging === rep.id}
                          onClick={() => handleStageReport(rep)}
                          className="px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded text-[10px] shadow transition flex items-center gap-1 font-sans"
                        >
                          <Zap className="w-3 h-3 text-amber-300" />
                          <span>{isStaging === rep.id ? "Staging..." : "Stage to Copilot / Execute"}</span>
                        </button>
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
    </div>
  );
};

