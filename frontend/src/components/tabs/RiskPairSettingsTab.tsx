import React, { useState, useEffect, useCallback } from "react";
import {
  ShieldAlert,
  Sliders,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Layers,
  Percent,
  DollarSign,
  Activity,
  Server,
  Zap,
  Globe,
  Lock,
  RotateCcw,
  SlidersHorizontal,
  ExternalLink,
} from "lucide-react";
import { INSTRUMENTS, InstrumentInfo, isMarketOpen, getAssetClassColor } from "../../constants/instruments";
import { api } from "../../services/api";
import { useToast } from "../Toast";
import { fmtUsd, fmtPct } from "../../utils/format";

interface RiskPairSettingsTabProps {
  onOpenAdvancedSettings?: () => void;
  isMt5Connected?: boolean;
  dbHealthy?: boolean;
}

interface PairConfigState {
  enabled: boolean;
  max_spread_points: number;
}

export const RiskPairSettingsTab: React.FC<RiskPairSettingsTabProps> = ({
  onOpenAdvancedSettings,
  isMt5Connected = false,
  dbHealthy = true,
}) => {
  const toast = useToast();
  const [loading, setLoading] = useState(false);
  const [guardrails, setGuardrails] = useState<any>(null);
  const [isResettingCb, setIsResettingCb] = useState(false);
  const [isSavingPairs, setIsSavingPairs] = useState(false);

  // Per-pair configuration state
  const [pairConfigs, setPairConfigs] = useState<Record<string, PairConfigState>>(() => {
    const initial: Record<string, PairConfigState> = {};
    INSTRUMENTS.forEach((inst) => {
      initial[inst.symbol] = {
        enabled: true,
        max_spread_points: inst.defaultSpread * 3 || 30,
      };
    });
    return initial;
  });

  // Fetch live guardrails & scheduler status
  const fetchTelemetry = useCallback(async () => {
    try {
      const [grRes, schedRes] = await Promise.all([
        api.ai.getRiskGuardrails(),
        api.ai.getScannerConfig().catch(() => null),
      ]);
      if (grRes) setGuardrails(grRes);
      if (schedRes && schedRes.pair_configs) {
        setPairConfigs((prev) => {
          const updated = { ...prev };
          Object.keys(schedRes.pair_configs).forEach((sym) => {
            if (updated[sym]) {
              updated[sym] = {
                ...updated[sym],
                ...schedRes.pair_configs[sym],
              };
            }
          });
          return updated;
        });
      }
    } catch (err: any) {
      console.warn("Telemetry fetch error in RiskSettings:", err);
    }
  }, []);

  useEffect(() => {
    fetchTelemetry();
    const timer = setInterval(fetchTelemetry, 8000);
    return () => clearInterval(timer);
  }, [fetchTelemetry]);

  // Reset Circuit Breaker
  const handleResetCircuitBreaker = async () => {
    setIsResettingCb(true);
    try {
      const res = await api.ai.resetCircuitBreaker();
      toast.success("Circuit Breaker Reset", res.message || "Trading safety lock cleared successfully.");
      await fetchTelemetry();
    } catch (err: any) {
      toast.error("Reset Failed", err.message || String(err));
    } finally {
      setIsResettingCb(false);
    }
  };

  // Toggle single pair scanning
  const handleTogglePair = (symbol: string) => {
    setPairConfigs((prev) => ({
      ...prev,
      [symbol]: {
        ...prev[symbol],
        enabled: !prev[symbol]?.enabled,
      },
    }));
  };

  // Update max spread for pair
  const handleSpreadChange = (symbol: string, val: number) => {
    setPairConfigs((prev) => ({
      ...prev,
      [symbol]: {
        ...prev[symbol],
        max_spread_points: Math.max(1, val),
      },
    }));
  };

  // Enable/Disable All
  const handleSetAllPairs = (enableState: boolean) => {
    setPairConfigs((prev) => {
      const next: Record<string, PairConfigState> = {};
      Object.keys(prev).forEach((sym) => {
        next[sym] = { ...prev[sym], enabled: enableState };
      });
      return next;
    });
    toast.info(
      enableState ? "All Pairs Enabled" : "All Pairs Disabled",
      `Scanning flags set to ${enableState ? "ACTIVE" : "DISABLED"} for 14 instruments.`
    );
  };

  // Save pair matrix
  const handleSavePairMatrix = async () => {
    setIsSavingPairs(true);
    try {
      const enabledMap: Record<string, boolean> = {};
      Object.keys(pairConfigs).forEach((s) => {
        enabledMap[s] = pairConfigs[s].enabled;
      });
      await api.ai.updateScannerConfig({
        pair_enabled_map: enabledMap,
        pair_configs: pairConfigs,
      });
      toast.success("Pair Settings Saved", "14-pair universe rules and spread caps persisted.");
    } catch (err: any) {
      toast.error("Save Failed", err.message || String(err));
    } finally {
      setIsSavingPairs(false);
    }
  };

  const isTripped = guardrails?.circuit_breaker?.tripped;

  return (
    <div className="space-y-4 font-sans max-w-7xl mx-auto pb-8">
      {/* Top Banner: Header + Advanced Settings Button */}
      <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-xl flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 shadow-inner">
            <Sliders className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-white font-mono tracking-wide">
                RISK MANAGEMENT & 14-PAIR CONTROL MATRIX
              </h2>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-cyan-950/80 text-cyan-400 border border-cyan-800/50 font-bold">
                INSTITUTIONAL GUARDRAILS
              </span>
            </div>
            <p className="text-xs text-slate-400 font-sans mt-0.5">
              Strict deterministic risk limits, sector correlation caps, and per-instrument execution thresholds.
            </p>
          </div>
        </div>

        {onOpenAdvancedSettings && (
          <button
            onClick={onOpenAdvancedSettings}
            className="flex items-center gap-2 px-3.5 py-2 bg-slate-900 hover:bg-slate-800 border border-slate-700/80 text-slate-200 text-xs font-mono font-semibold rounded-xl transition shadow-md"
          >
            <SlidersHorizontal className="w-4 h-4 text-cyan-400" />
            <span>Open Advanced Broker & DB Config</span>
            <ExternalLink className="w-3 h-3 text-slate-400" />
          </button>
        )}
      </div>

      {/* Grid: 3 Telemetry Guardrail Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Card 1: Position & Exposure Caps */}
        <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-lg space-y-3">
          <div className="flex items-center justify-between border-b border-slate-800/60 pb-2.5">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-indigo-400" />
              <span className="text-xs font-bold text-white font-mono uppercase">
                Portfolio Exposure
              </span>
            </div>
            <span className="text-[10px] font-mono text-indigo-300 font-bold px-1.5 py-0.5 rounded bg-indigo-950/60 border border-indigo-800/40">
              5 SLOTS MAX
            </span>
          </div>

          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between items-center py-1 border-b border-slate-900">
              <span className="text-slate-400">Open Positions:</span>
              <span className="font-bold text-white">
                {guardrails?.open_positions_count ?? 0} / {guardrails?.max_positions_limit ?? 5}
              </span>
            </div>
            <div className="flex justify-between items-center py-1 border-b border-slate-900">
              <span className="text-slate-400">Total Portfolio Risk:</span>
              <span className="font-bold text-cyan-400">
                {guardrails?.open_risk_pct?.toFixed(2) ?? "0.00"}% / 2.50%
              </span>
            </div>
            <div className="flex justify-between items-center py-1 border-b border-slate-900">
              <span className="text-slate-400">Risk Per Trade:</span>
              <span className="font-bold text-emerald-400">0.50% ($50.00 Cap)</span>
            </div>
            <div className="flex justify-between items-center py-1">
              <span className="text-slate-400">Margin Cap:</span>
              <span className="font-bold text-slate-200">18.00% Max Leverage</span>
            </div>
          </div>
        </div>

        {/* Card 2: Sector Correlation Caps */}
        <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-lg space-y-3">
          <div className="flex items-center justify-between border-b border-slate-800/60 pb-2.5">
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-cyan-400" />
              <span className="text-xs font-bold text-white font-mono uppercase">
                Sector Correlations
              </span>
            </div>
            <span className="text-[10px] font-mono text-cyan-300 font-bold px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/40">
              HEDGING LOCK
            </span>
          </div>

          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between items-center py-1 border-b border-slate-900">
              <span className="text-slate-400">Energy (OILCash#):</span>
              <span className="font-bold text-white">Max 1 Position</span>
            </div>
            <div className="flex justify-between items-center py-1 border-b border-slate-900">
              <span className="text-slate-400">Crypto CFDs (BTC/ETH/SOL/XRP):</span>
              <span className="font-bold text-white">Max 2 Positions</span>
            </div>
            <div className="flex justify-between items-center py-1 border-b border-slate-900">
              <span className="text-slate-400">USD Correlation Cap:</span>
              <span className="font-bold text-white">Max 2 Net USD Exposure</span>
            </div>
            <div className="flex justify-between items-center py-1">
              <span className="text-slate-400">Self-Hedging Block:</span>
              <span className="font-bold text-emerald-400">STRICT ENFORCEMENT</span>
            </div>
          </div>
        </div>

        {/* Card 3: Daily Drawdown Circuit Breaker */}
        <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl p-4 shadow-lg space-y-3">
          <div className="flex items-center justify-between border-b border-slate-800/60 pb-2.5">
            <div className="flex items-center gap-2">
              <ShieldAlert
                className={`w-4 h-4 ${isTripped ? "text-rose-400" : "text-emerald-400"}`}
              />
              <span className="text-xs font-bold text-white font-mono uppercase">
                Circuit Breaker
              </span>
            </div>
            <span
              className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                isTripped
                  ? "bg-rose-950/80 text-rose-300 border-rose-800"
                  : "bg-emerald-950/80 text-emerald-300 border-emerald-800"
              }`}
            >
              {isTripped ? "TRIPPED / PAUSED" : "ACTIVE / HEALTHY"}
            </span>
          </div>

          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between items-center py-1 border-b border-slate-900">
              <span className="text-slate-400">Daily Drawdown Limit:</span>
              <span className="font-bold text-rose-400">-3.00% Daily Soft-Stop</span>
            </div>
            <div className="flex justify-between items-center py-1 border-b border-slate-900">
              <span className="text-slate-400">Consecutive Loss Lock:</span>
              <span className="font-bold text-amber-400">4 Consecutive SL Hits</span>
            </div>
            <div className="flex justify-between items-center py-1">
              <span className="text-slate-400">Post-Exit Cooldown:</span>
              <span className="font-bold text-slate-300">15m Scalp / 60m Swing</span>
            </div>
          </div>

          {isTripped && (
            <div className="pt-2">
              <button
                onClick={handleResetCircuitBreaker}
                disabled={isResettingCb}
                className="w-full py-1.5 px-3 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-mono font-bold flex items-center justify-center gap-2 shadow-lg disabled:opacity-50"
              >
                <RotateCcw className={`w-3.5 h-3.5 ${isResettingCb ? "animate-spin" : ""}`} />
                <span>Override & Reset Circuit Breaker</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Main Table: 14-Instrument Control Matrix */}
      <div className="bg-[#0f1623] border border-slate-800/80 rounded-2xl shadow-xl overflow-hidden">
        <div className="p-4 border-b border-slate-800/80 flex flex-wrap items-center justify-between gap-3 bg-[#0a0f19]">
          <div>
            <h3 className="text-sm font-bold text-white font-mono flex items-center gap-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              <span>14-INSTRUMENT MULTI-ASSET MATRIX</span>
            </h3>
            <p className="text-xs text-slate-400 font-sans mt-0.5">
              Configure scanner activation and maximum spread thresholds across all supported XM Global instruments.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => handleSetAllPairs(true)}
              className="px-2.5 py-1 text-xs font-mono rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition"
            >
              Enable All (14)
            </button>
            <button
              onClick={() => handleSetAllPairs(false)}
              className="px-2.5 py-1 text-xs font-mono rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition"
            >
              Disable All
            </button>
            <button
              onClick={handleSavePairMatrix}
              disabled={isSavingPairs}
              className="px-4 py-1.5 text-xs font-mono font-bold rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition flex items-center gap-1.5 shadow-md disabled:opacity-50"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>{isSavingPairs ? "Saving..." : "Save Pair Matrix"}</span>
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono divide-y divide-slate-800/60">
            <thead className="bg-[#070b13] text-slate-400 uppercase text-[10px]">
              <tr>
                <th className="py-2.5 px-4">Instrument</th>
                <th className="py-2.5 px-4">Asset Class</th>
                <th className="py-2.5 px-4">Market Status</th>
                <th className="py-2.5 px-4">Digits</th>
                <th className="py-2.5 px-4">Default Spread</th>
                <th className="py-2.5 px-4">Max Spread Cap (pts)</th>
                <th className="py-2.5 px-4 text-right">Autonomous Scan</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40 text-slate-300">
              {INSTRUMENTS.map((inst) => {
                const conf = pairConfigs[inst.symbol] || {
                  enabled: true,
                  max_spread_points: inst.defaultSpread * 3 || 30,
                };
                const color = getAssetClassColor(inst.assetClass);
                const openState = isMarketOpen(inst.symbol);

                return (
                  <tr
                    key={inst.symbol}
                    className={`hover:bg-slate-800/30 transition ${
                      conf.enabled ? "" : "opacity-50 bg-slate-950/40"
                    }`}
                  >
                    <td className="py-3 px-4 font-bold text-white flex items-center gap-2">
                      <span
                        className={`w-2 h-2 rounded-full ${
                          openState ? "bg-emerald-400" : "bg-slate-600"
                        }`}
                      />
                      <span>{inst.symbol}</span>
                      <span className="text-[10px] text-slate-500 font-sans font-normal truncate max-w-[120px]">
                        {inst.name}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <span className={`text-[9px] px-2 py-0.5 rounded-md font-bold ${color.badge}`}>
                        {inst.assetClass}
                      </span>
                      {inst.is24_7 && (
                        <span className="ml-1.5 text-[9px] px-1.5 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800/60 font-bold">
                          24/7
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`text-[10px] font-bold ${
                          openState ? "text-emerald-400" : "text-slate-500"
                        }`}
                      >
                        {openState ? "OPEN / ACTIVE" : "CLOSED / WEEKEND"}
                      </span>
                    </td>
                    <td className="py-3 px-4 tabular-nums">{inst.digits}</td>
                    <td className="py-3 px-4 tabular-nums text-slate-400">
                      {inst.defaultSpread} pts
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1.5 max-w-[120px]">
                        <input
                          type="number"
                          min={1}
                          max={500}
                          value={conf.max_spread_points}
                          onChange={(e) =>
                            handleSpreadChange(inst.symbol, parseInt(e.target.value) || 1)
                          }
                          className="w-16 px-2 py-1 bg-slate-900 border border-slate-700 rounded text-center text-xs text-white focus:outline-none focus:border-cyan-500"
                        />
                        <span className="text-[10px] text-slate-500">pts</span>
                      </div>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={() => handleTogglePair(inst.symbol)}
                        className={`px-3 py-1 rounded-lg text-[10px] font-bold transition ${
                          conf.enabled
                            ? "bg-emerald-950 text-emerald-400 border border-emerald-800 hover:bg-emerald-900"
                            : "bg-slate-900 text-slate-500 border border-slate-800 hover:text-slate-300"
                        }`}
                      >
                        {conf.enabled ? "ACTIVE SCAN" : "DISABLED"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
