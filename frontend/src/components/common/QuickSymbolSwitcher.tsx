import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  Search,
  Command,
  ArrowRight,
  Zap,
  Check,
  LayoutDashboard,
  BrainCircuit,
  BookOpenCheck,
  BarChart3,
  Sliders,
} from "lucide-react";
import {
  INSTRUMENTS,
  InstrumentInfo,
  getAssetClassColor,
  isMarketOpen,
  getSymbolSession,
} from "../../constants/instruments";
import { NavWorkspace } from "./LeftNavRail";

interface QuickSymbolSwitcherProps {
  isOpen: boolean;
  onClose: () => void;
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
  onSelectWorkspace?: (workspace: NavWorkspace) => void;
  quotes?: Record<string, { bid: number; ask: number; spread_points?: number }>;
}

export const QuickSymbolSwitcher: React.FC<QuickSymbolSwitcherProps> = ({
  isOpen,
  onClose,
  selectedSymbol,
  onSelectSymbol,
  onSelectWorkspace,
  quotes = {},
}) => {
  const [search, setSearch] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const workspaces: { id: NavWorkspace; label: string; icon: any; category: "WORKSPACE" }[] = [
    { id: "COCKPIT", label: "Terminal Cockpit (Live Chart & Orders)", icon: LayoutDashboard, category: "WORKSPACE" },
    { id: "AI_SUPERVISOR", label: "AI Brain & Rules (Radar & Rules Vault)", icon: BrainCircuit, category: "WORKSPACE" },
    { id: "TRADE_BOOK", label: "Trade Book & Forensics (Ledger & Reports)", icon: BookOpenCheck, category: "WORKSPACE" },
    { id: "PERFORMANCE", label: "Performance Analytics (Heatmap & KPIs)", icon: BarChart3, category: "WORKSPACE" },
    { id: "RISK_SETTINGS", label: "Risk & Pair Settings (14-Pair Matrix)", icon: Sliders, category: "WORKSPACE" },
  ];

  useEffect(() => {
    if (isOpen) {
      setSearch("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const wsMatches = workspaces.filter(
      (ws) => !q || ws.label.toLowerCase().includes(q) || ws.id.toLowerCase().includes(q)
    );

    const pairMatches = INSTRUMENTS.filter(
      (inst) =>
        !q ||
        inst.symbol.toLowerCase().includes(q) ||
        inst.name.toLowerCase().includes(q) ||
        inst.displaySymbol.toLowerCase().includes(q) ||
        inst.assetClass.toLowerCase().includes(q)
    ).map((inst) => ({ ...inst, category: "PAIR" as const }));

    return [...wsMatches, ...pairMatches];
  }, [search]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [search]);

  const handleSelectItem = (item: any) => {
    if (item.category === "WORKSPACE" && onSelectWorkspace) {
      onSelectWorkspace(item.id);
    } else if (item.symbol) {
      onSelectSymbol(item.symbol);
    }
    onClose();
  };

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
        handleSelectItem(filtered[selectedIndex]);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/80 backdrop-blur-sm transition-opacity" onClick={onClose} />

      {/* Modal Card */}
      <div
        className="relative w-full max-w-xl bg-[#0a0f18] border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col z-10 font-sans"
        onKeyDown={handleKeyDown}
      >
        {/* Search Header */}
        <div className="p-3.5 border-b border-slate-800 bg-[#070b12] flex items-center gap-3">
          <Command className="w-4 h-4 text-cyan-400" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Type a pair (GOLD, BTC) or workspace (Cockpit, AI Brain, Risk)..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-500 focus:outline-none font-mono"
          />
          <div className="flex items-center gap-1 text-[10px] text-slate-400 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded font-mono">
            <span>ESC to close</span>
          </div>
        </div>

        {/* Results List */}
        <div className="max-h-[380px] overflow-y-auto divide-y divide-slate-800/60 p-2">
          {filtered.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-500 font-mono">
              No matching pairs or workspaces found for "{search}".
            </div>
          ) : (
            filtered.map((item: any, idx: number) => {
              const isSelected = idx === selectedIndex;
              const isWs = item.category === "WORKSPACE";

              if (isWs) {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    onClick={() => handleSelectItem(item)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={`w-full px-3 py-2.5 rounded-xl text-left flex items-center justify-between transition ${
                      isSelected
                        ? "bg-cyan-500/15 border border-cyan-500/40 text-cyan-300"
                        : "hover:bg-slate-800/40 border border-transparent text-slate-300"
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <div className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 text-cyan-400">
                        <Icon className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="font-bold text-xs font-mono">{item.label}</div>
                        <div className="text-[10px] text-slate-500 font-sans">Jump to platform workspace</div>
                      </div>
                    </div>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 font-mono border border-slate-800">
                      PAGE
                    </span>
                  </button>
                );
              }

              // Pair Item
              const color = getAssetClassColor(item.assetClass);
              const q = quotes[item.symbol] || quotes[item.symbol.replace("#", "")];
              const openState = isMarketOpen(item.symbol);
              const isCurrent = selectedSymbol === item.symbol;

              return (
                <button
                  key={item.symbol}
                  onClick={() => handleSelectItem(item)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`w-full px-3 py-2.5 rounded-xl text-left flex items-center justify-between transition ${
                    isSelected
                      ? "bg-cyan-500/15 border border-cyan-500/40 text-cyan-300"
                      : "hover:bg-slate-800/40 border border-transparent text-slate-300"
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        openState ? "bg-emerald-400" : "bg-slate-600"
                      }`}
                    />
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-xs font-mono text-white">{item.symbol}</span>
                        <span className={`text-[9px] px-1.5 py-0.2 rounded font-bold font-mono ${color.badge}`}>
                          {item.assetClass}
                        </span>
                        {item.is24_7 && (
                          <span className="text-[9px] px-1 rounded bg-purple-950 text-purple-300 border border-purple-800 font-mono">
                            24/7
                          </span>
                        )}
                        {isCurrent && (
                          <span className="text-[9px] px-1 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-mono">
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div className="text-[10px] text-slate-400 font-sans truncate max-w-[200px]">
                        {item.name}
                      </div>
                    </div>
                  </div>

                  {q && q.bid > 0 ? (
                    <div className="text-right text-xs font-mono tabular-nums">
                      <div className="text-emerald-400 font-bold">{q.bid.toFixed(item.digits)}</div>
                      <div className="text-[10px] text-slate-500">{q.spread_points ?? item.defaultSpread} pts</div>
                    </div>
                  ) : (
                    <ArrowRight className="w-4 h-4 text-slate-600" />
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* Footer Shortcut Helper */}
        <div className="p-2.5 border-t border-slate-800/80 bg-[#070b12] text-[10px] font-mono text-slate-500 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span>↑↓ Navigate</span>
            <span>↵ Select</span>
            <span>ESC Dismiss</span>
          </div>
          <span className="text-cyan-400">14 Pairs · 5 Workspaces</span>
        </div>
      </div>
    </div>
  );
};
