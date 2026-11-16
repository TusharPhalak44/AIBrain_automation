import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  IChartApi,
  ISeriesApi,
  ColorType,
  CandlestickSeries,
  HistogramSeries,
} from "lightweight-charts";
import {
  TrendingUp,
  TrendingDown,
  Clock,
  Radio,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Maximize2,
  Layers,
} from "lucide-react";
import { fmtPrice, fmtUsd, fmtLots, safeArr } from "../../utils/format";
import { OpenPosition, PlannedTrade, PairSchedule, QuoteData } from "../../hooks/useLiveStore";
import { api } from "../../services/api";
import { useToast } from "../Toast";

interface CockpitTabProps {
  selectedSymbol: string;
  selectedTimeframe: string;
  isMt5Connected: boolean;
  openPositions: OpenPosition[];
  plannedTrades: PlannedTrade[];
  pairSchedules: Record<string, PairSchedule>;
  quotes?: Record<string, QuoteData>;
  onSelectSymbol: (symbol: string) => void;
  onSelectTimeframe: (tf: string) => void;
  onApproveCopilot: (tradeId: number) => Promise<any>;
  onRejectCopilot: (tradeId: number) => Promise<any>;
}

const XM_SYMBOLS = [
  { symbol: "GOLD#", name: "Gold (Spot USD)", class: "METALS" },
  { symbol: "EURUSD#", name: "EUR / USD", class: "FOREX" },
  { symbol: "GBPUSD#", name: "GBP / USD", class: "FOREX" },
  { symbol: "USDJPY#", name: "USD / JPY", class: "FOREX" },
  { symbol: "BTCUSD#", name: "Bitcoin CFD", class: "CRYPTO" },
  { symbol: "ETHUSD#", name: "Ethereum CFD", class: "CRYPTO" },
  { symbol: "SOLUSD#", name: "Solana CFD", class: "CRYPTO" },
];

const TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"];

export const CockpitTab: React.FC<CockpitTabProps> = ({
  selectedSymbol,
  selectedTimeframe,
  isMt5Connected,
  openPositions,
  plannedTrades,
  pairSchedules,
  quotes = {},
  onSelectSymbol,
  onSelectTimeframe,
  onApproveCopilot,
  onRejectCopilot,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  const [isLoadingChart, setIsLoadingChart] = useState(false);
  const [chartStatus, setChartStatus] = useState<string>("OK");
  const [candleCount, setCandleCount] = useState<number>(0);
  const [overlays, setOverlays] = useState<any>({});
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const toast = useToast();

  // Initialize and update Lightweight Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Create Chart
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0B0E14" },
        textColor: "#94A3B8",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#161E2E" },
        horzLines: { color: "#161E2E" },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: "#1E293B",
      },
      timeScale: {
        borderColor: "#1E293B",
        timeVisible: true,
        secondsVisible: false,
      },
      autoSize: true,
    });

    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10B981",
      downColor: "#EF4444",
      borderUpColor: "#10B981",
      borderDownColor: "#EF4444",
      wickUpColor: "#10B981",
      wickDownColor: "#EF4444",
    });
    candleSeriesRef.current = candleSeries;

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "#3B82F6",
      priceFormat: {
        type: "volume",
      },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });
    volumeSeriesRef.current = volumeSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, []);

  // Fetch live candles and overlays when symbol or timeframe changes
  useEffect(() => {
    let isCancelled = false;

    async function loadCandles() {
      setIsLoadingChart(true);
      try {
        const data = await api.candles.get(selectedSymbol, selectedTimeframe, 250);

        if (isCancelled) return;

        setChartStatus(data.status || "OK");
        if (data.status === "OK" && candleSeriesRef.current && volumeSeriesRef.current) {
          const rawCandles = safeArr<any>(data.candles);
          setCandleCount(rawCandles.length);
          if (rawCandles.length > 0) {
            candleSeriesRef.current.setData(
              rawCandles.map((c) => ({
                time: c.time,
                open: c.open,
                high: c.high,
                low: c.low,
                close: c.close,
              }))
            );

            volumeSeriesRef.current.setData(
              rawCandles.map((c) => ({
                time: c.time,
                value: c.volume,
                color: c.close >= c.open ? "rgba(16, 185, 129, 0.4)" : "rgba(239, 68, 68, 0.4)",
              }))
            );

            // Fit chart content
            chartRef.current?.timeScale().fitContent();
          }

          if (data.overlays) {
            setOverlays(data.overlays);
          }
        }
      } catch (err: any) {
        console.error("Failed to load live candles:", err);
        setChartStatus("ERROR");
      } finally {
        if (!isCancelled) setIsLoadingChart(false);
      }
    }

    loadCandles();
    return () => {
      isCancelled = true;
    };
  }, [selectedSymbol, selectedTimeframe, isMt5Connected]);

  const handleApprove = async (id: number) => {
    setActionLoading(id);
    try {
      const res = await onApproveCopilot(id);
      toast.success("Order Dispatched", res.message || `Copilot setup #${id} approved.`);
    } catch (e: any) {
      toast.error("Execution Failed", e.message || String(e));
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (id: number) => {
    setActionLoading(id);
    try {
      await onRejectCopilot(id);
      toast.info("Setup Dismissed", `Copilot setup #${id} rejected.`);
    } catch (e: any) {
      toast.error("Dismiss Failed", e.message || String(e));
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 h-[calc(100vh-120px)] overflow-hidden">
      {/* Left Column: Market Watch (3 cols) */}
      <div className="lg:col-span-3 bg-[#121824] border border-slate-800 rounded-xl flex flex-col overflow-hidden">
        <div className="p-3 border-b border-slate-800 flex items-center justify-between">
          <div className="font-bold text-slate-100 text-xs flex items-center gap-1.5">
            <Radio className="w-3.5 h-3.5 text-blue-400" />
            <span>XM MARKET WATCH</span>
          </div>
          <span className="text-[10px] text-slate-400 font-mono">MT5 FEED</span>
        </div>

        <div className="flex-1 overflow-y-auto divide-y divide-slate-800/60">
          {XM_SYMBOLS.map((item) => {
            const isSelected = selectedSymbol === item.symbol;
            const sched = pairSchedules[item.symbol];
            const countdown = sched?.next_scan_seconds ?? sched?.interval_sec ?? 60;
            const q = quotes[item.symbol] || quotes[item.symbol.replace("#", "")];
            const digits = item.class === "FOREX" ? (item.symbol.includes("JPY") ? 3 : 5) : 2;

            return (
              <button
                key={item.symbol}
                onClick={() => onSelectSymbol(item.symbol)}
                className={`w-full p-2.5 text-left transition flex items-center justify-between ${
                  isSelected
                    ? "bg-blue-950/40 border-l-2 border-blue-500"
                    : "hover:bg-slate-900/60"
                }`}
              >
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-slate-100 text-xs">{item.symbol}</span>
                    <span className="text-[9px] bg-slate-800 text-slate-400 px-1 py-0.2 rounded font-mono">
                      {item.class}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5">{item.name}</div>
                  {q && q.bid > 0 ? (
                    <div className="flex items-center gap-1.5 mt-1 text-[10px] font-mono">
                      <span className="text-emerald-400 font-bold">{q.bid.toFixed(digits)}</span>
                      <span className="text-slate-600">/</span>
                      <span className="text-slate-200">{q.ask.toFixed(digits)}</span>
                      <span className="text-[9px] bg-slate-900 text-amber-400 px-1 py-0.2 rounded border border-slate-700/60">
                        {q.spread_points} pt
                      </span>
                    </div>
                  ) : null}
                </div>

                <div className="text-right">
                  <div className="text-[10px] font-mono text-slate-300 flex items-center gap-1 justify-end">
                    <Clock className="w-2.5 h-2.5 text-slate-500" />
                    <span>{countdown}s</span>
                  </div>
                  <div className="text-[9px] text-blue-400 mt-0.5 font-semibold">
                    {sched?.status || "MONITORING"}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Center & Right Column: Chart & Active Trades (9 cols) */}
      <div className="lg:col-span-9 flex flex-col gap-3 h-full overflow-hidden">
        {/* Top: Chart View Container */}
        <div className="flex-1 bg-[#121824] border border-slate-800 rounded-xl flex flex-col overflow-hidden relative">
          {/* Chart Header Bar */}
          <div className="px-4 py-2 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2 bg-[#0E131D]">
            <div className="flex items-center gap-3">
              <span className="font-bold text-slate-100 text-sm tracking-wide">{selectedSymbol}</span>
              <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded border border-slate-800">
                {TIMEFRAMES.map((tf) => (
                  <button
                    key={tf}
                    onClick={() => onSelectTimeframe(tf)}
                    className={`px-2 py-0.5 text-[11px] font-semibold rounded transition ${
                      selectedTimeframe === tf
                        ? "bg-blue-600 text-white"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {tf}
                  </button>
                ))}
              </div>
            </div>

            {/* Price-Action Overlays Info */}
            <div className="flex items-center gap-2 text-[10px] text-slate-400">
              {overlays.pdh && (
                <span className="bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                  PDH: <strong className="text-slate-200">{fmtPrice(overlays.pdh)}</strong>
                </span>
              )}
              {overlays.pdl && (
                <span className="bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                  PDL: <strong className="text-slate-200">{fmtPrice(overlays.pdl)}</strong>
                </span>
              )}
              {safeArr(overlays.fvgs).length > 0 && (
                <span className="bg-blue-950/60 text-blue-400 px-1.5 py-0.5 rounded border border-blue-900">
                  FVG: {safeArr(overlays.fvgs).length} Active
                </span>
              )}
            </div>
          </div>

          {/* Chart Canvas */}
          <div className="flex-1 w-full h-full relative" ref={chartContainerRef}>
            {/* Offline Banner Overlay - only if no candles available */}
            {((!isMt5Connected || chartStatus === "MT5_DISCONNECTED") && candleCount === 0) && (
              <div className="absolute inset-0 bg-black/75 backdrop-blur-xs flex flex-col items-center justify-center z-20 text-center p-6">
                <div className="w-12 h-12 rounded-full bg-red-950/80 border border-red-500/50 flex items-center justify-center mb-3 text-red-400">
                  <Radio className="w-6 h-6 animate-pulse" />
                </div>
                <h3 className="text-base font-bold text-white mb-1">XM MT5 Terminal Disconnected</h3>
                <p className="text-slate-400 text-xs max-w-sm">
                  Candlestick feed is paused. Strictly zero mock or synthetic fallback candles are rendered.
                  Connect your XM MT5 profile in Settings to stream live institutional ticks.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Bottom: Positions & Copilot Staging Cards (Fixed height) */}
        <div className="h-48 bg-[#121824] border border-slate-800 rounded-xl flex flex-col overflow-hidden">
          {/* Header tabs */}
          <div className="px-3 py-1.5 border-b border-slate-800 bg-[#0E131D] flex items-center justify-between text-xs font-bold text-slate-300">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5 text-blue-400">
                <Layers className="w-3.5 h-3.5" />
                <span>Open Positions ({openPositions.length})</span>
              </span>
              <span className="text-amber-400">
                Copilot Setups ({plannedTrades.length})
              </span>
            </div>
          </div>

          {/* Body Content */}
          <div className="flex-1 overflow-y-auto p-2">
            {plannedTrades.length > 0 && (
              <div className="mb-3 space-y-1.5">
                <div className="text-[10px] text-amber-400 font-bold uppercase tracking-wider px-1">
                  Pending Human Confirmation (Copilot 1-Click)
                </div>
                {plannedTrades.map((t) => (
                  <div
                    key={t.id}
                    className="p-2.5 rounded-lg bg-amber-950/20 border border-amber-500/30 flex flex-wrap items-center justify-between gap-2"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-slate-100 text-xs">{t.symbol}</span>
                        <span
                          className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                            t.direction === "BUY"
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                              : "bg-red-950 text-red-400 border border-red-800"
                          }`}
                        >
                          {t.direction} {t.mode}
                        </span>
                        <span className="text-[10px] text-slate-400 font-mono">
                          {fmtLots(t.lots)} Lots
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-300 mt-1 flex gap-3 font-mono">
                        <span>Entry: {fmtPrice(t.entry_price)}</span>
                        <span>SL: {fmtPrice(t.sl)}</span>
                        <span>TP1: {fmtPrice(t.tp1)}</span>
                        <span>TP2: {fmtPrice(t.tp2)}</span>
                      </div>
                      {t.ai_analysis_summary && (
                        <div className="text-[10px] text-amber-200/80 mt-1 max-w-xl truncate">
                          {t.ai_analysis_summary}
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        disabled={actionLoading === t.id}
                        onClick={() => handleReject(t.id)}
                        className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded transition"
                      >
                        Dismiss
                      </button>
                      <button
                        disabled={actionLoading === t.id}
                        onClick={() => handleApprove(t.id)}
                        className="flex items-center gap-1.5 px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded shadow transition"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>{actionLoading === t.id ? "Executing..." : "Approve & Enter"}</span>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Positions Table */}
            {openPositions.length === 0 && plannedTrades.length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-500 text-xs">
                No active positions or pending setups.
              </div>
            ) : openPositions.length > 0 ? (
              <table className="w-full text-left text-xs text-slate-300 font-mono">
                <thead>
                  <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase">
                    <th className="pb-1">Ticket</th>
                    <th className="pb-1">Symbol</th>
                    <th className="pb-1">Type</th>
                    <th className="pb-1">Volume</th>
                    <th className="pb-1">Open Price</th>
                    <th className="pb-1">Current</th>
                    <th className="pb-1">SL</th>
                    <th className="pb-1">TP</th>
                    <th className="pb-1 text-right">PnL (USD)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/40">
                  {openPositions.map((pos) => {
                    const isBuy = pos.type === 0;
                    return (
                      <tr key={pos.ticket} className="hover:bg-slate-900/40">
                        <td className="py-1 text-slate-400">#{pos.ticket}</td>
                        <td className="py-1 font-bold text-white">{pos.symbol}</td>
                        <td className="py-1">
                          <span
                            className={`px-1 py-0.2 rounded text-[10px] font-bold ${
                              isBuy ? "text-emerald-400" : "text-red-400"
                            }`}
                          >
                            {isBuy ? "BUY" : "SELL"}
                          </span>
                        </td>
                        <td className="py-1">{fmtLots(pos.volume)}</td>
                        <td className="py-1">{fmtPrice(pos.price_open)}</td>
                        <td className="py-1">{fmtPrice(pos.price_current)}</td>
                        <td className="py-1 text-red-400">{fmtPrice(pos.sl)}</td>
                        <td className="py-1 text-emerald-400">{fmtPrice(pos.tp)}</td>
                        <td
                          className={`py-1 text-right font-bold ${
                            pos.profit >= 0 ? "text-emerald-400" : "text-red-400"
                          }`}
                        >
                          {fmtUsd(pos.profit, true)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};

