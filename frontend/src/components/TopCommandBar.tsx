import React, { useState } from "react";
import {
  ShieldAlert,
  Sliders,
  Power,
  RefreshCw,
  Database,
  Radio,
  AlertTriangle,
  Command,
  Clock,
  Layers,
  Globe,
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
  activeSession = "London / NY",
  nextScanSeconds,
  onSwitchAccount,
  onSwitchMode,
  onPanicFlatten,
  onOpenSettings,
  onOpenQuickSwitcher,
}) => {
  const [showPanicConfirm, setShowPanicConfirm] = useState(false);
  const [showSwitchConfirm, setShowSwitchConfirm] = useState(false);
  const [targetAccount, setTargetAccount] = useState<string>("");
  const [isProcessing, setIsProcessing] = useState(false);

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

  // Color logic for Margin Usage (Cap 18%)
  const marginColor =
    marginUsagePct >= 18.0
      ? "bg-rose-500 text-rose-400"
      : marginUsagePct >= 12.0
      ? "bg-amber-500 text-amber-400"
      : "bg-emerald-500 text-emerald-400";

  // Color logic for Daily DD (Limit 2.5%)
  const dailyDdColor =
    dailyDdPct >= 2.5
      ? "bg-rose-500 text-rose-400"
      : dailyDdPct >= 1.5
      ? "bg-amber-500 text-amber-400"
      : "bg-cyan-500 text-cyan-400";

  return (
    <header className="border-b border-slate-800/80 bg-[#080c14] px-4 py-2 flex flex-wrap items-center justify-between gap-3 text-xs shadow-md">
      {/* Left: Branding, Telemetry & Status Indicators */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-cyan-600/20 border border-cyan-500/40 flex items-center justify-center font-black text-cyan-400 tracking-wider text-xs shadow-[0_0_12px_rgba(6,182,212,0.2)]">
            XM
          </div>
          <div>
            <div className="font-bold text-slate-100 tracking-wide flex items-center gap-1.5 text-xs font-mono">
              <span>PORTAL V2</span>
              <span className="text-[9px] bg-cyan-950 text-cyan-400 px-1 py-0.2 rounded border border-cyan-800/60 font-semibold">
                PRO 14P
              </span>
            </div>
            <div className="text-[10px] text-slate-400 font-mono">Ultra Low · Zero Fake</div>
          </div>
        </div>

        {/* Status Indicators */}
        <div className="hidden lg:flex items-center gap-2 pl-2 border-l border-slate-800/80">
          {/* MT5 Connection Pulse */}
          <div
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-mono font-semibold transition ${
              isMt5Connected
                ? "bg-emerald-950/60 text-emerald-400 border border-emerald-800/60"
                : "bg-rose-950/60 text-rose-400 border border-rose-800/60 animate-pulse"
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isMt5Connected
                  ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.9)]"
                  : "bg-rose-400"
              }`}
            />
            <span>{isMt5Connected ? "MT5 CONNECTED" : "MT5 OFFLINE"}</span>
          </div>

          {/* Database Pulse */}
          <div
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold ${
              dbHealthy
                ? "bg-slate-900 text-slate-300 border border-slate-800"
                : "bg-rose-950 text-rose-400 border border-rose-800"
            }`}
          >
            <Database className="w-3 h-3 text-slate-400" />
            <span>MySQL</span>
          </div>

          {/* 1s WebSocket */}
          <div
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold ${
              isWsConnected
                ? "bg-cyan-950/50 text-cyan-400 border border-cyan-800/40"
                : "bg-amber-950/50 text-amber-400 border border-amber-800/40"
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
            <span>1s WS</span>
          </div>

          {/* Global Session Indicator */}
          <div className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-slate-900/90 text-indigo-300 border border-indigo-900/50">
            <Globe className="w-3 h-3 text-indigo-400" />
            <span>{activeSession}</span>
          </div>

          {/* Next AI Scan countdown */}
          {nextScanSeconds !== undefined && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono bg-slate-900/90 text-slate-400 border border-slate-800">
              <Clock className="w-3 h-3 text-cyan-400" />
              <span className="tabular-nums">Scan: {nextScanSeconds}s</span>
            </div>
          )}
        </div>
      </div>

      {/* Center: Real-time Account & Risk Locks (Monospace Tabular) */}
      <div className="flex flex-wrap items-center gap-2.5">
        {/* Balance & Equity */}
        <div className="bg-[#0f1623] px-3 py-1 rounded-lg border border-slate-800 flex items-center gap-3">
          <div>
            <div className="text-[9px] text-slate-400 uppercase tracking-wider font-mono">Balance</div>
            <div className="font-bold text-slate-200 text-xs font-mono tabular-nums">{fmtUsd(balance)}</div>
          </div>
          <div className="h-6 w-px bg-slate-800" />
          <div>
            <div className="text-[9px] text-slate-400 uppercase tracking-wider font-mono">Equity</div>
            <div className="font-bold text-slate-100 text-xs font-mono tabular-nums">{fmtUsd(equity)}</div>
          </div>
          <div className="h-6 w-px bg-slate-800" />
          <div>
            <div className="text-[9px] text-slate-400 uppercase tracking-wider font-mono">Floating P&L</div>
            <div
              className={`font-bold text-xs font-mono tabular-nums ${
                floatingPnl > 0
                  ? "text-emerald-400"
                  : floatingPnl < 0
                  ? "text-rose-400"
                  : "text-slate-400"
              }`}
            >
              {fmtUsd(floatingPnl, true)}
            </div>
          </div>
        </div>

        {/* Open Exposure count */}
        {openExposureCount > 0 && (
          <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-950/40 border border-indigo-800/50 text-[10px] font-mono text-indigo-300">
            <Layers className="w-3 h-3" />
            <span className="tabular-nums font-bold">{openExposureCount} Open</span>
          </div>
        )}

        {/* 18% Max Margin Usage Gauge */}
        <div className="bg-[#0f1623] px-2.5 py-1 rounded-lg border border-slate-800 min-w-[110px]">
          <div className="flex justify-between items-center text-[9px] text-slate-400 mb-0.5 font-mono">
            <span>MARGIN CAP</span>
            <span className="font-bold tabular-nums">{fmtPct(marginUsagePct)} / 18%</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-1 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${marginColor.split(" ")[0]}`}
              style={{ width: `${Math.min((marginUsagePct / 18.0) * 100, 100)}%` }}
            />
          </div>
        </div>

        {/* Drawdown Risk Meter */}
        <div className="bg-[#0f1623] px-2.5 py-1 rounded-lg border border-slate-800 min-w-[110px]">
          <div className="flex justify-between items-center text-[9px] text-slate-400 mb-0.5 font-mono">
            <span>DAILY DD</span>
            <span className="font-bold tabular-nums">{fmtPct(dailyDdPct)} / 2.5%</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-1 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${dailyDdColor.split(" ")[0]}`}
              style={{ width: `${Math.min((dailyDdPct / 2.5) * 100, 100)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Right: Quick Switcher, Mode Selector, Account Switcher & Panic Flatten */}
      <div className="flex items-center gap-2">
        {/* Quick Pair Switcher Button (Ctrl+K) */}
        {onOpenQuickSwitcher && (
          <button
            onClick={onOpenQuickSwitcher}
            className="hidden md:flex items-center gap-1.5 px-2 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700/80 text-slate-300 hover:text-white transition font-mono text-[11px]"
            title="Open Quick Pair Switcher (Ctrl+K)"
          >
            <Command className="w-3 h-3 text-cyan-400" />
            <span>14 Pairs</span>
            <kbd className="text-[9px] bg-slate-800 px-1 py-0.2 rounded border border-slate-700 text-slate-400">
              Ctrl+K
            </kbd>
          </button>
        )}

        {/* Account Switcher */}
        <div className="flex bg-slate-900 p-0.5 rounded-lg border border-slate-800">
          <button
            onClick={() => handleAccountSwitchClick("DEMO")}
            className={`px-2 py-0.5 rounded text-[11px] font-bold font-mono transition ${
              accountType === "DEMO"
                ? "bg-cyan-600 text-slate-950 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            DEMO
          </button>
          <button
            onClick={() => handleAccountSwitchClick("LIVE")}
            className={`px-2 py-0.5 rounded text-[11px] font-bold font-mono transition ${
              accountType === "LIVE"
                ? "bg-rose-600 text-white shadow-sm animate-pulse"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            LIVE
          </button>
        </div>

        {/* Execution Mode: Strictly AUTO vs PAUSED/HALTED */}
        <select
          value={executionMode === "HALTED" ? "HALTED" : "AUTO"}
          onChange={(e) => onSwitchMode(e.target.value)}
          className={`border text-[11px] rounded-lg px-2 py-1 font-bold font-mono focus:outline-none transition ${
            executionMode === "AUTO"
              ? "bg-emerald-950/80 border-emerald-500/60 text-emerald-300"
              : "bg-amber-950/80 border-amber-500/60 text-amber-300"
          }`}
        >
          <option value="AUTO">🟢 AUTO (Market + Limit)</option>
          <option value="HALTED">⏸️ PAUSED / HALTED</option>
        </select>

        {/* Emergency Panic Flatten Button */}
        <button
          onClick={() => setShowPanicConfirm(true)}
          className="flex items-center gap-1.5 px-2.5 py-1 bg-rose-600 hover:bg-rose-500 active:bg-rose-700 text-white font-bold rounded-lg text-[11px] font-mono shadow-md shadow-rose-950 transition"
          title="Emergency Panic Flatten: Close all open positions & cancel pending orders"
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          <span>FLATTEN</span>
        </button>

        {/* Settings Gear */}
        <button
          onClick={onOpenSettings}
          className="p-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 rounded-lg border border-slate-800 transition"
          title="Open Settings"
        >
          <Sliders className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Account Switch Safety Modal */}
      {showSwitchConfirm && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#0f1623] border border-amber-500/50 rounded-xl p-5 max-w-sm w-full shadow-2xl">
            <div className="flex items-center gap-2 text-amber-400 font-bold text-sm mb-3">
              <AlertTriangle className="w-5 h-5" />
              <span>Confirm Switch to {targetAccount} Account</span>
            </div>
            <p className="text-slate-300 text-xs mb-4">
              Are you sure you want to switch active trading context to{" "}
              <strong className="text-white">{targetAccount}</strong>?
              {targetAccount === "LIVE" && (
                <span className="block mt-2 text-rose-400 font-semibold">
                  WARNING: Live real money execution rules and hard risk gates will apply.
                </span>
              )}
            </p>
            <div className="flex justify-end gap-2">
              <button
                disabled={isProcessing}
                onClick={() => setShowSwitchConfirm(false)}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded-lg"
              >
                Cancel
              </button>
              <button
                disabled={isProcessing}
                onClick={confirmAccountSwitch}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg text-white ${
                  targetAccount === "LIVE" ? "bg-rose-600 hover:bg-rose-500" : "bg-cyan-600 hover:bg-cyan-500"
                }`}
              >
                {isProcessing ? "Switching..." : `Confirm Switch`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Panic Flatten Safety Confirmation Modal */}
      {showPanicConfirm && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#150f14] border border-rose-500 rounded-xl p-6 max-w-md w-full shadow-2xl">
            <div className="flex items-center gap-3 text-rose-400 font-bold text-base mb-3">
              <ShieldAlert className="w-6 h-6" />
              <span>EMERGENCY PANIC FLATTEN</span>
            </div>
            <p className="text-slate-300 text-xs leading-relaxed mb-4">
              This will instantly dispatch <strong className="text-white">P0 Emergency Panic Flatten</strong> to
              the XM Global MT5 terminal. All active market positions across all 14 instruments will be closed immediately,
              and all pending orders deleted.
            </p>
            <div className="flex justify-end gap-2">
              <button
                disabled={isProcessing}
                onClick={() => setShowPanicConfirm(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg"
              >
                Cancel
              </button>
              <button
                disabled={isProcessing}
                onClick={handlePanicClick}
                className="px-4 py-2 bg-rose-600 hover:bg-rose-500 active:bg-rose-700 text-white text-xs font-bold rounded-lg shadow-lg"
              >
                {isProcessing ? "FLATTENING ALL..." : "EXECUTE PANIC FLATTEN"}
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
};
