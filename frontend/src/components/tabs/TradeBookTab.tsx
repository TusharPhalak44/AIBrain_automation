import React, { useState, useEffect } from "react";
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
} from "lucide-react";
import { fmtPrice, fmtUsd, fmtLots, fmtPct, safeArr, safeStr } from "../../utils/format";
import { api } from "../../services/api";
import { useToast } from "../Toast";

export const TradeBookTab: React.FC = () => {
  const [trades, setTrades] = useState<any[]>([]);
  const [filterSymbol, setFilterSymbol] = useState<string>("");
  const [filterMode, setFilterMode] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("");

  // Forensic Post-Mortem Drawer
  const [selectedLossTrade, setSelectedLossTrade] = useState<any | null>(null);
  const [isAnalyzingForensics, setIsAnalyzingForensics] = useState(false);
  const toast = useToast();

  const fetchTrades = async () => {
    try {
      const data = safeArr<any>(await api.trades.getHistory({ limit: 100 }));
      setTrades(data);
    } catch (e: any) {
      console.error("Failed to fetch trades:", e);
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

  // Filtered trades
  const filtered = trades.filter((t) => {
    if (filterSymbol && !t.symbol.toLowerCase().includes(filterSymbol.toLowerCase())) return false;
    if (filterMode && t.mode !== filterMode) return false;
    if (filterStatus && t.status !== filterStatus) return false;
    return true;
  });

  // Calculate KPIs
  const closedTrades = filtered.filter((t) => t.status === "CLOSED");
  const totalNet = closedTrades.reduce((acc, t) => acc + (t.net_pnl || 0), 0);
  const totalGross = closedTrades.reduce((acc, t) => acc + (t.gross_pnl || 0), 0);
  const totalSwap = closedTrades.reduce((acc, t) => acc + (t.swap || 0), 0);
  const winCount = closedTrades.filter((t) => (t.net_pnl || 0) > 0).length;
  const winRate = closedTrades.length > 0 ? (winCount / closedTrades.length) * 100 : 0;

  return (
    <div className="space-y-4">
      {/* Top KPI Summary & Export Toolbar */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-6 text-xs">
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Closed Trades</div>
            <div className="font-bold text-white text-base font-mono">{closedTrades.length}</div>
          </div>
          <div className="h-8 w-px bg-slate-800" />
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Win Rate</div>
            <div className="font-bold text-slate-200 text-base font-mono">{fmtPct(winRate)}</div>
          </div>
          <div className="h-8 w-px bg-slate-800" />
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Total Net PnL</div>
            <div
              className={`font-bold text-base font-mono ${
                totalNet >= 0 ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {fmtUsd(totalNet, true)}
            </div>
          </div>
          <div className="h-8 w-px bg-slate-800" />
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">Total Swap Cost</div>
            <div className="font-bold text-amber-400 text-base font-mono">{fmtUsd(totalSwap)}</div>
          </div>
        </div>

        {/* Export Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleExport("csv")}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700 transition"
          >
            <Download className="w-3.5 h-3.5" />
            <span>CSV</span>
          </button>
          <button
            onClick={() => handleExport("excel")}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700 transition"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Excel</span>
          </button>
          <button
            onClick={() => handleExport("pdf")}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700 transition"
          >
            <Download className="w-3.5 h-3.5" />
            <span>PDF</span>
          </button>
          <button
            onClick={handleTestTelegram}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600/90 hover:bg-blue-600 text-white text-xs font-bold rounded-lg transition"
            title="Dispatch test trade setup card to Telegram"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Telegram Test</span>
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap items-center gap-3 bg-[#121824] border border-slate-800 rounded-xl p-3 text-xs">
        <div className="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1">
          <Search className="w-3.5 h-3.5 text-slate-400" />
          <input
            type="text"
            value={filterSymbol}
            onChange={(e) => setFilterSymbol(e.target.value)}
            placeholder="Search Symbol (e.g. GOLD)"
            className="bg-transparent text-slate-100 placeholder-slate-500 focus:outline-none"
          />
        </div>

        <select
          value={filterMode}
          onChange={(e) => setFilterMode(e.target.value)}
          className="bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-2.5 py-1 font-semibold"
        >
          <option value="">All Modes</option>
          <option value="SCALP">SCALP</option>
          <option value="SWING">SWING</option>
        </select>

        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-2.5 py-1 font-semibold"
        >
          <option value="">All Statuses</option>
          <option value="CLOSED">CLOSED</option>
          <option value="OPEN">OPEN</option>
          <option value="PLANNED">PLANNED</option>
        </select>
      </div>

      {/* Trade Ledger Table */}
      <div className="bg-[#121824] border border-slate-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300 font-mono">
            <thead>
              <tr className="border-b border-slate-800 bg-[#0E131D] text-[10px] text-slate-500 uppercase">
                <th className="p-3">ID</th>
                <th className="p-3">Symbol</th>
                <th className="p-3">Mode</th>
                <th className="p-3">Type</th>
                <th className="p-3">Lots</th>
                <th className="p-3">Entry</th>
                <th className="p-3">Exit</th>
                <th className="p-3">Exit Reason</th>
                <th className="p-3 text-right">Net PnL</th>
                <th className="p-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={10} className="p-6 text-center text-slate-500">
                    No trades match filter criteria.
                  </td>
                </tr>
              ) : (
                filtered.map((t) => {
                  const isBuy = t.direction === "BUY";
                  const isSlHit = t.exit_reason === "SL_HIT";
                  return (
                    <tr key={t.id} className="hover:bg-slate-900/40 transition">
                      <td className="p-3 text-slate-500">#{t.id}</td>
                      <td className="p-3 font-bold text-white">{t.symbol}</td>
                      <td className="p-3">
                        <span className="text-[10px] bg-slate-800 text-slate-300 px-1.5 py-0.2 rounded font-sans">
                          {t.mode}
                        </span>
                      </td>
                      <td className="p-3 font-bold">
                        <span className={isBuy ? "text-emerald-400" : "text-red-400"}>
                          {t.direction}
                        </span>
                      </td>
                      <td className="p-3">{fmtLots(t.lots)}</td>
                      <td className="p-3">{fmtPrice(t.entry_price)}</td>
                      <td className="p-3">{fmtPrice(t.exit_price)}</td>
                      <td className="p-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-sans font-bold ${
                            isSlHit
                              ? "bg-red-950/80 text-red-400 border border-red-800"
                              : "bg-slate-800 text-slate-300"
                          }`}
                        >
                          {t.exit_reason || t.status}
                        </span>
                      </td>
                      <td
                        className={`p-3 text-right font-bold ${
                          (t.net_pnl || 0) >= 0 ? "text-emerald-400" : "text-red-400"
                        }`}
                      >
                        {fmtUsd(t.net_pnl, true)}
                      </td>
                      <td className="p-3 text-right">
                        {isSlHit ? (
                          <button
                            onClick={() => setSelectedLossTrade(t)}
                            className="px-2 py-1 bg-red-950 hover:bg-red-900 text-red-300 font-sans font-bold text-[10px] rounded border border-red-800/80 transition"
                          >
                            Forensics
                          </button>
                        ) : (
                          <span className="text-slate-600">-</span>
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

      {/* SL Post-Mortem Forensic Drawer / Modal */}
      {selectedLossTrade && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-xs z-50 flex items-center justify-center p-4">
          <div className="bg-[#121824] border border-red-500/40 rounded-xl p-6 max-w-lg w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2 text-red-400 font-bold text-sm">
                <AlertOctagon className="w-5 h-5" />
                <span>STOP-LOSS HIT POST-MORTEM FORENSICS</span>
              </div>
              <button
                onClick={() => setSelectedLossTrade(null)}
                className="text-slate-400 hover:text-white text-xs font-bold"
              >
                Close
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between text-slate-300">
                <span>Trade Ticket:</span>
                <strong className="text-white">#{selectedLossTrade.id} ({selectedLossTrade.symbol})</strong>
              </div>
              <div className="flex justify-between text-slate-300">
                <span>Setup & Direction:</span>
                <strong className="text-white">{selectedLossTrade.mode} {selectedLossTrade.direction}</strong>
              </div>
              <div className="flex justify-between text-slate-300">
                <span>Net Loss:</span>
                <strong className="text-red-400 font-mono">{fmtUsd(selectedLossTrade.net_pnl, true)}</strong>
              </div>
              <div className="flex justify-between text-slate-300">
                <span>Exit Price vs Hard SL:</span>
                <strong className="text-white font-mono">
                  {fmtPrice(selectedLossTrade.exit_price)} / {fmtPrice(selectedLossTrade.sl)}
                </strong>
              </div>
            </div>

            {/* Diagnostic Breakdown */}
            <div className="bg-slate-900/90 rounded-lg p-3 border border-slate-800 text-xs">
              <div className="text-[10px] text-slate-400 uppercase font-bold mb-1">
                Forensic Diagnosis & Root Cause
              </div>
              <div className="text-slate-200 leading-relaxed font-sans">
                {safeStr(
                  selectedLossTrade.loss_postmortem_text,
                  "No automated diagnosis text recorded yet. Click 'Run Forensic Post-Mortem' below."
                )}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                disabled={isAnalyzingForensics}
                onClick={() => handleRunForensics(selectedLossTrade.id)}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg text-xs transition"
              >
                {isAnalyzingForensics ? "Analyzing..." : "Run Forensic Post-Mortem"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

