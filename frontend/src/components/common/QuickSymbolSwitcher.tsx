import React, { useState, useEffect, useMemo, useRef } from "react";
import { Search, Command, ArrowRight, Zap, Check } from "lucide-react";
import {
  INSTRUMENTS,
  InstrumentInfo,
  getAssetClassColor,
  isMarketOpen,
  getSymbolSession,
} from "../../constants/instruments";

interface QuickSymbolSwitcherProps {
  isOpen: boolean;
  onClose: () => void;
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
  quotes?: Record<string, { bid: number; ask: number; spread_points?: number }>;
}

export const QuickSymbolSwitcher: React.FC<QuickSymbolSwitcherProps> = ({
  isOpen,
  onClose,
  selectedSymbol,
  onSelectSymbol,
  quotes = {},
}) => {
  const [search, setSearch] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setSearch("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  const filtered = useMemo(() => {
    if (!search.trim()) return INSTRUMENTS;
    const q = search.toLowerCase();
    return INSTRUMENTS.filter(
      (inst) =>
        inst.symbol.toLowerCase().includes(q) ||
        inst.name.toLowerCase().includes(q) ||
        inst.displaySymbol.toLowerCase().includes(q) ||
        inst.assetClass.toLowerCase().includes(q)
    );
  }, [search]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [search]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filtered.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filtered.length) % Math.max(1, filtered.length));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[selectedIndex]) {
        onSelectSymbol(filtered[selectedIndex].symbol);
        onClose();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/75 backdrop-blur-sm transition-opacity" onClick={onClose} />

      {/* Modal Card */}
      <div
        className="relative w-full max-w-xl bg-[#0a0f18] border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col z-10 font-sans"
        onKeyDown={handleKeyDown}
      >
        {/* Search Header */}
        <div className="p-3.5 border-b border-slate-800 bg-[#070b12] flex items-center gap-3">
          <Search className="w-4 h-4 text-cyan-400" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search 14 XM Ultra Low pairs (e.g. GOLD, BTC, EUR, 24/7)..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-500 focus:outline-none font-mono"
          />
          <div className="flex items-center gap-1 text-[10px] text-slate-400 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded font-mono">
            <span>ESC to close</span>
          </div>
        </div>

        {/* Results List */}
        <div className="max-h-96 overflow-y-auto divide-y divide-slate-800/40 p-2">
          {filtered.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-500">
              No matching instruments found for "{search}".
            </div>
          ) : (
            filtered.map((inst, idx) => {
              const isHighlight = idx === selectedIndex;
              const isCurrent = inst.symbol === selectedSymbol;
              const color = getAssetClassColor(inst.assetClass);
              const q = quotes[inst.symbol] || quotes[inst.symbol.replace("#", "")];
              const open = isMarketOpen(inst.symbol);

              return (
                <div
                  key={inst.symbol}
                  onClick={() => {
                    onSelectSymbol(inst.symbol);
                    onClose();
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`px-3 py-2.5 rounded-xl cursor-pointer transition flex items-center justify-between ${
                    isHighlight
                      ? "bg-cyan-950/40 border border-cyan-500/40"
                      : "hover:bg-slate-900/60 border border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        open ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" : "bg-slate-600"
                      }`}
                    />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-slate-100 text-sm font-mono tracking-wide">
                          {inst.symbol}
                        </span>
                        <span className={`text-[9px] px-1.5 py-0.2 rounded font-mono ${color.badge}`}>
                          {inst.assetClass}
                        </span>
                        {inst.is24_7 && (
                          <span className="text-[8px] bg-purple-950 text-purple-300 border border-purple-800 px-1 rounded font-mono">
                            24/7 CFD
                          </span>
                        )}
                        {isCurrent && (
                          <span className="text-[9px] bg-emerald-950/80 text-emerald-400 border border-emerald-800 px-1.5 py-0.2 rounded font-mono">
                            CURRENT
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-0.5">
                        {inst.displaySymbol} · {inst.name}
                      </div>
                    </div>
                  </div>

                  <div className="text-right flex items-center gap-3">
                    {q && q.bid > 0 ? (
                      <div className="text-right font-mono tabular-nums text-xs">
                        <div className="text-emerald-400 font-bold">{q.bid.toFixed(inst.digits)}</div>
                        {q.spread_points !== undefined && (
                          <div className="text-[10px] text-amber-400">{q.spread_points} pt spread</div>
                        )}
                      </div>
                    ) : (
                      <div className="text-[10px] text-slate-500 font-mono">
                        {getSymbolSession(inst.symbol)}
                      </div>
                    )}

                    {isHighlight && <ArrowRight className="w-4 h-4 text-cyan-400 animate-pulse" />}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="p-2.5 border-t border-slate-800 bg-[#070b12] flex items-center justify-between text-[11px] text-slate-500 font-mono">
          <div className="flex items-center gap-3">
            <span>↑↓ Navigate</span>
            <span>↵ Select Pair</span>
          </div>
          <span>14 High-Liquidity XM Instruments</span>
        </div>
      </div>
    </div>
  );
};
