import React, { useState } from "react";
import {
  ShieldAlert,
  Sliders,
  RefreshCw,
  Clock,
  Layers,
  Globe,
  Play,
  CheckCircle2,
  AlertOctagon,
  Pause,
  AlertTriangle,
  Command,
} from "lucide-react";
import { fmtUsd, fmtPct } from "../utils/format";

interface TopCommandBarProps {
  accountType: string;
  executionMode: string;
  isMt5Connected: boolean;
  dbHealthy: boolean;
  isWsConnected: boolean;
  balance: number;
  equity: number;
  floatingPnl: number;
  marginUsagePct: number;
  dailyDdPct: number;
  weeklyDdPct: number;
  riskState: string;
  openExposureCount?: number;
  activeSession?: string;
  nextScanSeconds?: number;
  onSwitchAccount: (type: string) => Promise<any>;
  onSwitchMode: (mode: string) => Promise<any>;
  onPanicFlatten: () => Promise<any>;
  onOpenSettings: () => void;
  onOpenQuickSwitcher?: () => void;
  onScanNow?: () => Promise<any> | void;
  onReconcileMT5?: () => Promise<any> | void;
  circuitBreakerStatus?: { status: string; tripped: boolean; reason?: string | null };
  openRiskPct?: number;
}

export const TopCommandBar: React.FC<TopCommandBarProps> = ({
  accountType,
  executionMode,
  isMt5Connected,
  dbHealthy,
  isWsConnected,
  balance,
  equity,
  floatingPnl,
  marginUsagePct,
  dailyDdPct,
  weeklyDdPct,
  riskState,
  openExposureCount = 0,
  activeSession = "Tokyo / Asian",
  nextScanSeconds,
  onSwitchAccount,
  onSwitchMode,
  onPanicFlatten,
  onOpenSettings,
  onOpenQuickSwitcher,
  onScanNow,
  onReconcileMT5,
  circuitBreakerStatus = { status: "HEALTHY", tripped: false },
  openRiskPct = 0.0,
}) => {
  const [showPanicConfirm, setShowPanicConfirm] = useState(false);
  const [showSwitchConfirm, setShowSwitchConfirm] = useState(false);
  const [targetAccount, setTargetAccount] = useState<string>("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [isReconciling, setIsReconciling] = useState(false);
  const [isScanningNow, setIsScanningNow] = useState(false);
  const [lastSyncedTime, setLastSyncedTime] = useState<string>("Just now");

  const handleAccountSwitchClick = (type: string) => {
    if (type === accountType) return;
    setTargetAccount(type);
    setShowSwitchConfirm(true);
  };

  const confirmAccountSwitch = async () => {
    setIsProcessing(true);
    try {
      await onSwitchAccount(targetAccount);
    } finally {
      setIsProcessing(false);
      setShowSwitchConfirm(false);
    }
  };

  const handlePanicClick = async () => {
    setIsProcessing(true);
    try {
      await onPanicFlatten();
    } finally {
      setIsProcessing(false);
      setShowPanicConfirm(false);
    }
  };

  const handleReconcileClick = async () => {
    if (!onReconcileMT5 || isReconciling) return;
    setIsReconciling(true);
    try {
      await onReconcileMT5();
      const now = new Date();
      setLastSyncedTime(now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    } finally {
      setIsReconciling(false);
    }
  };

  const handleScanNowClick = async () => {
    if (!onScanNow || isScanningNow) return;
    setIsScanningNow(true);
    try {
      await onScanNow();
    } finally {
      setTimeout(() => setIsScanningNow(false), 800);
    }
  };

  const isAuto = executionMode === "AUTO";
  const isCircuitBreakerTripped = circuitBreakerStatus?.tripped || circuitBreakerStatus?.status === "PAUSED";

  // Format seconds to MM:SS
  const formatCountdown = (sec?: number) => {
    if (sec === undefined || sec === null || sec < 0) return "--:--";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  return (
    <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-[#080c14]/95 backdrop-blur-md px-3 sm:px-4 h-14 min-h-[56px] flex items-center justify-between gap-3 text-xs shadow-lg select-none whitespace-nowrap overflow-x-auto scrollbar-none">
      {/* =========================================================================
          CLUSTER A (LEFT): Identity & Master Engine Switch
          ========================================================================= */}
      <div className="flex items-center gap-2.5 shrink-0 border-r border-slate-800/80 pr-3">
        {/* Compact XM PORTAL V2 Brand Mark */}
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-cyan-600/15 border border-cyan-500/30 flex items-center justify-center font-black text-cyan-400 tracking-wider text-xs shadow-[0_0_12px_rgba(6,182,212,0.15)]">
            XM
          </div>
          <div className="hidden xl:block">
            <div className="font-bold text-slate-100 tracking-wide flex items-center gap-1.5 text-xs font-mono leading-none whitespace-nowrap">
              <span>PORTAL V2</span>
              <span className="text-[9px] bg-cyan-950/80 text-cyan-400 px-1 py-0.5 rounded border border-cyan-800/50 font-semibold">
                14P
              </span>
            </div>
            <div className="text-[10px] text-slate-400 font-mono mt-0.5">Ultra Low MT5</div>
          </div>
        </div>

        {/* High-Contrast Master Engine Toggle: AUTO ACTIVE (Emerald) vs HALTED (Rose) */}
        <div className="flex items-center bg-[#0b101b] p-0.5 rounded-lg border border-slate-800/90 shadow-inner">
          <button
            onClick={() => onSwitchMode("AUTO")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-mono font-bold transition-all whitespace-nowrap ${
              isAuto
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-[0_0_10px_rgba(16,185,129,0.25)]"
                : "text-slate-400 hover:text-slate-200"
            }`}
            title="Auto execution enabled (Market + Limit orders)"
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isAuto ? "bg-emerald-400 animate-pulse" : "bg-slate-600"
              }`}
            />
            <span>AUTO ACTIVE</span>
          </button>

          <button
            onClick={() => onSwitchMode("HALTED")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-mono font-bold transition-all whitespace-nowrap ${
              !isAuto
                ? "bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-[0_0_10px_rgba(244,63,94,0.25)]"
                : "text-slate-400 hover:text-slate-200"
            }`}
            title="Engine halted: Scanner monitors only, zero broker orders"
          >
            <Pause className="w-3 h-3 text-rose-400" />
            <span>HALTED</span>
          </button>
        </div>

        {/* Compact [ ↻ Sync MT5 ] Button with Tooltip */}
        {onReconcileMT5 && (
          <button
            onClick={handleReconcileClick}
            disabled={isReconciling}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-[#0f1623] hover:bg-[#162032] border border-slate-800/90 text-slate-300 hover:text-cyan-300 transition text-[11px] font-mono group disabled:opacity-50 whitespace-nowrap shrink-0"
            title={`Sync & Reconcile open trades against MT5 deals (Last synced: ${lastSyncedTime})`}
          >
            <RefreshCw
              className={`w-3.5 h-3.5 text-cyan-400 transition-transform ${
                isReconciling ? "animate-spin text-cyan-300" : "group-hover:rotate-180"
              }`}
            />
            <span className="hidden sm:inline text-[10px]">Sync MT5</span>
          </button>
        )}
      </div>

      {/* =========================================================================
          CLUSTER B (CENTER): Single-Line Live Guardrails & Scanner Telemetry
          ========================================================================= */}
      <div className="flex items-center gap-2 shrink-0 border-r border-slate-800/80 pr-3">
        {/* Positions Pill: Strictly Single-Line POS: 1/5 */}
        <div
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border font-mono text-[11px] whitespace-nowrap shrink-0 ${
            openExposureCount >= 5
              ? "bg-rose-950/40 border-rose-500/40 text-rose-300"
              : openExposureCount >= 4
              ? "bg-amber-950/40 border-amber-500/40 text-amber-300"
              : "bg-[#0f1623] border-slate-800 text-slate-300"
          }`}
          title={`Global Open Positions: ${openExposureCount} out of 5 maximum institutional portfolio cap`}
        >
          <Layers className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
          <span className="text-slate-400 text-[10px] uppercase">POS:</span>
          <span className="font-bold tabular-nums whitespace-nowrap">
            {openExposureCount}/5
          </span>
        </div>

        {/* Portfolio Risk Pill: Single-Line Color-Coded RISK: 0.50% / 2.50% */}
        <div
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border font-mono text-[11px] whitespace-nowrap shrink-0 ${
            openRiskPct >= 2.2
              ? "bg-rose-950/40 border-rose-500/40 text-rose-300"
              : openRiskPct >= 1.5
              ? "bg-amber-950/40 border-amber-500/40 text-amber-300"
              : "bg-[#0f1623] border-slate-800 text-slate-300"
          }`}
          title={`Active Portfolio Open Risk: ${fmtPct(openRiskPct)} out of 2.50% max allowed global portfolio exposure`}
        >
          <AlertTriangle
            className={`w-3.5 h-3.5 shrink-0 ${
              openRiskPct >= 2.2
                ? "text-rose-400"
                : openRiskPct >= 1.5
                ? "text-amber-400"
                : "text-emerald-400"
            }`}
          />
          <span className="text-slate-400 text-[10px] uppercase">RISK:</span>
          <span
            className={`font-bold tabular-nums whitespace-nowrap ${
              openRiskPct >= 2.2
                ? "text-rose-300"
                : openRiskPct >= 1.5
                ? "text-amber-300"
                : "text-emerald-300"
            }`}
          >
            {fmtPct(openRiskPct)} / 2.50%
          </span>
        </div>

        {/* Circuit Breaker Pill: CB: HEALTHY / CB: PAUSED */}
        <div
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border font-mono text-[11px] whitespace-nowrap shrink-0 ${
            isCircuitBreakerTripped
              ? "bg-rose-950/60 border-rose-500/60 text-rose-300 animate-pulse"
              : "bg-[#0f1623] border-slate-800 text-slate-300"
          }`}
          title={
            isCircuitBreakerTripped
              ? `Circuit Breaker PAUSED: ${circuitBreakerStatus?.reason || "Daily Drawdown Limit Hit"} (Realized DD: ${fmtPct(dailyDdPct)})`
              : `Daily Drawdown Circuit Breaker: HEALTHY (Realized DD: ${fmtPct(dailyDdPct)}, Buffer: 3.00% Max Loss)`
          }
        >
          {isCircuitBreakerTripped ? (
            <AlertOctagon className="w-3.5 h-3.5 text-rose-400 shrink-0" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          )}
          <span className="text-slate-400 text-[10px] uppercase">CB:</span>
          <span
            className={`font-bold whitespace-nowrap ${
              isCircuitBreakerTripped ? "text-rose-400" : "text-emerald-400"
            }`}
          >
            {isCircuitBreakerTripped ? "PAUSED" : "HEALTHY"}
          </span>
        </div>

        {/* Scanner Cadence Pill: SCAN: MM:SS Countdown + Inline [ Scan Now ] */}
        <div className="inline-flex items-center bg-[#0f1623] border border-slate-800 rounded-lg p-0.5 whitespace-nowrap shrink-0">
          <div
            className="inline-flex items-center gap-1.5 px-2 py-0.5 text-[11px] font-mono text-slate-300"
            title="Countdown to next autonomous multi-pair market packet evaluation"
          >
            <Clock className="w-3 h-3 text-cyan-400 shrink-0" />
            <span className="text-slate-400 text-[10px] uppercase">SCAN:</span>
            <span className="font-bold tabular-nums text-cyan-300">
              {formatCountdown(nextScanSeconds)}
            </span>
          </div>

          {onScanNow && (
            <button
              onClick={handleScanNowClick}
              disabled={isScanningNow}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-cyan-500/15 hover:bg-cyan-500/25 active:bg-cyan-500/30 text-cyan-300 border border-cyan-500/30 rounded font-mono text-[10px] font-bold transition disabled:opacity-50"
              title="Force immediate scan across all enabled pairs"
            >
              <Play className={`w-2.5 h-2.5 shrink-0 ${isScanningNow ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">Scan Now</span>
            </button>
          )}
        </div>
      </div>

      {/* =========================================================================
          CLUSTER C (RIGHT): Session, Account Equity & Emergency Kill-Switch
          ========================================================================= */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Global Active Session Pill */}
        <div
          className="hidden md:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#0f1623] border border-slate-800 text-[11px] font-mono text-indigo-300 whitespace-nowrap shrink-0"
          title={`Active Market Session: ${activeSession}`}
        >
          <Globe className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
          <span>{activeSession}</span>
        </div>

        {/* Account Switcher: DEMO (Cyan) vs LIVE (Rose) */}
        <div className="inline-flex items-center bg-[#0b101b] p-0.5 rounded-lg border border-slate-800 shrink-0">
          <button
            onClick={() => handleAccountSwitchClick("DEMO")}
            className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono transition whitespace-nowrap ${
              accountType === "DEMO"
                ? "bg-cyan-600 text-slate-950 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            DEMO
          </button>
          <button
            onClick={() => handleAccountSwitchClick("LIVE")}
            className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono transition whitespace-nowrap ${
              accountType === "LIVE"
                ? "bg-rose-600 text-white shadow-sm animate-pulse"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            LIVE
          </button>
        </div>

        {/* Live Equity & PnL Block (Monospace Tabular) */}
        <div className="bg-[#0f1623] px-2.5 py-1 rounded-lg border border-slate-800 inline-flex items-center gap-2 font-mono text-xs whitespace-nowrap shrink-0">
          <div>
            <span className="text-[9px] text-slate-400 uppercase mr-1">EQ:</span>
            <span className="font-bold text-slate-100 tabular-nums">{fmtUsd(equity)}</span>
          </div>
          <div className="h-3.5 w-px bg-slate-800" />
          <div
            className={`font-bold tabular-nums ${
              floatingPnl > 0
                ? "text-emerald-400"
                : floatingPnl < 0
                ? "text-rose-400"
                : "text-slate-400"
            }`}
            title="Live floating unrealized P&L across all active MT5 broker positions"
          >
            {fmtUsd(floatingPnl, true)}
          </div>
        </div>

        {/* Emergency Panic Flatten Button with 2-Step Popover */}
        <div className="relative inline-block shrink-0">
          <button
            onClick={() => setShowPanicConfirm((prev) => !prev)}
            className="inline-flex items-center gap-1 px-2.5 py-1 bg-rose-600 hover:bg-rose-500 active:bg-rose-700 text-white font-bold rounded-lg text-[11px] font-mono shadow-md shadow-rose-950/50 transition whitespace-nowrap shrink-0"
            title="Emergency Panic Flatten: Close all open positions & cancel pending orders"
          >
            <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
            <span>FLATTEN</span>
          </button>

          {/* Clean 2-Step Popover cleanly positioned inside right viewport */}
          {showPanicConfirm && (
            <div className="absolute right-0 top-full mt-2 z-50 bg-[#0f1623] border border-rose-500/80 rounded-xl p-3.5 shadow-2xl w-64 space-y-2.5 text-left select-text">
              <div className="flex items-center gap-2 text-rose-400 font-bold text-xs font-mono">
                <AlertOctagon className="w-4 h-4 shrink-0 text-rose-400" />
                <span>FLATTEN ALL POSITIONS?</span>
              </div>
              <p className="text-[11px] text-slate-300 font-sans leading-tight">
                Immediately closes all open MT5 positions and cancels all pending orders across 14 pairs.
              </p>
              <div className="flex items-center justify-end gap-2 pt-1 border-t border-slate-800">
                <button
                  onClick={() => setShowPanicConfirm(false)}
                  className="px-2.5 py-1 text-[11px] text-slate-400 hover:text-white font-mono rounded"
                >
                  Cancel
                </button>
                <button
                  onClick={handlePanicClick}
                  disabled={isProcessing}
                  className="px-3 py-1 text-[11px] bg-rose-600 hover:bg-rose-500 text-white font-bold font-mono rounded shadow disabled:opacity-50"
                >
                  {isProcessing ? "Closing..." : "Yes, Flatten All"}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Quick Command Palette Trigger (Ctrl+K / ⌘K) */}
        {onOpenQuickSwitcher && (
          <button
            onClick={onOpenQuickSwitcher}
            className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#0f1623] hover:bg-[#162032] border border-slate-800 text-slate-300 hover:text-white transition font-mono text-[11px] shrink-0"
            title="Open Quick Pair & Workspace Command Palette (Ctrl+K / ⌘K)"
          >
            <Command className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
            <kbd className="text-[9px] bg-slate-900 border border-slate-700/80 px-1 py-0.2 rounded text-slate-400">
              ⌘K
            </kbd>
          </button>
        )}

        {/* Settings Gear */}
        <button
          onClick={onOpenSettings}
          className="p-1.5 rounded-lg bg-[#0f1623] hover:bg-[#162032] border border-slate-800 text-slate-400 hover:text-white transition shrink-0"
          title="Open Settings & Broker Profiles"
        >
          <Sliders className="w-3.5 h-3.5 shrink-0" />
        </button>
      </div>

      {/* Confirmation Modal: Account Switch */}
      {showSwitchConfirm && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 select-text">
          <div className="bg-[#0f1623] border border-slate-700 rounded-xl p-5 max-w-sm w-full shadow-2xl space-y-4">
            <h3 className="text-sm font-bold text-white font-mono flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <span>Switch Account Profile</span>
            </h3>
            <p className="text-xs text-slate-300">
              Are you sure you want to switch active account to{" "}
              <strong className={targetAccount === "LIVE" ? "text-rose-400" : "text-cyan-400"}>
                {targetAccount}
              </strong>
              ?
            </p>
            <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                onClick={() => setShowSwitchConfirm(false)}
                className="px-3 py-1.5 text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={confirmAccountSwitch}
                disabled={isProcessing}
                className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold text-xs rounded font-mono disabled:opacity-50"
              >
                {isProcessing ? "Switching..." : "Confirm Switch"}
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
};
