import React, { useState, useEffect } from "react";
import {
  LayoutDashboard,
  Brain,
  BookOpen,
  BarChart3,
  FlaskConical,
  Command,
} from "lucide-react";
import { useLiveStore } from "./hooks/useLiveStore";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { TopCommandBar } from "./components/TopCommandBar";
import { CockpitTab } from "./components/tabs/CockpitTab";
import { AIBrainTab } from "./components/tabs/AIBrainTab";
import { TradeBookTab } from "./components/tabs/TradeBookTab";
import { StrategyLabTab } from "./components/tabs/StrategyLabTab";
import { UsageAnalyticsTab } from "./components/tabs/UsageAnalyticsTab";
import { SettingsModal } from "./components/tabs/SettingsModal";
import { QuickSymbolSwitcher } from "./components/common/QuickSymbolSwitcher";
import { ToastProvider, useToast } from "./components/Toast";
import { getInstrument, getSymbolSession } from "./constants/instruments";

type ActiveTab = "COCKPIT" | "AI_SUPERVISOR" | "TRADE_BOOK" | "STRATEGY_LAB" | "USAGE_BILLING";

const AppContent: React.FC = () => {
  const store = useLiveStore();
  const [currentTab, setCurrentTab] = useState<ActiveTab>("COCKPIT");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isQuickSwitcherOpen, setIsQuickSwitcherOpen] = useState(false);
  const toast = useToast();

  // Keyboard shortcut listener for Ctrl+K Quick Switcher
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setIsQuickSwitcherOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handlePanicFlatten = async () => {
    try {
      const res = await store.panicFlatten();
      toast.warning("Panic Flatten Executed", res.message || "All positions flattened across 14 pairs.");
    } catch (e: any) {
      toast.error("Panic Flatten Failed", e.message || String(e));
    }
  };

  const handleSwitchAccount = async (type: string) => {
    try {
      const res = await store.switchAccount(type);
      toast.success("Account Switched", `Switched to ${type} account successfully.`);
    } catch (e: any) {
      toast.error("Switch Account Failed", e.message || String(e));
    }
  };

  const handleSwitchMode = async (mode: string) => {
    try {
      await store.switchMode(mode);
      toast.info("Execution Mode Changed", `Execution mode set to ${mode}.`);
    } catch (e: any) {
      toast.error("Mode Change Failed", e.message || String(e));
    }
  };

  const activeInst = getInstrument(store.selectedSymbol);
  const activeSessionTag = getSymbolSession(store.selectedSymbol);
  const pairSched = store.pairSchedules[store.selectedSymbol];
  const nextScanSec = pairSched?.next_scan_seconds ?? pairSched?.seconds_remaining;

  return (
    <div className="min-h-screen bg-[#080c14] text-slate-100 flex flex-col font-sans selection:bg-cyan-500/30">
      {/* Top Fixed Command & Risk Bar */}
      <TopCommandBar
        accountType={store.accountType}
        executionMode={store.executionMode}
        isMt5Connected={store.isMt5Connected}
        dbHealthy={store.dbHealthy}
        isWsConnected={store.isWsConnected}
        balance={store.balance}
        equity={store.equity}
        floatingPnl={store.floatingPnl}
        marginUsagePct={store.marginUsagePct}
        dailyDdPct={store.dailyDdPct}
        weeklyDdPct={store.weeklyDdPct}
        riskState={store.riskState}
        openExposureCount={store.openPositions.length}
        activeSession={activeSessionTag}
        nextScanSeconds={nextScanSec}
        onSwitchAccount={handleSwitchAccount}
        onSwitchMode={handleSwitchMode}
        onPanicFlatten={handlePanicFlatten}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenQuickSwitcher={() => setIsQuickSwitcherOpen(true)}
      />

      {/* Primary Navigation Ribbon */}
      <nav className="bg-[#0b101b] border-b border-slate-800/80 px-4 flex items-center justify-between text-xs font-semibold">
        <div className="flex items-center gap-1 overflow-x-auto scrollbar-none">
          <button
            onClick={() => setCurrentTab("COCKPIT")}
            className={`flex items-center gap-2 py-2.5 px-3.5 border-b-2 transition font-mono ${
              currentTab === "COCKPIT"
                ? "border-cyan-500 text-cyan-400 font-bold bg-cyan-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <LayoutDashboard className="w-4 h-4" />
            <span>TERMINAL COCKPIT</span>
          </button>

          <button
            onClick={() => setCurrentTab("AI_SUPERVISOR")}
            className={`flex items-center gap-2 py-2.5 px-3.5 border-b-2 transition font-mono ${
              currentTab === "AI_SUPERVISOR"
                ? "border-cyan-500 text-cyan-400 font-bold bg-cyan-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Brain className="w-4 h-4" />
            <span>GEMINI SUPERVISOR & RULES</span>
          </button>

          <button
            onClick={() => setCurrentTab("TRADE_BOOK")}
            className={`flex items-center gap-2 py-2.5 px-3.5 border-b-2 transition font-mono ${
              currentTab === "TRADE_BOOK"
                ? "border-cyan-500 text-cyan-400 font-bold bg-cyan-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>TRADE BOOK & FORENSICS</span>
          </button>

          <button
            onClick={() => setCurrentTab("STRATEGY_LAB")}
            className={`flex items-center gap-2 py-2.5 px-3.5 border-b-2 transition font-mono ${
              currentTab === "STRATEGY_LAB"
                ? "border-cyan-500 text-cyan-400 font-bold bg-cyan-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <FlaskConical className="w-4 h-4" />
            <span>STRATEGY LAB & BACKTEST</span>
          </button>

          <button
            onClick={() => setCurrentTab("USAGE_BILLING")}
            className={`flex items-center gap-2 py-2.5 px-3.5 border-b-2 transition font-mono ${
              currentTab === "USAGE_BILLING"
                ? "border-cyan-500 text-cyan-400 font-bold bg-cyan-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <BarChart3 className="w-4 h-4" />
            <span>AI USAGE & BILLING</span>
          </button>
        </div>

        {/* Selected Pair Indicator + Ctrl+K shortcut */}
        <div className="hidden sm:flex items-center gap-2 text-slate-400 text-xs">
          <button
            onClick={() => setIsQuickSwitcherOpen(true)}
            className="flex items-center gap-2 px-2.5 py-1 rounded bg-[#0f1623] hover:bg-[#151f32] border border-slate-800 text-slate-300 transition group"
            title="Press Ctrl+K to change instrument"
          >
            <span className="text-[10px] text-slate-500 uppercase font-mono">Pair:</span>
            <span className="font-bold text-white font-mono group-hover:text-cyan-300">
              {activeInst.symbol}
            </span>
            <span className="text-[10px] text-cyan-400 font-mono">({store.selectedTimeframe})</span>
            <kbd className="text-[9px] bg-slate-900 border border-slate-700/80 px-1 rounded text-slate-400">
              ⌘K
            </kbd>
          </button>
        </div>
      </nav>

      {/* Main Workspace Area Wrapped in ErrorBoundary */}
      <main className="flex-1 p-3.5 overflow-y-auto">
        <ErrorBoundary>
          {currentTab === "COCKPIT" && (
            <CockpitTab
              selectedSymbol={store.selectedSymbol}
              selectedTimeframe={store.selectedTimeframe}
              isMt5Connected={store.isMt5Connected}
              executionMode={store.executionMode}
              openPositions={store.openPositions}
              pendingOrders={store.pendingOrders}
              plannedTrades={store.plannedTrades}
              pairSchedules={store.pairSchedules}
              quotes={store.quotes}
              equity={store.equity}
              balance={store.balance}
              onSelectSymbol={store.setSelectedSymbol}
              onSelectTimeframe={store.setSelectedTimeframe}
              onApproveCopilot={store.approveCopilot}
              onRejectCopilot={store.rejectCopilot}
            />
          )}

          {currentTab === "AI_SUPERVISOR" && (
            <AIBrainTab
              selectedSymbol={store.selectedSymbol}
              pairSchedules={store.pairSchedules}
            />
          )}

          {currentTab === "TRADE_BOOK" && <TradeBookTab />}

          {currentTab === "STRATEGY_LAB" && (
            <StrategyLabTab selectedSymbol={store.selectedSymbol} />
          )}

          {currentTab === "USAGE_BILLING" && <UsageAnalyticsTab />}
        </ErrorBoundary>
      </main>

      {/* Quick Pair Switcher Modal (Ctrl+K) */}
      <QuickSymbolSwitcher
        isOpen={isQuickSwitcherOpen}
        onClose={() => setIsQuickSwitcherOpen(false)}
        selectedSymbol={store.selectedSymbol}
        onSelectSymbol={store.setSelectedSymbol}
        quotes={store.quotes}
      />

      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        isMt5Connected={store.isMt5Connected}
        dbHealthy={store.dbHealthy}
      />
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  );
};
