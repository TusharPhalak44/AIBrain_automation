import React, { useState } from "react";
import {
  ShieldAlert,
  Sliders,
  Power,
  RefreshCw,
  Database,
  Radio,
  AlertTriangle,
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
  onSwitchAccount: (type: string) => Promise<any>;
  onSwitchMode: (mode: string) => Promise<any>;
  onPanicFlatten: () => Promise<any>;
  onOpenSettings: () => void;
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
  onSwitchAccount,
  onSwitchMode,
  onPanicFlatten,
  onOpenSettings,
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
      ? "bg-red-500 text-red-400"
      : marginUsagePct >= 12.0
      ? "bg-amber-500 text-amber-400"
      : "bg-emerald-500 text-emerald-400";

  // Color logic for Daily DD (Limit 2.5%)
  const dailyDdColor =
    dailyDdPct >= 2.5
      ? "bg-red-500 text-red-400"
      : dailyDdPct >= 1.5
      ? "bg-amber-500 text-amber-400"
      : "bg-blue-500 text-blue-400";

  return (
    <header className="border-b border-slate-800 bg-[#0d131f] px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
      {/* Left: Branding & Connection Status */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-600/20 border border-blue-500/40 flex items-center justify-center font-black text-blue-400 tracking-wider text-sm">
            XM
          </div>
          <div>
            <div className="font-bold text-slate-100 tracking-wide flex items-center gap-1.5 text-sm">
              <span>PORTAL V2</span>
              <span className="text-[10px] bg-blue-950 text-blue-400 px-1.5 py-0.5 rounded border border-blue-800">
                PRO
              </span>
            </div>
            <div className="text-[10px] text-slate-400">Institutional MT5 Terminal</div>
          </div>
        </div>

        {/* Status Indicators */}
        <div className="hidden lg:flex items-center gap-2 pl-2 border-l border-slate-800">
          <div
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold ${
              isMt5Connected
                ? "bg-emerald-950/60 text-emerald-400 border border-emerald-800/60"
                : "bg-red-950/60 text-red-400 border border-red-800/60 animate-pulse"
            }`}
          >
            <Radio className="w-3 h-3" />
            <span>{isMt5Connected ? "MT5 ONLINE" : "MT5 OFFLINE"}</span>
          </div>

          <div
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold ${
              dbHealthy
                ? "bg-slate-800/80 text-slate-300 border border-slate-700"
                : "bg-red-950 text-red-400 border border-red-800"
            }`}
          >
            <Database className="w-3 h-3" />
            <span>XAMPP MySQL</span>
          </div>

          <div
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold ${
              isWsConnected
                ? "bg-blue-950/60 text-blue-400 border border-blue-800/60"
                : "bg-amber-950/60 text-amber-400 border border-amber-800/60"
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping" />
            <span>1s WS</span>
          </div>
        </div>
      </div>

      {/* Center: Real-time Account & Risk Locks */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Balance & Equity */}
        <div className="bg-slate-900/90 px-3 py-1 rounded-lg border border-slate-800 flex items-center gap-3">
          <div>
            <div className="text-[10px] text-slate-400 uppercase tracking-wider">Balance</div>
            <div className="font-bold text-slate-200 text-sm">{fmtUsd(balance)}</div>
          </div>
          <div className="h-6 w-px bg-slate-800" />
          <div>
            <div className="text-[10px] text-slate-400 uppercase tracking-wider">Equity</div>
            <div className="font-bold text-slate-100 text-sm">{fmtUsd(equity)}</div>
          </div>
          <div className="h-6 w-px bg-slate-800" />
          <div>
            <div className="text-[10px] text-slate-400 uppercase tracking-wider">Floating</div>
            <div
              className={`font-bold text-sm ${
                floatingPnl > 0
                  ? "text-emerald-400"
                  : floatingPnl < 0
                  ? "text-red-400"
                  : "text-slate-400"
              }`}
            >
              {fmtUsd(floatingPnl, true)}
            </div>
          </div>
        </div>

        {/* 18% Max Margin Usage Gauge */}
        <div className="bg-slate-900/90 px-3 py-1 rounded-lg border border-slate-800 min-w-[120px]">
          <div className="flex justify-between items-center text-[10px] text-slate-400 mb-1">
            <span>MARGIN CAP</span>
            <span className="font-bold">{fmtPct(marginUsagePct)} / 18.0%</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${marginColor.split(" ")[0]}`}
              style={{ width: `${Math.min((marginUsagePct / 18.0) * 100, 100)}%` }}
            />
          </div>
        </div>

        {/* Drawdown Risk Meters */}
        <div className="bg-slate-900/90 px-3 py-1 rounded-lg border border-slate-800 min-w-[120px]">
          <div className="flex justify-between items-center text-[10px] text-slate-400 mb-1">
            <span>DAILY DD</span>
            <span className="font-bold">{fmtPct(dailyDdPct)} / 2.5%</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${dailyDdColor.split(" ")[0]}`}
              style={{ width: `${Math.min((dailyDdPct / 2.5) * 100, 100)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Right: Controls, Account Switcher, Mode Selector & Emergency Panic */}
      <div className="flex items-center gap-2">
        {/* Account Switcher */}
        <div className="flex bg-slate-900 p-0.5 rounded-lg border border-slate-800">
          <button
            onClick={() => handleAccountSwitchClick("DEMO")}
            className={`px-2.5 py-1 rounded text-xs font-bold transition ${
              accountType === "DEMO"
                ? "bg-blue-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            DEMO
          </button>
          <button
            onClick={() => handleAccountSwitchClick("LIVE")}
            className={`px-2.5 py-1 rounded text-xs font-bold transition ${
              accountType === "LIVE"
                ? "bg-red-600 text-white shadow-sm animate-pulse"
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
          className={`border text-xs rounded-lg px-2.5 py-1 font-bold focus:outline-none transition ${
            executionMode === "AUTO"
              ? "bg-emerald-950/80 border-emerald-500/60 text-emerald-300 shadow-sm shadow-emerald-950"
              : "bg-amber-950/80 border-amber-500/60 text-amber-300"
          }`}
        >
          <option value="AUTO">🟢 AUTO (24/7 Autonomous Market + Limit)</option>
          <option value="HALTED">⏸️ PAUSED / HALTED</option>
        </select>

        {/* Emergency Panic Flatten Button */}
        <button
          onClick={() => setShowPanicConfirm(true)}
          className="flex items-center gap-1.5 px-3 py-1 bg-red-600/90 hover:bg-red-600 active:bg-red-700 text-white font-bold rounded-lg text-xs shadow-md shadow-red-950 transition"
          title="Emergency Panic Flatten: Close all open positions & cancel pending orders"
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          <span>PANIC FLATTEN</span>
        </button>

        {/* Settings Gear */}
        <button
          onClick={onOpenSettings}
          className="p-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 rounded-lg border border-slate-800 transition"
          title="Open Settings"
        >
          <Sliders className="w-4 h-4" />
        </button>
      </div>

      {/* Account Switch Safety Modal */}
      {showSwitchConfirm && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#121824] border border-amber-500/50 rounded-xl p-5 max-w-sm w-full shadow-2xl">
            <div className="flex items-center gap-2 text-amber-400 font-bold text-sm mb-3">
              <AlertTriangle className="w-5 h-5" />
              <span>Confirm Switch to {targetAccount} Account</span>
            </div>
            <p className="text-slate-300 text-xs mb-4">
              Are you sure you want to switch active trading context to{" "}
              <strong className="text-white">{targetAccount}</strong>?
              {targetAccount === "LIVE" && (
                <span className="block mt-2 text-red-400 font-semibold">
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
                  targetAccount === "LIVE" ? "bg-red-600 hover:bg-red-500" : "bg-blue-600 hover:bg-blue-500"
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
          <div className="bg-[#151016] border border-red-500 rounded-xl p-6 max-w-md w-full shadow-2xl">
            <div className="flex items-center gap-3 text-red-400 font-bold text-base mb-3">
              <ShieldAlert className="w-6 h-6" />
              <span>EMERGENCY PANIC FLATTEN</span>
            </div>
            <p className="text-slate-300 text-xs leading-relaxed mb-4">
              This will instantly dispatch <strong className="text-white">P0 Emergency Panic Flatten</strong> to
              the XM Global MT5 terminal. All active market positions across all instruments will be closed immediately,
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
                className="px-4 py-2 bg-red-600 hover:bg-red-500 active:bg-red-700 text-white text-xs font-bold rounded-lg shadow-lg"
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

