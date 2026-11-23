import React, { useState, useMemo } from "react";
import { Search, ChevronDown, Check, Globe } from "lucide-react";
import {
  INSTRUMENTS,
  InstrumentInfo,
  AssetClass,
  getAssetClassColor,
  isMarketOpen,
  getSymbolSession,
} from "../../constants/instruments";

interface InstrumentSelectorProps {
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
  quotes?: Record<string, { bid: number; ask: number; spread_points?: number }>;
  showCompact?: boolean;
  className?: string;
}

export const InstrumentSelector: React.FC<InstrumentSelectorProps> = ({
  selectedSymbol,
  onSelectSymbol,
  quotes = {},
  showCompact = false,
  className = "",
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedClass, setSelectedClass] = useState<"ALL" | AssetClass>("ALL");

  const selectedInst = useMemo(
    () => INSTRUMENTS.find((i) => i.symbol === selectedSymbol) || INSTRUMENTS[6],
    [selectedSymbol]
  );

  const filteredInstruments = useMemo(() => {
    return INSTRUMENTS.filter((inst) => {
      if (selectedClass !== "ALL" && inst.assetClass !== selectedClass) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          inst.symbol.toLowerCase().includes(q) ||
          inst.name.toLowerCase().includes(q) ||
          inst.displaySymbol.toLowerCase().includes(q) ||
          inst.assetClass.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [search, selectedClass]);

  const activeColor = getAssetClassColor(selectedInst.assetClass);
  const openState = isMarketOpen(selectedSymbol);

  return (
    <div className={`relative ${className}`}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center justify-between gap-2.5 px-3 py-1.5 rounded-lg border bg-[#0f1623] hover:bg-[#151f32] transition text-left ${activeColor.border}`}
      >
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${
              openState ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" : "bg-slate-500"
            }`}
          />
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-slate-100 text-xs font-mono tracking-wide">
                {selectedInst.symbol}
              </span>
              <span className={`text-[9px] px-1 py-0.2 rounded font-mono ${activeColor.badge}`}>
                {selectedInst.assetClass}
              </span>
            </div>
            {!showCompact && (
              <div className="text-[10px] text-slate-400 truncate max-w-[130px]">
                {selectedInst.displaySymbol} · {selectedInst.name}
              </div>
            )}
          </div>
        </div>

        <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />

          <div className="absolute left-0 top-full mt-1.5 w-80 max-h-[460px] bg-[#0c121e] border border-slate-700/80 rounded-xl shadow-2xl z-50 flex flex-col overflow-hidden backdrop-blur-md">
            {/* Search Header */}
            <div className="p-2.5 border-b border-slate-800 bg-[#080c14]">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Search 14 symbols (e.g. GOLD, EUR, BTC)..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  autoFocus
                  className="w-full bg-[#121927] border border-slate-700/80 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>

              {/* Asset Class Filter Pills */}
              <div className="flex items-center gap-1 mt-2">
                {(["ALL", "FOREX", "COMMODITIES", "CRYPTO"] as const).map((cls) => {
                  const isSel = selectedClass === cls;
                  return (
                    <button
                      key={cls}
                      type="button"
                      onClick={() => setSelectedClass(cls)}
                      className={`text-[10px] px-2 py-0.5 rounded font-mono font-medium transition ${
                        isSel
                          ? "bg-cyan-500 text-slate-950 font-bold"
                          : "bg-slate-800/80 text-slate-400 hover:text-slate-200 hover:bg-slate-700"
                      }`}
                    >
                      {cls === "ALL" ? "All (14)" : cls === "COMMODITIES" ? "Metals/Oil" : cls}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Symbols List */}
            <div className="flex-1 overflow-y-auto divide-y divide-slate-800/60 p-1">
              {filteredInstruments.map((inst) => {
                const isSelected = inst.symbol === selectedSymbol;
                const instColor = getAssetClassColor(inst.assetClass);
                const q = quotes[inst.symbol] || quotes[inst.symbol.replace("#", "")];
                const isOpenNow = isMarketOpen(inst.symbol);
                const sessionTag = getSymbolSession(inst.symbol);

                return (
                  <button
                    key={inst.symbol}
                    type="button"
                    onClick={() => {
                      onSelectSymbol(inst.symbol);
                      setIsOpen(false);
                    }}
                    className={`w-full px-2.5 py-2 text-left rounded-lg transition flex items-center justify-between group ${
                      isSelected
                        ? "bg-cyan-950/40 border border-cyan-500/40"
                        : "hover:bg-slate-800/50 border border-transparent"
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          isOpenNow ? "bg-emerald-400" : "bg-slate-600"
                        }`}
                      />
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-slate-100 text-xs font-mono group-hover:text-cyan-300">
                            {inst.symbol}
                          </span>
                          <span
                            className={`text-[9px] px-1 py-0.2 rounded font-mono ${instColor.badge}`}
                          >
                            {inst.assetClass.slice(0, 3)}
                          </span>
                          {inst.is24_7 && (
                            <span className="text-[8px] bg-purple-950 text-purple-300 border border-purple-800 px-1 rounded font-mono">
                              24/7
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-slate-400">
                          {inst.displaySymbol} · {inst.name}
                        </div>
                      </div>
                    </div>

                    <div className="text-right">
                      {q && q.bid > 0 ? (
                        <div className="text-[11px] font-mono tabular-nums text-slate-200">
                          <span className="text-emerald-400">{q.bid.toFixed(inst.digits)}</span>
                          {q.spread_points !== undefined && (
                            <div className="text-[9px] text-amber-400">{q.spread_points} pt</div>
                          )}
                        </div>
                      ) : (
                        <div className="text-[9px] text-slate-500 font-mono">{sessionTag}</div>
                      )}
                      {isSelected && <Check className="w-3.5 h-3.5 text-cyan-400 ml-auto mt-0.5" />}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
};

