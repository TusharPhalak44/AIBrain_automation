import React, { useState } from "react";
import {
  LayoutDashboard,
  Brain,
  Code2,
  BookOpen,
} from "lucide-react";
import { useLiveStore } from "./hooks/useLiveStore";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { TopCommandBar } from "./components/TopCommandBar";
import { CockpitTab } from "./components/tabs/CockpitTab";
import { AIBrainTab } from "./components/tabs/AIBrainTab";
import { StrategyLabTab } from "./components/tabs/StrategyLabTab";
import { TradeBookTab } from "./components/tabs/TradeBookTab";
import { SettingsModal } from "./components/tabs/SettingsModal";
import { ToastProvider, useToast } from "./components/Toast";

type ActiveTab = "COCKPIT" | "AI_SUPERVISOR" | "STRATEGY_LAB" | "TRADE_BOOK";

const AppContent: React.FC = () => {
  const store = useLiveStore();
  const [currentTab, setCurrentTab] = useState<ActiveTab>("COCKPIT");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const toast = useToast();

  const handlePanicFlatten = async () => {
    try {
      const res = await store.panicFlatten();
      toast.warning("Panic Flatten Executed", res.message || "All positions flattened.");
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

  return (
    <div className="min-h-screen bg-[#0B0E14] text-slate-100 flex flex-col font-sans">
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
        onSwitchAccount={handleSwitchAccount}
        onSwitchMode={handleSwitchMode}
        onPanicFlatten={handlePanicFlatten}
        onOpenSettings={() => setIsSettingsOpen(true)}
      />

      {/* Primary Navigation Ribbon */}
      <nav className="bg-[#0E131D] border-b border-slate-800/80 px-4 flex items-center justify-between text-xs font-semibold">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setCurrentTab("COCKPIT")}
            className={`flex items-center gap-2 py-3 px-4 border-b-2 transition ${
              currentTab === "COCKPIT"
                ? "border-blue-500 text-blue-400 font-bold bg-blue-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <LayoutDashboard className="w-4 h-4" />
            <span>TERMINAL COCKPIT</span>
          </button>

          <button
            onClick={() => setCurrentTab("AI_SUPERVISOR")}
            className={`flex items-center gap-2 py-3 px-4 border-b-2 transition ${
              currentTab === "AI_SUPERVISOR"
                ? "border-blue-500 text-blue-400 font-bold bg-blue-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Brain className="w-4 h-4" />
            <span>GEMINI SUPERVISOR & RULES</span>
          </button>

          <button
            onClick={() => setCurrentTab("STRATEGY_LAB")}
            className={`flex items-center gap-2 py-3 px-4 border-b-2 transition ${
              currentTab === "STRATEGY_LAB"
                ? "border-blue-500 text-blue-400 font-bold bg-blue-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Code2 className="w-4 h-4" />
            <span>STRATEGY LAB & $100 TESTER</span>
          </button>

          <button
            onClick={() => setCurrentTab("TRADE_BOOK")}
            className={`flex items-center gap-2 py-3 px-4 border-b-2 transition ${
              currentTab === "TRADE_BOOK"
                ? "border-blue-500 text-blue-400 font-bold bg-blue-950/20"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>TRADE BOOK & FORENSICS</span>
          </button>
        </div>

        {/* Selected Pair Indicator */}
        <div className="hidden sm:flex items-center gap-2 text-slate-400 text-xs">
          <span>Active Instrument:</span>
          <span className="font-bold text-white bg-slate-900 border border-slate-800 px-2.5 py-0.5 rounded font-mono">
            {store.selectedSymbol} ({store.selectedTimeframe})
          </span>
        </div>
      </nav>

      {/* Main Workspace Area Wrapped in ErrorBoundary */}
      <main className="flex-1 p-4 overflow-y-auto">
        <ErrorBoundary>
          {currentTab === "COCKPIT" && (
            <CockpitTab
              selectedSymbol={store.selectedSymbol}
              selectedTimeframe={store.selectedTimeframe}
              isMt5Connected={store.isMt5Connected}
              openPositions={store.openPositions}
              plannedTrades={store.plannedTrades}
              pairSchedules={store.pairSchedules}
              quotes={store.quotes}
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

          {currentTab === "STRATEGY_LAB" && (
            <StrategyLabTab selectedSymbol={store.selectedSymbol} />
          )}

          {currentTab === "TRADE_BOOK" && <TradeBookTab />}
        </ErrorBoundary>
      </main>

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


