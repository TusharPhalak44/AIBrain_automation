import React, { useEffect, useRef, useState, useMemo } from "react";
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
  ArrowUpRight,
  ArrowDownRight,
  ShieldAlert,
  Loader2,
  Sliders,
  DollarSign,
  Percent,
} from "lucide-react";
import { fmtPrice, fmtUsd, fmtLots, safeArr } from "../../utils/format";
import {
  INSTRUMENTS,
  InstrumentInfo,
  AssetClass,
  getInstrument,
  getAssetClassColor,
  formatSymbolPrice,
  isMarketOpen,
  getSymbolSession,
} from "../../constants/instruments";
import { OpenPosition, PlannedTrade, PairSchedule, QuoteData, PendingOrder } from "../../hooks/useLiveStore";
import { api } from "../../services/api";
import { useToast } from "../Toast";

interface CockpitTabProps {
  selectedSymbol: string;
  selectedTimeframe: string;
  isMt5Connected: boolean;
  executionMode?: string;
  openPositions: OpenPosition[];
  pendingOrders?: PendingOrder[];
  plannedTrades?: PlannedTrade[];
  pairSchedules: Record<string, PairSchedule>;
  quotes?: Record<string, QuoteData>;
  equity?: number;
  balance?: number;
  onSelectSymbol: (symbol: string) => void;
  onSelectTimeframe: (tf: string) => void;
  onApproveCopilot?: (tradeId: number) => Promise<any>;
  onRejectCopilot?: (tradeId: number) => Promise<any>;
}

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

export const CockpitTab: React.FC<CockpitTabProps> = ({
  selectedSymbol,
  selectedTimeframe,
  isMt5Connected,
  executionMode = "AUTO",
  openPositions,
  pendingOrders = [],
  plannedTrades = [],
  pairSchedules,
  quotes = {},
  equity = 100.0,
  balance = 100.0,
  onSelectSymbol,
  onSelectTimeframe,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  const [isLoadingChart, setIsLoadingChart] = useState(false);
  const [chartStatus, setChartStatus] = useState<string>("OK");
  const [candleCount, setCandleCount] = useState<number>(0);
  const [overlays, setOverlays] = useState<any>({});
  const [bottomTab, setBottomTab] = useState<"POSITIONS" | "LIMITS" | "EXECUTE">("POSITIONS");
  const [marketWatchClass, setMarketWatchClass] = useState<"ALL" | AssetClass>("ALL");
  const [closingTicket, setClosingTicket] = useState<number | null>(null);
  const toast = useToast();

  // Manual Execution Form State
  const activeInst = useMemo(() => getInstrument(selectedSymbol), [selectedSymbol]);
  const activeQuote = quotes[selectedSymbol] || quotes[selectedSymbol.replace("#", "")] || {
    bid: 0,
    ask: 0,
    spread_points: activeInst.defaultSpread,
  };

  const [orderLots, setOrderLots] = useState<number>(0.01);
  const [slPrice, setSlPrice] = useState<string>("");
  const [tpPrice, setTpPrice] = useState<string>("");
  const [isExecuting, setIsExecuting] = useState(false);

  // Initialize default SL/TP whenever symbol or live price updates if inputs are empty
  useEffect(() => {
    if (activeQuote.bid > 0) {
      const step = 1 / Math.pow(10, activeInst.digits);
      const slDist = (activeInst.defaultSpread * 3 * step) || 1.0;
      // Default to 1.5R SL/TP suggestion for convenience
      if (!slPrice) {
        setSlPrice(formatSymbolPrice(selectedSymbol, activeQuote.bid - slDist));
      }
      if (!tpPrice) {
        setTpPrice(formatSymbolPrice(selectedSymbol, activeQuote.ask + slDist * 2));
      }
    }
  }, [selectedSymbol]);

  // Initialize and update Lightweight Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#080c14" },
        textColor: "#94A3B8",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#131b2c" },
        horzLines: { color: "#131b2c" },
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
      color: "#06B6D4",
      priceFormat: {
        type: "volume",
      },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.82,
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
  }, [selectedSymbol, selectedTimeframe]);

  // Close position handler
  const handleClosePosition = async (ticket: number) => {
    setClosingTicket(ticket);
    try {
      const res = await api.trades.closePosition(ticket);
      toast.success("Position Closed", res.message || `Position #${ticket} successfully closed.`);
    } catch (e: any) {
      toast.error("Close Failed", e.message || String(e));
    } finally {
      setClosingTicket(null);
    }
  };

  // Manual Buy/Sell Execution
  const handleExecuteOrder = async (orderType: "BUY" | "SELL") => {
    const sl = parseFloat(slPrice);
    const tp = tpPrice ? parseFloat(tpPrice) : undefined;

    if (!sl || isNaN(sl) || sl <= 0) {
      toast.error("Mandatory SL Missing", "A hard Stop Loss price is strictly required (Zero Naked Trades).");
      return;
    }

    const currentPrice = orderType === "BUY" ? activeQuote.ask : activeQuote.bid;
    if (orderType === "BUY" && sl >= currentPrice) {
      toast.error("Invalid SL Geometry", `For BUY, Stop Loss (${sl}) must be strictly below current Ask (${currentPrice}).`);
      return;
    }
    if (orderType === "SELL" && sl <= currentPrice) {
      toast.error("Invalid SL Geometry", `For SELL, Stop Loss (${sl}) must be strictly above current Bid (${currentPrice}).`);
      return;
    }

    setIsExecuting(true);
    try {
      const res = await api.trades.executeManualOrder({
        symbol: selectedSymbol,
        order_type: orderType,
        lots: orderLots,
        sl: sl,
        tp: tp,
        comment: `Manual Portal ${selectedTimeframe}`,
      });
      toast.success(
        `Order Executed: ${orderType} ${orderLots} ${selectedSymbol}`,
        `Executed at ${res.executed_price ?? currentPrice} (Ticket #${res.ticket ?? "NEW"})`
      );
    } catch (e: any) {
      toast.error("Order Execution Failed", e.message || String(e));
    } finally {
      setIsExecuting(false);
    }
  };

  // Filter Market Watch instruments
  const filteredInstruments = useMemo(() => {
    if (marketWatchClass === "ALL") return INSTRUMENTS;
    return INSTRUMENTS.filter((i) => i.assetClass === marketWatchClass);
  }, [marketWatchClass]);

  // Dynamic Margin & Risk calculations
  const priceReference = activeQuote.ask || activeQuote.bid || 1.0;
  const estMarginUsd = (orderLots * activeInst.contractSize * priceReference) / 100.0; // 1:100 leverage assumed
  const marginPctOfEquity = equity > 0 ? (estMarginUsd / equity) * 100 : 0;
  const slDist = slPrice ? Math.abs(priceReference - parseFloat(slPrice)) : 0;
  const estRiskUsd = slDist > 0 ? (slDist / (activeInst.tickSize || 0.01)) * activeInst.tickValue * orderLots : 0;
  const riskPctOfEquity = equity > 0 ? (estRiskUsd / equity) * 100 : 0;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 h-[calc(100vh-100px)] min-h-[640px]">
      {/* Left Column: 14-Pair Market Watch (3 cols) */}
      <div className="lg:col-span-3 bg-[#0f1623] border border-slate-800/80 rounded-xl flex flex-col overflow-hidden shadow-lg">
        {/* Header & Asset Class Filter Pills */}
        <div className="p-2.5 border-b border-slate-800 bg-[#080c14]">
          <div className="flex items-center justify-between mb-2">
            <span className="font-bold text-slate-100 text-xs font-mono tracking-wider flex items-center gap-1.5">
              <span>MARKET WATCH</span>
              <span className="text-[9px] bg-cyan-950 text-cyan-400 px-1.5 py-0.2 rounded font-semibold border border-cyan-800/40">
                14 PAIRS
              </span>
            </span>
            <span className="text-[10px] text-slate-400 font-mono">1s LIVE</span>
          </div>

          <div className="flex items-center gap-1 overflow-x-auto scrollbar-none">
            {(["ALL", "FOREX", "COMMODITIES", "CRYPTO"] as const).map((cls) => {
              const isSel = marketWatchClass === cls;
              return (
                <button
                  key={cls}
                  onClick={() => setMarketWatchClass(cls)}
                  className={`text-[9px] px-2 py-0.5 rounded font-mono font-medium transition ${
                    isSel
                      ? "bg-cyan-500 text-slate-950 font-bold"
                      : "bg-slate-800/80 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {cls === "ALL" ? "All (14)" : cls === "COMMODITIES" ? "Metals" : cls}
                </button>
              );
            })}
          </div>
        </div>

        {/* 14 Pairs Scrollable List */}
        <div className="flex-1 overflow-y-auto divide-y divide-slate-800/50 p-1">
          {filteredInstruments.map((item) => {
            const isSelected = selectedSymbol === item.symbol;
            const sched = pairSchedules[item.symbol];
            const countdown = sched?.next_scan_seconds ?? sched?.seconds_remaining ?? 60;
            const q = quotes[item.symbol] || quotes[item.symbol.replace("#", "")];
            const color = getAssetClassColor(item.assetClass);
            const openState = isMarketOpen(item.symbol);

            return (
              <button
                key={item.symbol}
                onClick={() => onSelectSymbol(item.symbol)}
                className={`w-full p-2 rounded-lg text-left transition flex items-center justify-between group ${
                  isSelected
                    ? "bg-cyan-950/40 border border-cyan-500/50 shadow-[0_0_12px_rgba(6,182,212,0.15)]"
                    : "hover:bg-slate-800/40 border border-transparent"
                }`}
              >
                <div>
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        openState ? "bg-emerald-400" : "bg-slate-600"
                      }`}
                    />
                    <span className="font-bold text-slate-100 text-xs font-mono group-hover:text-cyan-300">
                      {item.symbol}
                    </span>
                    <span className={`text-[8px] px-1 py-0.2 rounded font-mono ${color.badge}`}>
                      {item.assetClass.slice(0, 3)}
                    </span>
                    {item.is24_7 && (
                      <span className="text-[8px] bg-purple-950 text-purple-300 border border-purple-800 px-1 rounded font-mono">
                        24/7
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5 truncate max-w-[130px]">
                    {item.name}
                  </div>

                  {q && q.bid > 0 ? (
                    <div className="flex items-center gap-1.5 mt-1 text-[10px] font-mono tabular-nums">
                      <span className="text-emerald-400 font-bold">{q.bid.toFixed(item.digits)}</span>
                      <span className="text-slate-600">/</span>
                      <span className="text-slate-200">{q.ask.toFixed(item.digits)}</span>
                      <span className="text-[9px] bg-slate-950 text-amber-400 px-1 rounded border border-amber-500/30">
                        {q.spread_points ?? item.defaultSpread} pt
                      </span>
                    </div>
                  ) : null}
                </div>

                <div className="text-right">
                  <div className="text-[10px] font-mono text-slate-400 flex items-center gap-1 justify-end tabular-nums">
                    <Clock className="w-2.5 h-2.5 text-slate-500" />
                    <span>{countdown}s</span>
                  </div>
                  <div className="text-[9px] text-cyan-400 mt-0.5 font-semibold font-mono">
                    {sched?.status || "MONITORING"}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Center & Right Column: Chart + Dual Execution + Tables (9 cols) */}
      <div className="lg:col-span-9 flex flex-col gap-2.5 h-full overflow-hidden">
        {/* Top: Chart View Container */}
        <div className="flex-1 bg-[#0f1623] border border-slate-800/80 rounded-xl flex flex-col overflow-hidden relative shadow-lg">
          {/* Chart Header Bar */}
          <div className="px-3 py-1.5 border-b border-slate-800 bg-[#080c14] flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-100 text-sm font-mono tracking-wide">
                  {selectedSymbol}
                </span>
                <span className="text-[10px] text-slate-400 font-mono">
                  {activeInst.name}
                </span>
              </div>

              {/* Timeframe Selector Matrix */}
              <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded border border-slate-800">
                {TIMEFRAMES.map((tf) => (
                  <button
                    key={tf}
                    onClick={() => onSelectTimeframe(tf)}
                    className={`px-2 py-0.5 text-[10px] font-semibold font-mono rounded transition ${
                      selectedTimeframe === tf
                        ? "bg-cyan-500 text-slate-950 font-bold shadow-sm"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {tf}
                  </button>
                ))}
              </div>
            </div>

            {/* Price-Action Overlays Info */}
            <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
              {overlays.pdh && (
                <span className="bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                  PDH: <strong className="text-slate-200">{formatSymbolPrice(selectedSymbol, overlays.pdh)}</strong>
                </span>
              )}
              {overlays.pdl && (
                <span className="bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                  PDL: <strong className="text-slate-200">{formatSymbolPrice(selectedSymbol, overlays.pdl)}</strong>
                </span>
              )}
              {safeArr(overlays.fvgs).length > 0 && (
                <span className="bg-cyan-950/60 text-cyan-400 px-1.5 py-0.5 rounded border border-cyan-800/40">
                  FVG: {safeArr(overlays.fvgs).length} Active
                </span>
              )}
              {activeQuote.spread_points !== undefined && (
                <span className="bg-amber-950/50 text-amber-400 px-1.5 py-0.5 rounded border border-amber-800/40 tabular-nums">
                  Spread: {activeQuote.spread_points} pts
                </span>
              )}
            </div>
          </div>

          {/* Chart Canvas */}
          <div className="flex-1 w-full h-full relative" ref={chartContainerRef}>
            {((!isMt5Connected || chartStatus === "MT5_DISCONNECTED") && candleCount === 0) && (
              <div className="absolute inset-0 bg-black/80 backdrop-blur-xs flex flex-col items-center justify-center z-20 text-center p-6">
                <div className="w-12 h-12 rounded-full bg-rose-950/80 border border-rose-500/50 flex items-center justify-center mb-3 text-rose-400 shadow-[0_0_15px_rgba(244,63,94,0.3)]">
                  <Radio className="w-6 h-6 animate-pulse" />
                </div>
                <h3 className="text-sm font-bold text-white mb-1 font-mono">XM MT5 Terminal Disconnected</h3>
                <p className="text-slate-400 text-xs max-w-sm">
                  Candlestick feed is paused. Strictly zero mock or synthetic fallback candles are rendered.
                  Connect your XM MT5 profile in Settings to stream live institutional ticks.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Bottom Panel: Dual Action Order Panel + Open Positions / Limits */}
        <div className="h-60 bg-[#0f1623] border border-slate-800/80 rounded-xl flex flex-col overflow-hidden shadow-lg">
          {/* Header Sub-Tabs */}
          <div className="px-3 py-1.5 border-b border-slate-800 bg-[#080c14] flex items-center justify-between text-xs font-bold text-slate-300">
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setBottomTab("POSITIONS")}
                className={`flex items-center gap-1.5 px-3 py-1 rounded font-mono text-[11px] transition ${
                  bottomTab === "POSITIONS"
                    ? "bg-cyan-500/20 text-cyan-400 border border-cyan-500/40"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Layers className="w-3.5 h-3.5" />
                <span>Open Positions ({openPositions.length})</span>
              </button>

              <button
                onClick={() => setBottomTab("LIMITS")}
                className={`flex items-center gap-1.5 px-3 py-1 rounded font-mono text-[11px] transition ${
                  bottomTab === "LIMITS"
                    ? "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Clock className="w-3.5 h-3.5" />
                <span>Resting Limits ({pendingOrders.length})</span>
              </button>

              <button
                onClick={() => setBottomTab("EXECUTE")}
                className={`flex items-center gap-1.5 px-3 py-1 rounded font-mono text-[11px] transition ${
                  bottomTab === "EXECUTE"
                    ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <DollarSign className="w-3.5 h-3.5" />
                <span>Manual Order Execution</span>
              </button>
            </div>

            <span className="hidden sm:flex items-center gap-1.5 text-[10px] font-mono font-bold text-emerald-400 bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-800/60">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
              <span>PURE AUTO & LIMIT CAPABLE</span>
            </span>
          </div>

          {/* Body Content */}
          <div className="flex-1 overflow-y-auto p-2.5">
            {bottomTab === "EXECUTE" ? (
              /* DUAL ACTION EXECUTION PANEL */
              <div className="grid grid-cols-1 md:grid-cols-12 gap-3 h-full">
                {/* Left: Input Parameters (5 cols) */}
                <div className="md:col-span-5 bg-[#080c14] border border-slate-800 rounded-lg p-2.5 flex flex-col justify-between text-xs font-mono">
                  <div className="space-y-2">
                    {/* Volume Input + Quick Steppers */}
                    <div>
                      <div className="flex justify-between items-center text-slate-400 text-[10px] mb-1">
                        <span>VOLUME (LOTS)</span>
                        <span className="text-cyan-400">Step: 0.01</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setOrderLots((prev) => Math.max(0.01, +(prev - 0.01).toFixed(2)))}
                          className="px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-slate-300 font-bold"
                        >
                          -
                        </button>
                        <input
                          type="number"
                          step="0.01"
                          min="0.01"
                          max="100.0"
                          value={orderLots}
                          onChange={(e) => setOrderLots(Math.max(0.01, parseFloat(e.target.value) || 0.01))}
                          className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-center text-white font-bold tabular-nums"
                        />
                        <button
                          type="button"
                          onClick={() => setOrderLots((prev) => +(prev + 0.01).toFixed(2))}
                          className="px-2 py-1 bg-slate-800 hover:bg-slate-700 rounded text-slate-300 font-bold"
                        >
                          +
                        </button>
                      </div>
                      <div className="flex items-center gap-1 mt-1">
                        {[0.01, 0.02, 0.05, 0.1, 0.5].map((preset) => (
                          <button
                            key={preset}
                            type="button"
                            onClick={() => setOrderLots(preset)}
                            className={`flex-1 text-[9px] py-0.5 rounded transition ${
                              orderLots === preset ? "bg-cyan-500 text-slate-950 font-bold" : "bg-slate-900 text-slate-400 hover:bg-slate-800"
                            }`}
                          >
                            {preset}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Hard SL & TP Inputs with Exact Decimal Precision */}
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="text-[10px] text-rose-400 font-bold block mb-0.5">
                          STOP LOSS (HARD)
                        </label>
                        <input
                          type="number"
                          step={1 / Math.pow(10, activeInst.digits)}
                          value={slPrice}
                          onChange={(e) => setSlPrice(e.target.value)}
                          placeholder={`SL (${activeInst.digits} dec)`}
                          className="w-full bg-slate-900 border border-rose-500/40 rounded px-2 py-1 text-rose-300 text-xs font-mono tabular-nums focus:outline-none focus:border-rose-400"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] text-emerald-400 font-bold block mb-0.5">
                          TAKE PROFIT (OPT)
                        </label>
                        <input
                          type="number"
                          step={1 / Math.pow(10, activeInst.digits)}
                          value={tpPrice}
                          onChange={(e) => setTpPrice(e.target.value)}
                          placeholder={`TP (${activeInst.digits} dec)`}
                          className="w-full bg-slate-900 border border-emerald-500/40 rounded px-2 py-1 text-emerald-300 text-xs font-mono tabular-nums focus:outline-none focus:border-emerald-400"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Real-time Margin & Risk Preview */}
                  <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] text-slate-400">
                    <div>
                      <span>Margin: </span>
                      <strong className="text-white tabular-nums">{fmtUsd(estMarginUsd)}</strong>
                      <span className="text-slate-500"> ({marginPctOfEquity.toFixed(1)}%)</span>
                    </div>
                    <div>
                      <span>Risk: </span>
                      <strong className="text-rose-400 tabular-nums">{fmtUsd(estRiskUsd)}</strong>
                      <span className="text-slate-500"> ({riskPctOfEquity.toFixed(1)}%)</span>
                    </div>
                  </div>
                </div>

                {/* Right: Dual Action Buttons (SELL vs BUY) (7 cols) */}
                <div className="md:col-span-7 grid grid-cols-2 gap-3">
                  {/* SELL BUTTON CARD */}
                  <button
                    type="button"
                    disabled={isExecuting || !isMt5Connected}
                    onClick={() => handleExecuteOrder("SELL")}
                    className="bg-[#180e14] hover:bg-[#22121c] border border-rose-500/40 hover:border-rose-500 rounded-xl p-3 flex flex-col justify-between text-left transition group disabled:opacity-50 disabled:pointer-events-none shadow-md shadow-rose-950/30"
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-rose-400 text-xs font-mono flex items-center gap-1">
                          <ArrowDownRight className="w-4 h-4" />
                          <span>SELL / SHORT</span>
                        </span>
                        <span className="text-[9px] bg-rose-950 text-rose-300 px-1.5 py-0.2 rounded border border-rose-800/40 font-mono">
                          BID
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-400 mt-1 font-mono">{selectedSymbol}</div>
                    </div>

                    <div className="my-2">
                      <div className="text-xl font-bold font-mono text-rose-400 tabular-nums tracking-wide">
                        {activeQuote.bid > 0 ? activeQuote.bid.toFixed(activeInst.digits) : "-"}
                      </div>
                      <div className="text-[10px] text-slate-500 font-mono">
                        Instant Market Fill · SL Protected
                      </div>
                    </div>

                    <div className="w-full py-1.5 bg-rose-600 group-hover:bg-rose-500 text-white font-bold rounded-lg text-center text-xs font-mono flex items-center justify-center gap-1.5">
                      {isExecuting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <span>EXECUTE SELL</span>}
                    </div>
                  </button>

                  {/* BUY BUTTON CARD */}
                  <button
                    type="button"
                    disabled={isExecuting || !isMt5Connected}
                    onClick={() => handleExecuteOrder("BUY")}
                    className="bg-[#0e1814] hover:bg-[#12221c] border border-emerald-500/40 hover:border-emerald-500 rounded-xl p-3 flex flex-col justify-between text-left transition group disabled:opacity-50 disabled:pointer-events-none shadow-md shadow-emerald-950/30"
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-emerald-400 text-xs font-mono flex items-center gap-1">
                          <ArrowUpRight className="w-4 h-4" />
                          <span>BUY / LONG</span>
                        </span>
                        <span className="text-[9px] bg-emerald-950 text-emerald-300 px-1.5 py-0.2 rounded border border-emerald-800/40 font-mono">
                          ASK
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-400 mt-1 font-mono">{selectedSymbol}</div>
                    </div>

                    <div className="my-2">
                      <div className="text-xl font-bold font-mono text-emerald-400 tabular-nums tracking-wide">
                        {activeQuote.ask > 0 ? activeQuote.ask.toFixed(activeInst.digits) : "-"}
                      </div>
                      <div className="text-[10px] text-slate-500 font-mono">
                        Instant Market Fill · SL Protected
                      </div>
                    </div>

                    <div className="w-full py-1.5 bg-emerald-600 group-hover:bg-emerald-500 text-white font-bold rounded-lg text-center text-xs font-mono flex items-center justify-center gap-1.5">
                      {isExecuting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <span>EXECUTE BUY</span>}
                    </div>
                  </button>
                </div>
              </div>
            ) : bottomTab === "POSITIONS" ? (
              /* OPEN POSITIONS TABLE WITH 1-CLICK CLOSE */
              openPositions.length === 0 ? (
                <div className="h-full flex items-center justify-center text-slate-500 text-xs font-mono">
                  No active open positions on MT5 broker.
                </div>
              ) : (
                <table className="w-full text-left text-xs text-slate-300 font-mono">
                  <thead>
                    <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase sticky top-0 bg-[#0f1623]">
                      <th className="pb-1.5">Ticket</th>
                      <th className="pb-1.5">Symbol</th>
                      <th className="pb-1.5">Type</th>
                      <th className="pb-1.5">Volume</th>
                      <th className="pb-1.5">Open Price</th>
                      <th className="pb-1.5">Current</th>
                      <th className="pb-1.5">Stop Loss</th>
                      <th className="pb-1.5">Take Profit</th>
                      <th className="pb-1.5 text-right">PnL (USD)</th>
                      <th className="pb-1.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/40">
                    {openPositions.map((pos) => {
                      const isBuy = pos.type === 0;
                      const inst = getInstrument(pos.symbol);
                      const color = getAssetClassColor(inst.assetClass);
                      return (
                        <tr key={pos.ticket} className="hover:bg-slate-900/50 transition">
                          <td className="py-1.5 text-slate-400">#{pos.ticket}</td>
                          <td className="py-1.5">
                            <span className="font-bold text-white mr-1.5">{pos.symbol}</span>
                            <span className={`text-[8px] px-1 py-0.2 rounded font-mono ${color.badge}`}>
                              {inst.assetClass.slice(0, 3)}
                            </span>
                          </td>
                          <td className="py-1.5">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                isBuy
                                  ? "bg-emerald-950 text-emerald-400 border border-emerald-800/60"
                                  : "bg-rose-950 text-rose-400 border border-rose-800/60"
                              }`}
                            >
                              {isBuy ? "BUY" : "SELL"}
                            </span>
                          </td>
                          <td className="py-1.5 tabular-nums">{fmtLots(pos.volume)}</td>
                          <td className="py-1.5 tabular-nums">{formatSymbolPrice(pos.symbol, pos.price_open)}</td>
                          <td className="py-1.5 tabular-nums text-slate-100">{formatSymbolPrice(pos.symbol, pos.price_current)}</td>
                          <td className="py-1.5 tabular-nums text-rose-400">{formatSymbolPrice(pos.symbol, pos.sl)}</td>
                          <td className="py-1.5 tabular-nums text-emerald-400">{formatSymbolPrice(pos.symbol, pos.tp)}</td>
                          <td
                            className={`py-1.5 text-right font-bold tabular-nums ${
                              pos.profit >= 0 ? "text-emerald-400" : "text-rose-400"
                            }`}
                          >
                            {fmtUsd(pos.profit, true)}
                          </td>
                          <td className="py-1.5 text-right">
                            <button
                              disabled={closingTicket === pos.ticket}
                              onClick={() => handleClosePosition(pos.ticket)}
                              className="px-2 py-0.5 bg-rose-600/80 hover:bg-rose-600 text-white rounded text-[10px] font-bold font-mono transition disabled:opacity-50"
                            >
                              {closingTicket === pos.ticket ? "Closing..." : "Close"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )
            ) : (
              /* RESTING LIMIT ORDERS TABLE */
              pendingOrders.length === 0 ? (
                <div className="h-full flex items-center justify-center text-slate-500 text-xs font-mono">
                  No resting limit orders on MT5 broker.
                </div>
              ) : (
                <table className="w-full text-left text-xs text-slate-300 font-mono">
                  <thead>
                    <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase sticky top-0 bg-[#0f1623]">
                      <th className="pb-1.5">Ticket</th>
                      <th className="pb-1.5">Symbol</th>
                      <th className="pb-1.5">Order Type</th>
                      <th className="pb-1.5">Volume</th>
                      <th className="pb-1.5">Limit Price</th>
                      <th className="pb-1.5">Stop Loss</th>
                      <th className="pb-1.5">Take Profit</th>
                      <th className="pb-1.5">Comment</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/40">
                    {pendingOrders.map((ord) => (
                      <tr key={ord.ticket} className="hover:bg-slate-900/50 transition">
                        <td className="py-1.5 text-slate-400">#{ord.ticket}</td>
                        <td className="py-1.5 font-bold text-white">{ord.symbol}</td>
                        <td className="py-1.5">
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-950/80 text-amber-300 border border-amber-800/60">
                            {ord.type_desc || "LIMIT"}
                          </span>
                        </td>
                        <td className="py-1.5 tabular-nums">{fmtLots(ord.volume)}</td>
                        <td className="py-1.5 text-amber-300 font-bold tabular-nums">
                          {formatSymbolPrice(ord.symbol, ord.price_open)}
                        </td>
                        <td className="py-1.5 text-rose-400 tabular-nums">
                          {formatSymbolPrice(ord.symbol, ord.sl)}
                        </td>
                        <td className="py-1.5 text-emerald-400 tabular-nums">
                          {formatSymbolPrice(ord.symbol, ord.tp)}
                        </td>
                        <td className="py-1.5 text-slate-400 truncate max-w-[150px]">{ord.comment || "AUTO_LIMIT"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
