import React, { useState, useEffect, useCallback } from "react";
import { useLiveStore } from "./hooks/useLiveStore";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { TopCommandBar } from "./components/TopCommandBar";
import { LeftNavRail, NavWorkspace } from "./components/common/LeftNavRail";
import { CockpitTab } from "./components/tabs/CockpitTab";
import { AIBrainTab } from "./components/tabs/AIBrainTab";
import { TradeBookTab } from "./components/tabs/TradeBookTab";
import { UsageAnalyticsTab } from "./components/tabs/UsageAnalyticsTab";
import { RiskPairSettingsTab } from "./components/tabs/RiskPairSettingsTab";
import { SettingsModal } from "./components/tabs/SettingsModal";
import { QuickSymbolSwitcher } from "./components/common/QuickSymbolSwitcher";
import { ToastProvider, useToast } from "./components/Toast";
import { getInstrument, getSymbolSession } from "./constants/instruments";
import { api } from "./services/api";

const AppContent: React.FC = () => {
  const store = useLiveStore();
  const [currentWorkspace, setCurrentWorkspace] = useState<NavWorkspace>("COCKPIT");
  const [isRailCollapsed, setIsRailCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("xm_nav_rail_collapsed") === "true";
  });
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isQuickSwitcherOpen, setIsQuickSwitcherOpen] = useState(false);
  const [guardrails, setGuardrails] = useState<any>(null);
  const [liveRulesCount, setLiveRulesCount] = useState<number>(171);
  const toast = useToast();

  const handleToggleRail = () => {
    setIsRailCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("xm_nav_rail_collapsed", String(next));
      return next;
    });
  };

  const fetchGuardrails = useCallback(async () => {
    try {
      const [grRes, rulesRes] = await Promise.all([
        api.ai.getRiskGuardrails(),
        api.ai.getRulesVault().catch(() => null),
      ]);
      if (grRes) setGuardrails(grRes);
      if (rulesRes && typeof rulesRes.live_count === "number") {
        setLiveRulesCount(rulesRes.live_count);
      }
    } catch {
      // ignore background error
    }
  }, []);

  useEffect(() => {
    fetchGuardrails();
    const iv = setInterval(fetchGuardrails, 6000);
    return () => clearInterval(iv);
  }, [fetchGuardrails]);

  const handleScanNow = async () => {
    try {
      const res = await api.ai.scanAll();
      toast.info("Autonomous Scan Triggered", res?.message || "14-pair market packet evaluation dispatched.");
    } catch (e: any) {
      toast.error("Scan Failed", e.message || String(e));
    }
  };

  const handleReconcileMT5 = async () => {
    try {
      const res = await api.ai.reconcileMT5();
      toast.success("MT5 Reconciled", res?.message || "All positions synchronized with MT5 deals.");
      store.fetchLiveSnapshot();
      fetchGuardrails();
    } catch (e: any) {
      toast.error("Reconcile Failed", e.message || String(e));
    }
  };

  // Global Keyboard shortcut listener for Ctrl+K Quick Command Palette
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
  const activeSessionTag = guardrails?.active_session || getSymbolSession(store.selectedSymbol);
  const pairSched = store.pairSchedules[store.selectedSymbol];
  const nextScanSec = guardrails?.next_scan_seconds ?? pairSched?.next_scan_seconds ?? pairSched?.seconds_remaining ?? 180;

  return (
    <div className="h-screen w-screen bg-[#080c14] text-slate-100 flex flex-col font-sans selection:bg-cyan-500/30 overflow-hidden">
      {/* Tier-1 Persistent Top Command & Safety Header */}
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
        openExposureCount={guardrails?.open_positions_count ?? store.openPositions.length}
        activeSession={activeSessionTag}
        nextScanSeconds={nextScanSec}
        onSwitchAccount={handleSwitchAccount}
        onSwitchMode={handleSwitchMode}
        onPanicFlatten={handlePanicFlatten}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenQuickSwitcher={() => setIsQuickSwitcherOpen(true)}
        onScanNow={handleScanNow}
        onReconcileMT5={handleReconcileMT5}
        circuitBreakerStatus={guardrails?.circuit_breaker}
        openRiskPct={guardrails?.open_risk_pct}
      />

      {/* Main App Container: Left Navigation Rail + Active Workspace View */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Persistent Collapsible Left Navigation Rail */}
        <LeftNavRail
          currentWorkspace={currentWorkspace}
          onSelectWorkspace={setCurrentWorkspace}
          isCollapsed={isRailCollapsed}
          onToggleCollapse={handleToggleRail}
          liveRulesCount={liveRulesCount}
          openPositionsCount={store.openPositions.length}
          isMt5Connected={store.isMt5Connected}
          dbHealthy={store.dbHealthy}
          isWsConnected={store.isWsConnected}
        />

        {/* Center / Main Scrollable Content Area */}
        <main className="flex-1 overflow-y-auto p-3.5 bg-[#080c14] focus:outline-none">
          <ErrorBoundary>
            {/* Workspace 1: Terminal Cockpit */}
            {currentWorkspace === "COCKPIT" && (
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

            {/* Workspace 2: AI Brain & Rules */}
            {currentWorkspace === "AI_SUPERVISOR" && (
              <AIBrainTab
                selectedSymbol={store.selectedSymbol}
                pairSchedules={store.pairSchedules}
              />
            )}

            {/* Workspace 3: Trade Book & Forensics */}
            {currentWorkspace === "TRADE_BOOK" && <TradeBookTab />}

            {/* Workspace 4: Performance Analytics */}
            {currentWorkspace === "PERFORMANCE" && <UsageAnalyticsTab />}

            {/* Workspace 5: Risk & Pair Settings */}
            {currentWorkspace === "RISK_SETTINGS" && (
              <RiskPairSettingsTab
                onOpenAdvancedSettings={() => setIsSettingsOpen(true)}
                isMt5Connected={store.isMt5Connected}
                dbHealthy={store.dbHealthy}
              />
            )}
          </ErrorBoundary>
        </main>
      </div>

      {/* Quick Command & Pair Palette Modal (Ctrl+K / ⌘K) */}
      <QuickSymbolSwitcher
        isOpen={isQuickSwitcherOpen}
        onClose={() => setIsQuickSwitcherOpen(false)}
        selectedSymbol={store.selectedSymbol}
        onSelectSymbol={store.setSelectedSymbol}
        onSelectWorkspace={setCurrentWorkspace}
        quotes={store.quotes}
      />

      {/* Advanced MT5 Broker & Database Settings Modal */}
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
