import React, { useState, useEffect, useCallback } from "react";
import {
  BarChart3,
  Calendar,
  DollarSign,
  Download,
  Filter,
  RefreshCw,
  Zap,
  ShieldAlert,
  Sliders,
  Sparkles,
  Layers,
  Clock,
  CheckCircle2,
} from "lucide-react";
import { api } from "../../services/api";
import { useToast } from "../Toast";

interface RateCard {
  model_id: string;
  input_per_1m_usd: number;
  output_per_1m_usd: number;
  cached_per_1m_usd: number;
  is_free_tier_eligible: boolean;
}

export const UsageAnalyticsTab: React.FC = () => {
  const toast = useToast();
  const [loading, setLoading] = useState(false);
  const [granularity, setGranularity] = useState<"DAILY" | "WEEKLY" | "MONTHLY">("DAILY");
  const [currency, setCurrency] = useState<"USD" | "INR">("USD");
  const [inrRate, setInrRate] = useState<number>(86.50);

  // Filters
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedPurpose, setSelectedPurpose] = useState<string>("");
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");

  // Data
  const [summary, setSummary] = useState<any>(null);
  const [rateCards, setRateCards] = useState<RateCard[]>([]);
  const [isFreeTierActive, setIsFreeTierActive] = useState<boolean>(false);
  const [isRateModalOpen, setIsRateModalOpen] = useState(false);
  const [editingRates, setEditingRates] = useState<RateCard[]>([]);

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.usage.getSummary({
        granularity,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        symbol: selectedSymbol || undefined,
        model_id: selectedModel || undefined,
        call_purpose: selectedPurpose || undefined,
        usd_to_inr_rate: inrRate,
      });
      setSummary(data);
      setIsFreeTierActive(data.free_tier_active || false);
    } catch (e: any) {
      toast.error("Failed to load usage data", e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [granularity, startDate, endDate, selectedSymbol, selectedModel, selectedPurpose, inrRate, toast]);

  const fetchRates = async () => {
    try {
      const res = await api.usage.getRates();
      if (res && res.rates) {
        setRateCards(res.rates);
        setEditingRates(res.rates);
        setIsFreeTierActive(res.gemini_use_free_tier || false);
      }
    } catch (e: any) {
      console.warn("Could not fetch rate cards:", e);
    }
  };

  useEffect(() => {
    fetchSummary();
    fetchRates();
  }, [fetchSummary]);

  const handleExportCsv = () => {
    const url = api.usage.exportCsvUrl({
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      symbol: selectedSymbol || undefined,
      model_id: selectedModel || undefined,
      call_purpose: selectedPurpose || undefined,
    });
    window.open(url, "_blank");
  };

  const handleSaveRates = async () => {
    try {
      await api.usage.updateRates({
        rates: editingRates,
        gemini_use_free_tier: isFreeTierActive,
      });
      toast.success("Rate Cards Saved", "Gemini pricing configuration and billing tier updated.");
      setIsRateModalOpen(false);
      fetchSummary();
      fetchRates();
    } catch (e: any) {
      toast.error("Save Failed", e.message || String(e));
    }
  };

  const formatCost = (usdVal: number) => {
    if (currency === "INR") {
      const inr = usdVal * inrRate;
      return `₹${inr.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `$${usdVal.toFixed(4)}`;
  };

  const totals = summary?.totals || {
    total_calls: 0,
    total_tokens: 0,
    total_prompt_tokens: 0,
    total_output_tokens: 0,
    total_thinking_tokens: 0,
    total_cached_tokens: 0,
    total_cost_usd: 0,
    shadow_paid_usd: 0,
    cached_savings_usd: 0,
    avg_cost_per_call_usd: 0,
    avg_latency_ms: 0,
    today_cost_usd: 0,
    week_cost_usd: 0,
    month_cost_usd: 0,
    run_rate_30d_usd: 0,
  };

  return (
    <div className="space-y-4">
      {/* Top Header & Control Toolbar */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <BarChart3 className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-white tracking-wide">
                GEMINI USAGE & BILLING ANALYTICS
              </h2>
              {isFreeTierActive ? (
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  FREE TIER ACTIVE ($0.00 Billed)
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/30">
                  COMMERCIAL PAID TIER
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400">
              Deterministic real-time token tracking, prompt/output/cache ledger, and pricing telemetry.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Currency Toggle */}
          <div className="flex bg-slate-950 border border-slate-800 rounded-md p-0.5">
            <button
              onClick={() => setCurrency("USD")}
              className={`px-2.5 py-1 text-xs font-semibold rounded ${currency === "USD"
                ? "bg-cyan-500/20 text-cyan-400"
                : "text-slate-400 hover:text-white"
                }`}
            >
              USD ($)
            </button>
            <button
              onClick={() => setCurrency("INR")}
              className={`px-2.5 py-1 text-xs font-semibold rounded ${currency === "INR"
                ? "bg-cyan-500/20 text-cyan-400"
                : "text-slate-400 hover:text-white"
                }`}
            >
              INR (₹{inrRate})
            </button>
          </div>

          {/* Granularity */}
          <div className="flex bg-slate-950 border border-slate-800 rounded-md p-0.5">
            {(["DAILY", "WEEKLY", "MONTHLY"] as const).map((g) => (
              <button
                key={g}
                onClick={() => setGranularity(g)}
                className={`px-2.5 py-1 text-xs font-semibold rounded ${granularity === g
                  ? "bg-slate-800 text-white"
                  : "text-slate-400 hover:text-white"
                  }`}
              >
                {g}
              </button>
            ))}
          </div>

          <button
            onClick={() => setIsRateModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-md border border-slate-700 transition"
          >
            <Sliders className="w-3.5 h-3.5 text-cyan-400" />
            <span>Rate Cards</span>
          </button>

          <button
            onClick={handleExportCsv}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-md border border-slate-700 transition"
          >
            <Download className="w-3.5 h-3.5 text-emerald-400" />
            <span>Export CSV</span>
          </button>

          <button
            onClick={fetchSummary}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold rounded-md transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Multi-Filter Bar */}
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-3 flex flex-wrap items-center gap-3 text-xs">
        <div className="flex items-center gap-1.5 text-slate-400 font-semibold">
          <Filter className="w-3.5 h-3.5 text-cyan-400" />
          <span>Filters:</span>
        </div>

        {/* Symbol */}
        <select
          value={selectedSymbol}
          onChange={(e) => setSelectedSymbol(e.target.value)}
          className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-slate-200 focus:outline-none focus:border-cyan-500 font-bold"
        >
          <option value="">All Pairs</option>
          <option value="GOLD#">GOLD# (Spot Gold)</option>
          <option value="BTCUSD#">BTCUSD# (Bitcoin CFD)</option>
          <option value="GLOBAL">GLOBAL (System / Forensics)</option>
        </select>

        {/* Model */}
        <select
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-slate-200 focus:outline-none focus:border-cyan-500"
        >
          <option value="">All Models</option>
          <option value="gemini-3.8-flash">Gemini 3.8 Flash</option>
          <option value="gemini-3.6-flash">Gemini 3.6 Flash</option>
          <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
          <option value="gemini-3-flash-preview">Gemini 3 Flash Preview</option>
          <option value="gemini-3.1-pro-preview">Gemini 3.1 Pro Preview</option>
          <option value="gemini-4-argon">Gemini 4 Argon</option>
        </select>

        {/* Purpose */}
        <select
          value={selectedPurpose}
          onChange={(e) => setSelectedPurpose(e.target.value)}
          className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-slate-200 focus:outline-none focus:border-cyan-500"
        >
          <option value="">All Call Types</option>
          <option value="LIVE_SCAN">LIVE_SCAN (Supervisor)</option>
          <option value="MANUAL_SCAN">MANUAL_SCAN (1-Click)</option>
          <option value="SL_FORENSICS">SL_FORENSICS (Postmortem)</option>
          <option value="RULE_VALIDATION">RULE_VALIDATION</option>
          <option value="KEY_TEST">KEY_TEST</option>
        </select>

        {/* Start Date */}
        <div className="flex items-center gap-1">
          <span className="text-slate-500">From:</span>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-200"
          />
        </div>

        {/* End Date */}
        <div className="flex items-center gap-1">
          <span className="text-slate-500">To:</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-200"
          />
        </div>

        {(selectedSymbol || selectedModel || selectedPurpose || startDate || endDate) && (
          <button
            onClick={() => {
              setSelectedSymbol("");
              setSelectedModel("");
              setSelectedPurpose("");
              setStartDate("");
              setEndDate("");
            }}
            className="text-cyan-400 hover:text-cyan-300 font-semibold ml-auto"
          >
            Clear Filters
          </button>
        )}
      </div>

      {/* Primary KPI Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Today's Spend */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span>Today's Spend</span>
            <DollarSign className="w-3.5 h-3.5 text-cyan-400" />
          </div>
          <div className="text-lg font-bold text-white font-mono">
            {formatCost(totals.today_cost_usd)}
          </div>
          <div className="text-[10px] text-slate-500 mt-1">
            {currency === "USD" ? `₹${(totals.today_cost_usd * inrRate).toFixed(2)}` : `$${totals.today_cost_usd.toFixed(4)}`}
          </div>
        </div>

        {/* 7-Day Spend */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span>Past 7 Days</span>
            <Calendar className="w-3.5 h-3.5 text-blue-400" />
          </div>
          <div className="text-lg font-bold text-white font-mono">
            {formatCost(totals.week_cost_usd)}
          </div>
          <div className="text-[10px] text-slate-500 mt-1">
            {currency === "USD" ? `₹${(totals.week_cost_usd * inrRate).toFixed(2)}` : `$${totals.week_cost_usd.toFixed(4)}`}
          </div>
        </div>

        {/* 30-Day Run Rate */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span>30D Run Rate</span>
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
          </div>
          <div className="text-lg font-bold text-amber-400 font-mono">
            {formatCost(totals.run_rate_30d_usd)}
          </div>
          <div className="text-[10px] text-slate-500 mt-1">
            Est. monthly API expense
          </div>
        </div>

        {/* Total Tokens Consumed */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span>Total Tokens</span>
            <Layers className="w-3.5 h-3.5 text-purple-400" />
          </div>
          <div className="text-lg font-bold text-purple-300 font-mono">
            {totals.total_tokens.toLocaleString()}
          </div>
          <div className="text-[10px] text-slate-500 mt-1 flex items-center gap-1">
            <span>In: {Math.round(totals.total_prompt_tokens / 1000)}k</span>
            <span>•</span>
            <span>Out: {Math.round(totals.total_output_tokens / 1000)}k</span>
          </div>
        </div>

        {/* Cached Savings */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span>Context Savings</span>
            <Zap className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="text-lg font-bold text-emerald-400 font-mono">
            {formatCost(totals.cached_savings_usd)}
          </div>
          <div className="text-[10px] text-slate-500 mt-1">
            {totals.total_cached_tokens.toLocaleString()} cached tokens
          </div>
        </div>

        {/* Shadow Paid Value */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
            <span>Shadow Paid Value</span>
            <ShieldAlert className="w-3.5 h-3.5 text-cyan-400" />
          </div>
          <div className="text-lg font-bold text-cyan-300 font-mono">
            {formatCost(totals.shadow_paid_usd)}
          </div>
          <div className="text-[10px] text-slate-500 mt-1">
            Avg: ${(totals.avg_cost_per_call_usd).toFixed(5)}/call
          </div>
        </div>
      </div>

      {/* Visual Charts: Daily Spend Timeline & Pair Breakdowns */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Timeline Bar Chart */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-cyan-400" />
              <span>Spend & Token Timeline ({granularity})</span>
            </h3>
            <span className="text-xs text-slate-500 font-mono">
              Total Invocations: {totals.total_calls}
            </span>
          </div>

          {summary?.time_series && summary.time_series.length > 0 ? (
            <div className="space-y-2">
              <div className="h-44 flex items-end gap-2 pt-6 pb-2 border-b border-slate-800">
                {summary.time_series.map((bucket: any, idx: number) => {
                  const maxCost = Math.max(...summary.time_series.map((b: any) => b.cost_usd), 0.001);
                  const heightPct = Math.max(8, Math.min(100, Math.round((bucket.cost_usd / maxCost) * 100)));
                  return (
                    <div key={idx} className="flex-1 flex flex-col items-center gap-1 group relative">
                      {/* Tooltip */}
                      <div className="absolute -top-10 opacity-0 group-hover:opacity-100 transition pointer-events-none bg-slate-950 border border-slate-700 px-2 py-1 rounded text-[10px] text-white whitespace-nowrap z-20">
                        {bucket.date_bucket}: {formatCost(bucket.cost_usd)} ({bucket.calls} calls, {bucket.tokens} tokens)
                      </div>
                      <div
                        style={{ height: `${heightPct}%` }}
                        className="w-full bg-cyan-500/40 hover:bg-cyan-400 rounded-t transition border-t border-cyan-400/80"
                      />
                    </div>
                  );
                })}
              </div>
              <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                <span>{summary.time_series[0]?.date_bucket}</span>
                <span>{summary.time_series[summary.time_series.length - 1]?.date_bucket}</span>
              </div>
            </div>
          ) : (
            <div className="h-44 flex items-center justify-center text-slate-500 text-xs">
              No usage records found for selected filter range.
            </div>
          )}
        </div>

        {/* Cost By Symbol Breakdown Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <h3 className="text-xs font-bold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
            <Layers className="w-4 h-4 text-purple-400" />
            <span>Cost By Instrument</span>
          </h3>
          <div className="space-y-2 max-h-56 overflow-y-auto">
            {summary?.by_symbol && summary.by_symbol.length > 0 ? (
              summary.by_symbol.map((item: any, idx: number) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 rounded bg-slate-950/60 border border-slate-800/80 text-xs"
                >
                  <div>
                    <span className="font-bold text-white font-mono">{item.symbol}</span>
                    <span className="text-[10px] text-slate-500 ml-2">({item.calls} scans)</span>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-cyan-400 font-semibold">{formatCost(item.cost_usd)}</div>
                    <div className="text-[10px] text-slate-500 font-mono">
                      {item.tokens.toLocaleString()} tokens
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center text-slate-500 text-xs py-8">No data available</div>
            )}
          </div>
        </div>
      </div>

      {/* Detailed Token Ledger Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
            <Clock className="w-4 h-4 text-emerald-400" />
            <span>Recent Token Invocations Ledger</span>
          </h3>
          <span className="text-[11px] text-slate-400">
            Showing latest {summary?.recent_calls?.length || 0} API records
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 text-[11px]">
                <th className="pb-2">Time (IST)</th>
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Model</th>
                <th className="pb-2">Purpose</th>
                <th className="pb-2">Tier</th>
                <th className="pb-2 text-right">Prompt</th>
                <th className="pb-2 text-right">Output</th>
                <th className="pb-2 text-right">Cached</th>
                <th className="pb-2 text-right">Total Tokens</th>
                <th className="pb-2 text-right">USD Cost</th>
                <th className="pb-2 text-right">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50 text-slate-300">
              {summary?.recent_calls && summary.recent_calls.length > 0 ? (
                summary.recent_calls.map((row: any) => (
                  <tr key={row.id} className="hover:bg-slate-800/30 transition">
                    <td className="py-2 font-mono text-[11px] text-slate-400">{row.created_at_ist}</td>
                    <td className="py-2 font-bold text-white font-mono">{row.symbol}</td>
                    <td className="py-2 font-mono text-[11px] text-cyan-400">{row.model_id}</td>
                    <td className="py-2">
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300">
                        {row.call_purpose}
                      </span>
                    </td>
                    <td className="py-2">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${row.billing_tier === "FREE"
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                          : "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                          }`}
                      >
                        {row.billing_tier}
                      </span>
                    </td>
                    <td className="py-2 text-right font-mono text-slate-400">{row.prompt_tokens}</td>
                    <td className="py-2 text-right font-mono text-slate-400">{row.output_tokens}</td>
                    <td className="py-2 text-right font-mono text-emerald-400">
                      {row.cached_tokens > 0 ? row.cached_tokens : "-"}
                    </td>
                    <td className="py-2 text-right font-mono text-purple-300 font-semibold">
                      {row.total_tokens.toLocaleString()}
                    </td>
                    <td className="py-2 text-right font-mono text-cyan-300 font-bold">
                      ${row.estimated_cost_usd.toFixed(6)}
                    </td>
                    <td className="py-2 text-right font-mono text-[11px] text-slate-500">
                      {row.latency_ms}ms
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={11} className="py-6 text-center text-slate-500">
                    No API usage records logged yet. Real calls from Gemini Supervisor will populate here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Model Rate Card Configuration Modal */}
      {isRateModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-2xl w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <Sliders className="w-5 h-5 text-cyan-400" />
                <h3 className="font-bold text-white text-base">Gemini Model Pricing Rate Cards</h3>
              </div>
              <button
                onClick={() => setIsRateModalOpen(false)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            {/* Free Tier Mode Switch */}
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 flex items-center justify-between">
              <div>
                <div className="text-xs font-bold text-white flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span>Free Tier Key Mode</span>
                </div>
                <div className="text-[11px] text-slate-400 mt-0.5">
                  When enabled, all eligible model calls report $0.00 actual billed cost while preserving shadow paid value.
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={isFreeTierActive}
                  onChange={(e) => setIsFreeTierActive(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-600"></div>
              </label>
            </div>

            {/* Rates Table */}
            <div className="overflow-x-auto border border-slate-800 rounded-lg">
              <table className="w-full text-xs text-left">
                <thead className="bg-slate-950 text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="p-2.5">Model ID</th>
                    <th className="p-2.5">Input / 1M ($)</th>
                    <th className="p-2.5">Output / 1M ($)</th>
                    <th className="p-2.5">Cached / 1M ($)</th>
                    <th className="p-2.5 text-center">Free Eligible</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 text-slate-200">
                  {editingRates.map((rc, idx) => (
                    <tr key={rc.model_id}>
                      <td className="p-2.5 font-mono font-semibold text-cyan-400">{rc.model_id}</td>
                      <td className="p-2.5">
                        <input
                          type="number"
                          step="0.01"
                          value={rc.input_per_1m_usd}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value) || 0;
                            const copy = [...editingRates];
                            copy[idx].input_per_1m_usd = val;
                            setEditingRates(copy);
                          }}
                          className="w-20 bg-slate-950 border border-slate-800 rounded px-2 py-0.5 font-mono text-right"
                        />
                      </td>
                      <td className="p-2.5">
                        <input
                          type="number"
                          step="0.01"
                          value={rc.output_per_1m_usd}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value) || 0;
                            const copy = [...editingRates];
                            copy[idx].output_per_1m_usd = val;
                            setEditingRates(copy);
                          }}
                          className="w-20 bg-slate-950 border border-slate-800 rounded px-2 py-0.5 font-mono text-right"
                        />
                      </td>
                      <td className="p-2.5">
                        <input
                          type="number"
                          step="0.001"
                          value={rc.cached_per_1m_usd}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value) || 0;
                            const copy = [...editingRates];
                            copy[idx].cached_per_1m_usd = val;
                            setEditingRates(copy);
                          }}
                          className="w-20 bg-slate-950 border border-slate-800 rounded px-2 py-0.5 font-mono text-right"
                        />
                      </td>
                      <td className="p-2.5 text-center">
                        <input
                          type="checkbox"
                          checked={rc.is_free_tier_eligible}
                          onChange={(e) => {
                            const copy = [...editingRates];
                            copy[idx].is_free_tier_eligible = e.target.checked;
                            setEditingRates(copy);
                          }}
                          className="rounded bg-slate-950 border-slate-700 text-cyan-500 focus:ring-0"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setIsRateModalOpen(false)}
                className="px-3 py-1.5 text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveRates}
                className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold rounded-md transition"
              >
                Save Rate Cards
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

