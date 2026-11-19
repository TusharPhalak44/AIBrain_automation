import React from "react";
import { getInstrument, getAssetClassColor, isMarketOpen } from "../../constants/instruments";

interface InstrumentBadgeProps {
  symbol: string;
  spreadPoints?: number;
  showSession?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export const InstrumentBadge: React.FC<InstrumentBadgeProps> = ({
  symbol,
  spreadPoints,
  size = "md",
  className = "",
}) => {
  const inst = getInstrument(symbol);
  const color = getAssetClassColor(inst.assetClass);
  const open = isMarketOpen(symbol);

  const sizeClasses = {
    sm: "text-[10px] py-0.5 px-2 gap-1.5",
    md: "text-xs py-1 px-2.5 gap-2",
    lg: "text-sm py-1.5 px-3 gap-2.5",
  }[size];

  return (
    <div
      className={`inline-flex items-center rounded-lg border font-mono font-medium transition ${color.badge} ${sizeClasses} ${className}`}
      title={`${inst.name} (${inst.assetClass}) — XM MT5 Ultra Low / CFD`}
    >
      {/* Market Status Dot */}
      <span
        className={`w-1.5 h-1.5 rounded-full ${
          open ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]" : "bg-slate-500"
        }`}
      />

      {/* Symbol Name & Class */}
      <div className="flex items-center gap-1.5">
        <span className="font-bold text-slate-100 tracking-wide">{inst.symbol}</span>
        <span className="text-[9px] uppercase px-1 py-0.2 rounded bg-slate-900/80 text-slate-400 border border-slate-700/50">
          {inst.assetClass.slice(0, 3)}
        </span>
      </div>

      {/* Optional Spread Points */}
      {spreadPoints !== undefined && (
        <span className="text-[10px] tabular-nums font-mono text-amber-400 bg-slate-950/80 px-1 rounded border border-amber-500/20">
          {spreadPoints} pt
        </span>
      )}
    </div>
  );
};
