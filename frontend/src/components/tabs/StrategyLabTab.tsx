import React, { useState, useEffect } from "react";
import {
  Code,
  ShieldCheck,
  Play,
  Save,
  CheckCircle2,
  AlertCircle,
  FileCode,
  BarChart2,
  DollarSign,
  TrendingUp,
  TrendingDown,
  Trophy,
  BookmarkPlus,
  Trash2,
  UploadCloud,
  Check,
} from "lucide-react";
import { fmtUsd, fmtPct, safeArr } from "../../utils/format";
import { api } from "../../services/api";
import { useToast } from "../Toast";

interface StrategyLabTabProps {
  selectedSymbol: string;
}

export const StrategyLabTab: React.FC<StrategyLabTabProps> = ({
  selectedSymbol,
}) => {
  const [strategies, setStrategies] = useState<any[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(null);
  const [strategyCode, setStrategyCode] = useState<string>("");
  const [strategyName, setStrategyName] = useState<string>("My Custom Strategy");
  const [targetMode, setTargetMode] = useState<string>("BOTH");
  const toast = useToast();

  // AST Validation State
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    message?: string;
  } | null>(null);

  // Backtest State
  const [backtestSymbol, setBacktestSymbol] = useState(selectedSymbol);
  const [backtestTf, setBacktestTf] = useState("H1");
  const [testMode, setTestMode] = useState("ACCOUNT_100");
  const [barsCount, setBarsCount] = useState(500);
  const [riskPct, setRiskPct] = useState(1.0);
  const [isRunningBacktest, setIsRunningBacktest] = useState(false);
  const [backtestResult, setBacktestResult] = useState<any | null>(null);

  // Saved Vault Leaderboard State
  const [savedVault, setSavedVault] = useState<any[]>([]);
  const [isSavingSnapshot, setIsSavingSnapshot] = useState(false);
  const [snapshotLabel, setSnapshotLabel] = useState("");
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeletingStrategy, setIsDeletingStrategy] = useState(false);
  const [isRestoringDefaults, setIsRestoringDefaults] = useState(false);

  useEffect(() => {
    fetchStrategies();
    fetchSavedVault();
  }, []);

  const fetchStrategies = async () => {
    try {
      const data = safeArr<any>(await api.strategies.list());
      setStrategies(data);
      if (data.length > 0 && selectedStrategyId === null) {
        setSelectedStrategyId(data[0].id);
        setStrategyCode(data[0].python_code);
        setStrategyName(data[0].name);
        setTargetMode(data[0].target_mode || "BOTH");
      }
    } catch (e: any) {
      console.error("Failed to load strategies:", e);
    }
  };

  const fetchSavedVault = async () => {
    try {
      const data = safeArr<any>(await api.strategies.getSavedVault());
      setSavedVault(data);
    } catch (e: any) {
      console.error("Failed to load saved vault:", e);
    }
  };

  const handleSelectStrategy = (id: number) => {
    const s = strategies.find((item) => item.id === id);
    if (s) {
      setSelectedStrategyId(s.id);
      setStrategyCode(s.python_code);
      setStrategyName(s.name);
      setTargetMode(s.target_mode || "BOTH");
      setValidationResult(null);
    }
  };

  const handleValidateAST = async () => {
    setIsValidating(true);
    try {
      const data = await api.strategies.validate(strategyCode);
      setValidationResult({
        valid: data.valid,
        message: data.message || data.error,
      });
      if (data.valid) {
        toast.success("AST Guard Passed", "Strategy syntax and AST security verified clean.");
      } else {
        toast.warning("AST Guard Blocked", data.message || data.error);
      }
    } catch (e: any) {
      setValidationResult({
        valid: false,
        message: e.message || "Failed to connect to AST validator",
      });
      toast.error("Validation Error", e.message || String(e));
    } finally {
      setIsValidating(false);
    }
  };

  const handleSaveStrategy = async () => {
    try {
      const res = await api.strategies.create({
        name: strategyName,
        target_mode: targetMode,
        python_code: strategyCode,
      });
      toast.success("Strategy Saved", `Strategy "${strategyName}" persisted to MySQL.`);
      fetchStrategies();
    } catch (e: any) {
      toast.error("Save Failed", e.message || String(e));
    }
  };

  const handleDeleteStrategy = async () => {
    if (!selectedStrategyId) return;
    setIsDeletingStrategy(true);
    try {
      await api.strategies.delete(selectedStrategyId);
      toast.success("Strategy Deleted", `Strategy #${selectedStrategyId} removed.`);
      setShowDeleteConfirm(false);
      setSelectedStrategyId(null);
      await fetchStrategies();
    } catch (e: any) {
      toast.error("Delete Failed", e.message || String(e));
    } finally {
      setIsDeletingStrategy(false);
    }
  };

  const handleRestoreDefaults = async () => {
    setIsRestoringDefaults(true);
    try {
      const res = await api.strategies.restoreDefaults();
      toast.success("Templates Restored", res.message || "Default starter strategies restored.");
      await fetchStrategies();
    } catch (e: any) {
      toast.error("Restore Failed", e.message || String(e));
    } finally {
      setIsRestoringDefaults(false);
    }
  };

  const handleRunBacktest = async () => {
    setIsRunningBacktest(true);
    setBacktestResult(null);
    try {
      const payload: any = {
        strategy_code: strategyCode,
        symbol: backtestSymbol,
        timeframe: backtestTf,
        test_mode: testMode,
        bars_count: barsCount,
        risk_pct: riskPct,
      };
      if (selectedStrategyId) {
        payload.strategy_id = selectedStrategyId;
      }

      const data = await api.strategies.backtest(payload);
      setBacktestResult(data);
      setSnapshotLabel(`${strategyName} - ${backtestSymbol} (${fmtPct(data.net_roi_pct, true)})`);
      toast.success("Backtest Completed", `${testMode} test on ${backtestSymbol} (${backtestTf}) finished.`);
    } catch (e: any) {
      toast.error("Backtest Failed", e.message || String(e));
    } finally {
      setIsRunningBacktest(false);
    }
  };

  const handleSaveSnapshot = async () => {
    if (!backtestResult) return;
    setIsSavingSnapshot(true);
    try {
      await api.strategies.saveSnapshot({
        backtest_run_id: backtestResult.backtest_run_id,
        strategy_id: selectedStrategyId || undefined,
        custom_label: snapshotLabel || `${strategyName} [${backtestSymbol}]`,
        symbol: backtestResult.symbol,
        timeframe: backtestResult.timeframe,
        test_mode: backtestResult.test_mode,
        strategy_code: strategyCode,
        metrics: backtestResult,
      });
      toast.success("Vault Snapshot Saved", `Strategy bookmarked into MySQL PnL Vault.`);
      setShowSaveModal(false);
      await fetchSavedVault();
    } catch (e: any) {
      toast.error("Bookmark Failed", e.message || String(e));
    } finally {
      setIsSavingSnapshot(false);
    }
  };

  const handleDeleteVaultItem = async (id: number) => {
    try {
      await api.strategies.deleteSavedVault(id);
      toast.info("Vault Entry Removed", `Snapshot #${id} deleted.`);
      await fetchSavedVault();
    } catch (e: any) {
      toast.error("Delete Failed", e.message || String(e));
    }
  };

  const handleLoadVaultCode = (item: any) => {
    if (item.strategy_code_snapshot) {
      setStrategyCode(item.strategy_code_snapshot);
      setStrategyName(item.custom_label || "Loaded Strategy");
      setBacktestSymbol(item.symbol);
      setBacktestTf(item.timeframe);
      toast.success("Strategy Loaded", `Loaded code snapshot for "${item.custom_label}" into editor.`);
    }
  };

  const handleAssignPairStrategy = async (symbol: string, strategyId: number, slot: "SCALP" | "SWING") => {
    try {
      const payload = slot === "SCALP" ? { scalp_strategy_id: strategyId } : { swing_strategy_id: strategyId };
      await api.pairs.assignStrategy(symbol, payload);
      toast.success("Strategy Assigned", `Assigned strategy #${strategyId} to ${symbol} as ${slot}.`);
    } catch (e: any) {
      toast.error("Assignment Failed", e.message || String(e));
    }
  };

  // Helper for mini SVG equity curve
  const renderMiniEquityCurve = (curve: any[]) => {
    if (!curve || curve.length < 2) return null;
    const values = curve.map((c) => Number(c.equity));
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const range = maxVal - minVal || 1.0;
    const width = 380;
    const height = 65;

    const points = values
      .map((val, idx) => {
        const x = (idx / (values.length - 1)) * width;
        const y = height - ((val - minVal) / range) * (height - 10) - 5;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

    const isPositive = values[values.length - 1] >= values[0];
    const strokeColor = isPositive ? "#34D399" : "#F87171";

    return (
      <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
        <div className="flex justify-between items-center text-[10px] text-slate-400 mb-1">
          <span className="font-semibold text-slate-300">Equity Curve ($100 Compounding)</span>
          <span className="font-mono">{fmtUsd(values[values.length - 1])}</span>
        </div>
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-16 overflow-visible">
          <polyline
            fill="none"
            stroke={strokeColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={points}
          />
        </svg>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Top Grid: Editor (7 cols) + Strategy Tester (5 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left: Strategy Code Editor & Security Verification (7 cols) */}
        <div className="lg:col-span-7 bg-[#121824] border border-slate-800 rounded-xl p-4 flex flex-col space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <Code className="w-5 h-5 text-blue-400" />
              <span className="font-bold text-white text-sm">PYTHON STRATEGY SANDBOX</span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <select
                value={selectedStrategyId || ""}
                onChange={(e) => handleSelectStrategy(Number(e.target.value))}
                className="bg-slate-900 border border-slate-800 text-slate-200 text-xs rounded-lg px-2.5 py-1 font-semibold"
              >
                {strategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.is_builtin ? "[Built-in] " : "[Custom] "}
                    {s.name} ({s.target_mode})
                  </option>
                ))}
              </select>

              <button
                onClick={() => setShowDeleteConfirm(true)}
                disabled={!selectedStrategyId}
                className="flex items-center gap-1 px-2.5 py-1 bg-red-950/60 hover:bg-red-900 border border-red-800 text-red-400 font-bold rounded-lg text-xs transition disabled:opacity-50"
                title="Delete Strategy"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Delete</span>
              </button>

              <button
                onClick={handleRestoreDefaults}
                disabled={isRestoringDefaults}
                className="flex items-center gap-1 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold rounded-lg text-xs transition disabled:opacity-50"
                title="Restore Default Starter Templates"
              >
                <span>{isRestoringDefaults ? "Restoring..." : "🔄 Restore Templates"}</span>
              </button>
            </div>
          </div>

          {/* Name & Target Mode */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <input
              type="text"
              value={strategyName}
              onChange={(e) => setStrategyName(e.target.value)}
              placeholder="Strategy Name"
              className="sm:col-span-2 bg-slate-900 border border-slate-800 text-slate-100 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-500"
            />
            <select
              value={targetMode}
              onChange={(e) => setTargetMode(e.target.value)}
              className="bg-slate-900 border border-slate-800 text-slate-200 text-xs rounded-lg px-2.5 py-1.5"
            >
              <option value="BOTH">BOTH (Scalp & Swing)</option>
              <option value="SCALP">SCALP</option>
              <option value="SWING">SWING</option>
            </select>
          </div>

          {/* Code Editor Area */}
          <div className="flex-1 min-h-[340px] relative">
            <textarea
              value={strategyCode}
              onChange={(e) => {
                setStrategyCode(e.target.value);
                setValidationResult(null);
              }}
              spellCheck={false}
              className="w-full h-full min-h-[340px] bg-[#0A0D13] text-emerald-300 font-mono text-xs p-3.5 rounded-lg border border-slate-800 focus:outline-none focus:border-blue-500/80 resize-none leading-relaxed"
            />
          </div>

          {/* Actions & AST Feedback */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <div className="flex items-center gap-2">
              <button
                disabled={isValidating}
                onClick={handleValidateAST}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold rounded-lg text-xs border border-slate-700 transition"
              >
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>{isValidating ? "Validating..." : "Validate AST"}</span>
              </button>
              <button
                onClick={handleSaveStrategy}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg text-xs shadow transition"
              >
                <Save className="w-4 h-4" />
                <span>Save Strategy</span>
              </button>
            </div>

            {validationResult && (
              <div
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-semibold ${
                  validationResult.valid
                    ? "bg-emerald-950/80 text-emerald-400 border border-emerald-800"
                    : "bg-red-950/80 text-red-400 border border-red-800"
                }`}
              >
                {validationResult.valid ? (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5" />
                )}
                <span>{validationResult.message}</span>
              </div>
            )}
          </div>
        </div>

        {/* Right: $100 Strategy Tester & Fee Accounting (5 cols) */}
        <div className="lg:col-span-5 bg-[#121824] border border-slate-800 rounded-xl p-4 flex flex-col space-y-3">
          <div className="border-b border-slate-800 pb-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BarChart2 className="w-5 h-5 text-emerald-400" />
              <span className="font-bold text-white text-sm">$100 STRATEGY TESTER</span>
            </div>
            <span className="text-[10px] text-slate-400 font-mono">XM Global Fee Model</span>
          </div>

          {/* Configuration Grid */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <label className="text-slate-400 block mb-0.5">Symbol</label>
              <select
                value={backtestSymbol}
                onChange={(e) => setBacktestSymbol(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-2 py-1.5 font-bold"
              >
                <option value="GOLD#">GOLD# (Spot Gold)</option>
                <option value="BTCUSD#">BTCUSD# (Bitcoin CFD)</option>
              </select>
            </div>

            <div>
              <label className="text-slate-400 block mb-0.5">Timeframe</label>
              <select
                value={backtestTf}
                onChange={(e) => setBacktestTf(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-2 py-1.5"
              >
                <option value="M5">M5</option>
                <option value="M15">M15</option>
                <option value="H1">H1</option>
                <option value="H4">H4</option>
                <option value="D1">D1</option>
              </select>
            </div>

            <div>
              <label className="text-slate-400 block mb-0.5">Mode</label>
              <select
                value={testMode}
                onChange={(e) => setTestMode(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-2 py-1.5"
              >
                <option value="ACCOUNT_100">$100 Realistic Account</option>
                <option value="PER_TRADE_100">$100 Per-Trade</option>
              </select>
            </div>

            <div>
              <label className="text-slate-400 block mb-0.5">Bars Count</label>
              <input
                type="number"
                min={100}
                max={1500}
                value={barsCount}
                onChange={(e) => setBarsCount(parseInt(e.target.value))}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-2 py-1.5"
              />
            </div>
          </div>

          {/* Run Backtest Button */}
          <button
            disabled={isRunningBacktest}
            onClick={handleRunBacktest}
            className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg text-xs shadow-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>{isRunningBacktest ? "Simulating Bar-by-Bar with MT5..." : "Run $100 Backtest"}</span>
          </button>

          {/* Backtest Results Panel */}
          {backtestResult && (
            <div className="bg-slate-900/90 rounded-xl p-3 border border-slate-800 space-y-2.5 text-xs">
              <div className="font-bold text-white flex items-center justify-between border-b border-slate-800 pb-2">
                <span className="flex items-center gap-1.5">
                  <span className="text-emerald-400">●</span>
                  <span>Results: {backtestResult.symbol} ({backtestResult.timeframe})</span>
                </span>
                <span
                  className={`font-mono font-bold text-sm ${
                    backtestResult.net_pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {fmtUsd(backtestResult.net_pnl_usd, true)} ({fmtPct(backtestResult.net_roi_pct, true)})
                </span>
              </div>

              {/* 6-Card KPI Grid */}
              <div className="grid grid-cols-3 gap-1.5 text-center">
                <div className="bg-slate-950 p-1.5 rounded-lg border border-slate-800/60">
                  <div className="text-[9px] text-slate-400 uppercase">Trades (W/L)</div>
                  <div className="font-bold text-slate-100 font-mono">
                    {backtestResult.total_trades} ({backtestResult.win_trades}W/{backtestResult.loss_trades}L)
                  </div>
                </div>
                <div className="bg-slate-950 p-1.5 rounded-lg border border-slate-800/60">
                  <div className="text-[9px] text-slate-400 uppercase">Win Rate</div>
                  <div className="font-bold text-emerald-400 font-mono">{fmtPct(backtestResult.win_rate_pct)}</div>
                </div>
                <div className="bg-slate-950 p-1.5 rounded-lg border border-slate-800/60">
                  <div className="text-[9px] text-slate-400 uppercase">Profit Factor</div>
                  <div className="font-bold text-blue-400 font-mono">{backtestResult.profit_factor}</div>
                </div>
                <div className="bg-slate-950 p-1.5 rounded-lg border border-slate-800/60">
                  <div className="text-[9px] text-slate-400 uppercase">Max DD</div>
                  <div className="font-bold text-red-400 font-mono">{fmtPct(backtestResult.max_dd_pct)}</div>
                </div>
                <div className="bg-slate-950 p-1.5 rounded-lg border border-slate-800/60">
                  <div className="text-[9px] text-slate-400 uppercase">Avg R-Mult</div>
                  <div className="font-bold text-slate-200 font-mono">{backtestResult.average_r_multiple}R</div>
                </div>
                <div className="bg-slate-950 p-1.5 rounded-lg border border-slate-800/60">
                  <div className="text-[9px] text-slate-400 uppercase">Ending Equity</div>
                  <div className="font-bold text-emerald-300 font-mono">
                    {fmtUsd(100.0 + backtestResult.net_pnl_usd)}
                  </div>
                </div>
              </div>

              {/* Mini SVG Equity Curve */}
              {renderMiniEquityCurve(backtestResult.equity_curve)}

              {/* XM Fee Breakdown */}
              <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/60 space-y-0.5 font-mono text-[10px]">
                <div className="text-[9px] text-slate-400 font-sans font-bold uppercase mb-1">
                  XM Global Brokerage Friction
                </div>
                <div className="flex justify-between text-slate-300">
                  <span>Gross PnL:</span>
                  <span>{fmtUsd(backtestResult.gross_pnl_usd, true)}</span>
                </div>
                <div className="flex justify-between text-amber-400">
                  <span>Bid/Ask Spread Cost:</span>
                  <span>-{fmtUsd(backtestResult.spread_cost_usd)}</span>
                </div>
                <div className="flex justify-between text-amber-400">
                  <span>Overnight Swap (3x Wed):</span>
                  <span>-{fmtUsd(backtestResult.swap_cost_usd)}</span>
                </div>
                <div className="flex justify-between text-slate-400">
                  <span>Commission:</span>
                  <span>-{fmtUsd(backtestResult.commission_cost_usd)}</span>
                </div>
              </div>

              {/* Action: Save Strategy + PnL Snapshot Button */}
              <button
                onClick={() => setShowSaveModal(true)}
                className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg text-xs shadow transition flex items-center justify-center gap-1.5"
              >
                <BookmarkPlus className="w-4 h-4" />
                <span>💾 Save Strategy + PnL Snapshot to Vault</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Save Snapshot Modal */}
      {showSaveModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-[#121824] border border-slate-800 rounded-xl max-w-md w-full p-4 space-y-3">
            <div className="flex justify-between items-center border-b border-slate-800 pb-2">
              <h4 className="font-bold text-white text-sm flex items-center gap-2">
                <BookmarkPlus className="w-4 h-4 text-blue-400" />
                <span>Save Strategy + PnL Snapshot</span>
              </h4>
              <button
                onClick={() => setShowSaveModal(false)}
                className="text-slate-400 hover:text-white text-xs"
              >
                ✕
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <label className="text-slate-400 block">Custom Benchmark Label</label>
              <input
                type="text"
                value={snapshotLabel}
                onChange={(e) => setSnapshotLabel(e.target.value)}
                placeholder="e.g. Gold Liquidity Sweep M15 (+42.5%)"
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-3 py-1.5"
              />
              <div className="text-[11px] text-slate-400">
                This bookmarks the current code, parameters, and backtest PnL metrics into your MySQL Leaderboard table.
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                onClick={() => setShowSaveModal(false)}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                disabled={isSavingSnapshot}
                onClick={handleSaveSnapshot}
                className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold shadow"
              >
                {isSavingSnapshot ? "Saving..." : "Save to Vault"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Strategy Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-[#121824] border border-red-800/80 rounded-xl max-w-sm w-full p-4 space-y-3">
            <h4 className="font-bold text-white text-sm flex items-center gap-2 text-red-400">
              <Trash2 className="w-4 h-4" />
              <span>Confirm Strategy Deletion</span>
            </h4>
            <p className="text-xs text-slate-300">
              Are you sure you want to delete strategy <strong className="text-white font-mono">"{strategyName}"</strong>? This will unassign it from active pair bots and unlink historical backtest runs.
            </p>
            <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                disabled={isDeletingStrategy}
                onClick={handleDeleteStrategy}
                className="px-4 py-1.5 bg-red-600 hover:bg-red-500 text-white rounded-lg text-xs font-bold shadow"
              >
                {isDeletingStrategy ? "Deleting..." : "Yes, Delete Strategy"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bottom Section: Saved Strategies & Tested PnL Vault (Leaderboard Table) */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-4 space-y-3">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Trophy className="w-5 h-5 text-amber-400" />
            <div>
              <h3 className="font-bold text-white text-sm">SAVED STRATEGIES & TESTED PNL VAULT</h3>
              <p className="text-[11px] text-slate-400">
                Persistent MySQL Leaderboard ({savedVault.length} Saved Snapshots). Rank, compare, and assign profitable strategies to live bots.
              </p>
            </div>
          </div>
          <button
            onClick={fetchSavedVault}
            className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg"
          >
            Refresh Vault
          </button>
        </div>

        {savedVault.length === 0 ? (
          <div className="text-slate-500 text-xs py-8 text-center">
            No saved strategy snapshots in the vault yet. Run a $100 backtest above and click "💾 Save Strategy + PnL Snapshot" to bookmark it here.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/80 text-[10px] text-slate-400 uppercase font-mono border-b border-slate-800">
                <tr>
                  <th className="py-2 px-3">Rank</th>
                  <th className="py-2 px-3">Strategy / Label</th>
                  <th className="py-2 px-3">Symbol</th>
                  <th className="py-2 px-3">TF</th>
                  <th className="py-2 px-3">Mode</th>
                  <th className="py-2 px-3">Net PnL</th>
                  <th className="py-2 px-3">Net ROI</th>
                  <th className="py-2 px-3">Win Rate</th>
                  <th className="py-2 px-3">P.Factor</th>
                  <th className="py-2 px-3">Max DD</th>
                  <th className="py-2 px-3">Fees</th>
                  <th className="py-2 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                {savedVault.map((item, idx) => {
                  const isPositive = item.net_pnl_usd >= 0;
                  return (
                    <tr key={item.id} className="hover:bg-slate-900/40 transition">
                      <td className="py-2.5 px-3 font-bold text-slate-400">#{idx + 1}</td>
                      <td className="py-2.5 px-3 font-sans font-bold text-white max-w-[200px] truncate">
                        {item.custom_label}
                      </td>
                      <td className="py-2.5 px-3 font-bold text-blue-400">{item.symbol}</td>
                      <td className="py-2.5 px-3">{item.timeframe}</td>
                      <td className="py-2.5 px-3 text-slate-400 text-[10px]">{item.test_mode}</td>
                      <td className={`py-2.5 px-3 font-bold ${isPositive ? "text-emerald-400" : "text-red-400"}`}>
                        {fmtUsd(item.net_pnl_usd, true)}
                      </td>
                      <td className={`py-2.5 px-3 font-bold ${isPositive ? "text-emerald-400" : "text-red-400"}`}>
                        {fmtPct(item.net_roi_pct, true)}
                      </td>
                      <td className="py-2.5 px-3 text-slate-200">{fmtPct(item.win_rate_pct)}</td>
                      <td className="py-2.5 px-3 text-blue-300">{item.profit_factor}</td>
                      <td className="py-2.5 px-3 text-red-400">{fmtPct(item.max_dd_pct)}</td>
                      <td className="py-2.5 px-3 text-amber-400/90 text-[10px]">
                        -{fmtUsd((item.spread_cost_usd || 0) + (item.swap_cost_usd || 0))}
                      </td>
                      <td className="py-2.5 px-3 text-right space-x-1 font-sans">
                        <button
                          onClick={() => handleLoadVaultCode(item)}
                          className="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-[10px] font-bold rounded"
                        >
                          Load in Editor
                        </button>
                        <button
                          onClick={() => handleAssignPairStrategy(item.symbol, item.strategy_id || item.id, "SCALP")}
                          className="px-2 py-0.5 bg-emerald-950 text-emerald-400 hover:bg-emerald-900 border border-emerald-800 text-[10px] font-bold rounded"
                        >
                          Assign Scalp
                        </button>
                        <button
                          onClick={() => handleAssignPairStrategy(item.symbol, item.strategy_id || item.id, "SWING")}
                          className="px-2 py-0.5 bg-blue-950 text-blue-400 hover:bg-blue-900 border border-blue-800 text-[10px] font-bold rounded"
                        >
                          Assign Swing
                        </button>
                        <button
                          onClick={() => handleDeleteVaultItem(item.id)}
                          className="p-1 hover:text-red-400 text-slate-500 transition inline-flex items-center"
                          title="Delete from Vault"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
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
