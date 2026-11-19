import React, { useState, useEffect, useMemo } from "react";
import {
  FileText,
  Download,
  AlertOctagon,
  Search,
  Filter,
  CheckCircle,
  XCircle,
  ExternalLink,
  Send,
  Loader2,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Layers,
} from "lucide-react";
import { fmtPrice, fmtUsd, fmtLots, fmtPct, safeArr, safeStr } from "../../utils/format";
import {
  INSTRUMENTS,
  AssetClass,
  getInstrument,
  getAssetClassColor,
  formatSymbolPrice,
} from "../../constants/instruments";
import { api } from "../../services/api";
import { useToast } from "../Toast";

export const TradeBookTab: React.FC = () => {
  const [trades, setTrades] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedAssetClass, setSelectedAssetClass] = useState<"ALL" | AssetClass>("ALL");
  const [filterSymbol, setFilterSymbol] = useState<string>("");
  const [filterMode, setFilterMode] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("");

  // Forensic Post-Mortem Drawer
  const [selectedLossTrade, setSelectedLossTrade] = useState<any | null>(null);
  const [isAnalyzingForensics, setIsAnalyzingForensics] = useState(false);
  const toast = useToast();

  const fetchTrades = async () => {
    setIsLoading(true);
    try {
      const data = safeArr<any>(await api.trades.getHistory({ limit: 150 }));
      setTrades(data);
    } catch (e: any) {
      console.error("Failed to fetch trades:", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTrades();
  }, []);

  const handleRunForensics = async (tradeId: number) => {
    setIsAnalyzingForensics(true);
    try {
      const data = await api.ai.runForensics(tradeId);
      toast.success("Forensic Analysis Complete", `Rule generated: ${data.loss_postmortem_text || "Analysis saved."}`);
      await fetchTrades();
      setSelectedLossTrade((prev: any) =>
        prev ? { ...prev, loss_postmortem_text: data.loss_postmortem_text } : null
      );
    } catch (e: any) {
      toast.error("Forensics Failed", e.message || String(e));
    } finally {
      setIsAnalyzingForensics(false);
    }
  };

  const handleExport = (format: string) => {
    window.open(api.reports.exportUrl(format), "_blank");
  };

  const handleTestTelegram = async () => {
    try {
      const data = await api.telegram.testMessage();
      toast.success("Telegram Test Sent", data.message || "Test alert dispatched to authorized Telegram subscribers.");
    } catch (e: any) {
      toast.error("Telegram Test Failed", e.message || String(e));
    }
  };

  // Filtered trades across 14 symbols, asset classes & trade modes
  const filtered = useMemo(() => {
    return trades.filter((t) => {
      const inst = getInstrument(t.symbol);
      if (selectedAssetClass !== "ALL" && inst.assetClass !== selectedAssetClass) return false;
      if (filterSymbol && !t.symbol.toUpperCase().includes(filterSymbol.toUpperCase())) return false;
      if (filterMode && t.mode !== filterMode) return false;
      if (filterStatus && t.status !== filterStatus) return false;
      return true;
    });
  }, [trades, selectedAssetClass, filterSymbol, filterMode, filterStatus]);

  // Calculate KPIs
  const closedTrades = useMemo(() => filtered.filter((t) => t.status === "CLOSED"), [filtered]);
  const totalNet = useMemo(() => closedTrades.reduce((acc, t) => acc + (t.net_pnl || 0), 0), [closedTrades]);
  const totalGross = useMemo(() => closedTrades.reduce((acc, t) => acc + (t.gross_pnl || 0), 0), [closedTrades]);
  const totalSwap = useMemo(() => closedTrades.reduce((acc, t) => acc + (t.swap || 0), 0), [closedTrades]);
  const winCount = useMemo(() => closedTrades.filter((t) => (t.net_pnl || 0) > 0).length, [closedTrades]);
  const winRate = closedTrades.length > 0 ? (winCount / closedTrades.length) * 100 : 0;
  const maxAbsPnl = useMemo(() => {
    const vals = closedTrades.map((t) => Math.abs(t.net_pnl || 0));
    return Math.max(...vals, 1.0);
  }, [closedTrades]);

  return (
    <div className="space-y-3 font-sans">
      {/* Top KPI Summary & Export Toolbar */}
      <div className="bg-[#0f1623] border border-slate-800/80 rounded-xl p-3.5 flex flex-wrap items-center justify-between gap-4 shadow-lg">
        <div className="flex flex-wrap items-center gap-5 text-xs font-mono">
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Closed Trades</div>
            <div className="font-bold text-white text-sm tabular-nums">{closedTrades.length}</div>
          </div>
          <div className="h-7 w-px bg-slate-800" />
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Win Rate</div>
            <div className="font-bold text-slate-200 text-sm tabular-nums">{fmtPct(winRate)}</div>
          </div>
          <div className="h-7 w-px bg-slate-800" />
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Total Net PnL</div>
            <div
              className={`font-bold text-sm tabular-nums ${
                totalNet >= 0 ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {fmtUsd(totalNet, true)}
            </div>
          </div>
          <div className="h-7 w-px bg-slate-800" />
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Swap Drag</div>
            <div className="font-bold text-amber-400 text-sm tabular-nums">{fmtUsd(totalSwap)}</div>
          </div>
        </div>

        {/* Export Buttons */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => handleExport("csv")}
            className="flex items-center gap-1 px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-slate-300 text-xs font-mono rounded-lg border border-slate-700/80 transition"
          >
            <Download className="w-3 h-3 text-cyan-400" />
            <span>CSV</span>
          </button>
          <button
            onClick={() => handleExport("excel")}
            className="flex items-center gap-1 px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-slate-300 text-xs font-mono rounded-lg border border-slate-700/80 transition"
          >
            <Download className="w-3 h-3 text-cyan-400" />
            <span>Excel</span>
          </button>
          <button
            onClick={() => handleExport("pdf")}
            className="flex items-center gap-1 px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-slate-300 text-xs font-mono rounded-lg border border-slate-700/80 transition"
          >
            <Download className="w-3 h-3 text-cyan-400" />
            <span>PDF</span>
          </button>
          <button
            onClick={handleTestTelegram}
            className="flex items-center gap-1 px-2.5 py-1 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold text-xs font-mono rounded-lg transition"
            title="Dispatch test trade setup card to Telegram"
          >
            <Send className="w-3 h-3" />
            <span>Telegram Test</span>
          </button>
        </div>
      </div>

      {/* Filter Bar with Asset Class Pills + Multi-Pair Select */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-[#0f1623] border border-slate-800/80 rounded-xl p-2.5 text-xs shadow-md">
        {/* Left: Asset Class Pills */}
        <div className="flex items-center gap-1">
          {(["ALL", "FOREX", "COMMODITIES", "CRYPTO"] as const).map((cls) => {
            const isSel = selectedAssetClass === cls;
            return (
              <button
                key={cls}
                onClick={() => setSelectedAssetClass(cls)}
                className={`text-[10px] px-2.5 py-1 rounded-lg font-mono font-medium transition ${
                  isSel
                    ? "bg-cyan-500 text-slate-950 font-bold shadow-sm"
                    : "bg-slate-900 text-slate-400 hover:text-slate-200 border border-slate-800"
                }`}
              >
                {cls === "ALL" ? "All Pairs (14)" : cls === "COMMODITIES" ? "Metals & Oil" : cls}
              </button>
            );
          })}
        </div>

        {/* Right: Search + Dropdowns */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Symbol Search */}
          <div className="flex items-center gap-1.5 bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1">
            <Search className="w-3.5 h-3.5 text-slate-400" />
            <input
              type="text"
              value={filterSymbol}
              onChange={(e) => setFilterSymbol(e.target.value)}
              placeholder="Search symbol (e.g. GOLD, EUR)..."
              className="bg-transparent text-slate-100 placeholder-slate-500 focus:outline-none font-mono text-xs w-44"
            />
          </div>

          {/* 14 Pairs Quick Dropdown */}
          <select
            value={filterSymbol}
            onChange={(e) => setFilterSymbol(e.target.value)}
            className="bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-2 py-1 font-mono text-xs"
          >
            <option value="">All 14 Pairs</option>
            <optgroup label="Forex Majors">
              {INSTRUMENTS.filter((i) => i.assetClass === "FOREX").map((i) => (
                <option key={i.symbol} value={i.symbol}>
                  {i.symbol} ({i.name})
                </option>
              ))}
            </optgroup>
            <optgroup label="Commodities & Energy">
              {INSTRUMENTS.filter((i) => i.assetClass === "COMMODITIES").map((i) => (
                <option key={i.symbol} value={i.symbol}>
                  {i.symbol} ({i.name})
                </option>
              ))}
            </optgroup>
            <optgroup label="Crypto 24/7">
              {INSTRUMENTS.filter((i) => i.assetClass === "CRYPTO").map((i) => (
                <option key={i.symbol} value={i.symbol}>
                  {i.symbol} ({i.name})
                </option>
              ))}
            </optgroup>
          </select>

          {/* Trade Mode Filter */}
          <select
            value={filterMode}
            onChange={(e) => setFilterMode(e.target.value)}
            className="bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-2 py-1 font-mono text-xs"
          >
            <option value="">All Styles</option>
            <option value="SCALP">⚡ SCALP</option>
            <option value="SWING">🌊 SWING</option>
          </select>

          {/* Status Filter */}
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-2 py-1 font-mono text-xs"
          >
            <option value="">All Statuses</option>
            <option value="CLOSED">CLOSED</option>
            <option value="OPEN">OPEN</option>
          </select>
        </div>
      </div>

      {/* Trade Ledger Table with Exact Symbol Decimals & Inline Magnitude Bars */}
      <div className="bg-[#0f1623] border border-slate-800/80 rounded-xl overflow-hidden shadow-lg">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300 font-mono">
            <thead>
              <tr className="border-b border-slate-800 bg-[#080c14] text-[10px] text-slate-500 uppercase sticky top-0">
                <th className="p-3">Ticket / ID</th>
                <th className="p-3">Instrument</th>
                <th className="p-3">Style</th>
                <th className="p-3">Type</th>
                <th className="p-3">Volume</th>
                <th className="p-3">Entry Price</th>
                <th className="p-3">Exit Price</th>
                <th className="p-3">SL / TP</th>
                <th className="p-3">Exit Reason</th>
                <th className="p-3 text-right">Net PnL</th>
                <th className="p-3 text-right">Forensic</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40">
              {isLoading ? (
                <tr>
                  <td colSpan={11} className="p-8 text-center text-slate-400 font-mono">
                    <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-cyan-400" />
                    <span>Hydrating Trade History from MySQL...</span>
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={11} className="p-8 text-center text-slate-500 font-mono">
                    No trades match the selected filter criteria.
                  </td>
                </tr>
              ) : (
                filtered.map((t) => {
                  const isBuy = t.direction === "BUY";
                  const isSlHit = t.exit_reason === "SL_HIT";
                  const inst = getInstrument(t.symbol);
                  const color = getAssetClassColor(inst.assetClass);
                  const pnl = t.net_pnl || 0;
                  const pnlBarPct = Math.min((Math.abs(pnl) / maxAbsPnl) * 100, 100);

                  return (
                    <tr key={t.id} className="hover:bg-slate-900/50 transition relative group">
                      <td className="p-3 text-slate-500 tabular-nums">#{t.position_id || t.id}</td>
                      <td className="p-3">
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-white tracking-wide">{t.symbol}</span>
                          <span className={`text-[8px] px-1 py-0.2 rounded font-mono ${color.badge}`}>
                            {inst.assetClass.slice(0, 3)}
                          </span>
                        </div>
                      </td>
                      <td className="p-3">
                        <span
                          className={`text-[9px] px-1.5 py-0.2 rounded font-mono font-bold ${
                            t.mode === "SCALP"
                              ? "bg-amber-950/60 text-amber-300 border border-amber-800/40"
                              : "bg-indigo-950/60 text-indigo-300 border border-indigo-800/40"
                          }`}
                        >
                          {t.mode}
                        </span>
                      </td>
                      <td className="p-3 font-bold">
                        <span
                          className={`text-[10px] px-1.5 py-0.2 rounded ${
                            isBuy
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800/50"
                              : "bg-rose-950 text-rose-400 border border-rose-800/50"
                          }`}
                        >
                          {t.direction}
                        </span>
                      </td>
                      <td className="p-3 tabular-nums">{fmtLots(t.lots)}</td>
                      <td className="p-3 tabular-nums">{formatSymbolPrice(t.symbol, t.entry_price)}</td>
                      <td className="p-3 tabular-nums text-slate-200">
                        {t.exit_price ? formatSymbolPrice(t.symbol, t.exit_price) : "-"}
                      </td>
                      <td className="p-3 tabular-nums text-[11px]">
                        <span className="text-rose-400">{formatSymbolPrice(t.symbol, t.sl)}</span>
                        <span className="text-slate-600 mx-1">/</span>
                        <span className="text-emerald-400">{formatSymbolPrice(t.symbol, t.tp1 || t.tp2)}</span>
                      </td>
                      <td className="p-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                            isSlHit
                              ? "bg-rose-950/80 text-rose-400 border border-rose-800/60"
                              : t.exit_reason === "TP1_HIT" || t.exit_reason === "TP2_HIT"
                              ? "bg-emerald-950/80 text-emerald-400 border border-emerald-800/60"
                              : "bg-slate-900 text-slate-400"
                          }`}
                        >
                          {t.exit_reason || t.status}
                        </span>
                      </td>
                      <td className="p-3 text-right font-bold tabular-nums relative overflow-hidden">
                        {/* Subtle inline P&L magnitude bar */}
                        <div
                          className={`absolute inset-y-0 right-0 opacity-15 pointer-events-none transition-all ${
                            pnl >= 0 ? "bg-emerald-500" : "bg-rose-500"
                          }`}
                          style={{ width: `${pnlBarPct}%` }}
                        />
                        <span className={pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                          {fmtUsd(pnl, true)}
                        </span>
                      </td>
                      <td className="p-3 text-right">
                        {isSlHit ? (
                          <button
                            onClick={() => setSelectedLossTrade(t)}
                            className="px-2 py-0.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 rounded text-[10px] font-mono transition"
                          >
                            Forensics
                          </button>
                        ) : (
                          <span className="text-slate-600 text-[10px]">-</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Forensic Post-Mortem Modal Drawer */}
      {selectedLossTrade && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#0f1623] border border-rose-500/50 rounded-2xl p-6 max-w-lg w-full shadow-2xl font-mono">
            <div className="flex items-center gap-2 text-rose-400 font-bold text-sm mb-3">
              <AlertOctagon className="w-5 h-5" />
              <span>SL POST-MORTEM FORENSIC: #{selectedLossTrade.position_id || selectedLossTrade.id}</span>
            </div>

            <div className="bg-[#080c14] border border-slate-800 rounded-xl p-3 text-xs space-y-2 mb-4">
              <div className="flex justify-between text-slate-400">
                <span>Symbol:</span>
                <strong className="text-white">{selectedLossTrade.symbol}</strong>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Entry / Exit:</span>
                <span className="tabular-nums">
                  {formatSymbolPrice(selectedLossTrade.symbol, selectedLossTrade.entry_price)} /{" "}
                  {formatSymbolPrice(selectedLossTrade.symbol, selectedLossTrade.exit_price)}
                </span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Net Loss:</span>
                <span className="text-rose-400 font-bold tabular-nums">
                  {fmtUsd(selectedLossTrade.net_pnl, true)}
                </span>
              </div>
              {selectedLossTrade.loss_postmortem_text && (
                <div className="pt-2 border-t border-slate-800 text-[11px] text-slate-300">
                  <div className="text-slate-500 uppercase text-[9px] mb-1">Generated Immune Rule:</div>
                  <div className="p-2 bg-slate-900 rounded border border-slate-700/60 text-cyan-300">
                    {selectedLossTrade.loss_postmortem_text}
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 text-xs font-mono">
              <button
                onClick={() => setSelectedLossTrade(null)}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg"
              >
                Close
              </button>
              <button
                disabled={isAnalyzingForensics}
                onClick={() => handleRunForensics(selectedLossTrade.id)}
                className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold rounded-lg flex items-center gap-1.5 disabled:opacity-50"
              >
                {isAnalyzingForensics ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <span>Synthesize Learned Rule</span>}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
