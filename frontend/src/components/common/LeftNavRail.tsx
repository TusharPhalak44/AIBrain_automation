import React from "react";
import {
  LayoutDashboard,
  BrainCircuit,
  BookOpenCheck,
  BarChart3,
  Sliders,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
  Radio,
  Database,
  Layers,
  Sparkles,
} from "lucide-react";

export type NavWorkspace =
  | "COCKPIT"
  | "AI_SUPERVISOR"
  | "TRADE_BOOK"
  | "PERFORMANCE"
  | "RISK_SETTINGS";

interface LeftNavRailProps {
  currentWorkspace: NavWorkspace;
  onSelectWorkspace: (ws: NavWorkspace) => void;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  liveRulesCount?: number;
  openPositionsCount?: number;
  isMt5Connected?: boolean;
  dbHealthy?: boolean;
  isWsConnected?: boolean;
}

export const LeftNavRail: React.FC<LeftNavRailProps> = ({
  currentWorkspace,
  onSelectWorkspace,
  isCollapsed,
  onToggleCollapse,
  liveRulesCount = 0,
  openPositionsCount = 0,
  isMt5Connected = false,
  dbHealthy = true,
  isWsConnected = false,
}) => {
  const navItems = [
    {
      id: "COCKPIT" as NavWorkspace,
      label: "Terminal Cockpit",
      shortLabel: "Cockpit",
      icon: LayoutDashboard,
      description: "Live Chart, 14 Pairs & Order Ticket",
      badge: openPositionsCount > 0 ? `${openPositionsCount}` : undefined,
      badgeColor: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
    },
    {
      id: "AI_SUPERVISOR" as NavWorkspace,
      label: "AI Brain & Rules",
      shortLabel: "AI Brain",
      icon: BrainCircuit,
      description: "Radar, Rules Vault & Prompts",
      badge: liveRulesCount > 0 ? `${liveRulesCount} LIVE` : undefined,
      badgeColor: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
    },
    {
      id: "TRADE_BOOK" as NavWorkspace,
      label: "Trade Book & Forensics",
      shortLabel: "Trades",
      icon: BookOpenCheck,
      description: "Ledger & Exit Reason Forensics",
    },
    {
      id: "PERFORMANCE" as NavWorkspace,
      label: "Performance Analytics",
      shortLabel: "Analytics",
      icon: BarChart3,
      description: "Heatmap, Expectancy & Token Costs",
    },
    {
      id: "RISK_SETTINGS" as NavWorkspace,
      label: "Risk & Pair Settings",
      shortLabel: "Risk & Settings",
      icon: Sliders,
      description: "14 Pairs Matrix & Guardrails",
    },
  ];

  return (
    <aside
      className={`transition-all duration-200 ease-in-out border-r border-slate-800/80 bg-[#0a0f19] flex flex-col justify-between shrink-0 select-none z-30 ${
        isCollapsed ? "w-16" : "w-56"
      }`}
    >
      {/* Top: Section Header & Workspace Navigation Items */}
      <div className="flex flex-col py-2.5">
        {/* Workspace Group Label */}
        <div className="px-3.5 mb-2 flex items-center justify-between">
          {!isCollapsed ? (
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500 font-semibold">
              Workspaces
            </span>
          ) : (
            <div className="w-full flex justify-center">
              <span className="w-4 h-0.5 bg-slate-800 rounded-full" />
            </div>
          )}
        </div>

        {/* Navigation Buttons List */}
        <nav className="space-y-1 px-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentWorkspace === item.id;

            return (
              <button
                key={item.id}
                onClick={() => onSelectWorkspace(item.id)}
                title={isCollapsed ? `${item.label} — ${item.description}` : undefined}
                className={`w-full flex items-center rounded-xl transition-all group relative text-left ${
                  isCollapsed ? "justify-center p-2.5" : "px-3 py-2.5 gap-3"
                } ${
                  isActive
                    ? "bg-cyan-500/15 text-cyan-300 font-bold border border-cyan-500/30 shadow-[0_0_14px_rgba(6,182,212,0.15)]"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/40 border border-transparent"
                }`}
              >
                {/* Active Indicator Accent Strip */}
                {isActive && (
                  <span className="absolute left-0 top-2 bottom-2 w-1 bg-cyan-400 rounded-r shadow-[0_0_8px_rgba(6,182,212,0.8)]" />
                )}

                {/* Main Icon */}
                <Icon
                  className={`shrink-0 transition-transform ${
                    isCollapsed ? "w-5 h-5" : "w-4 h-4"
                  } ${
                    isActive
                      ? "text-cyan-400 scale-105"
                      : "text-slate-400 group-hover:text-slate-200"
                  }`}
                />

                {/* Text Labels & Badges (Expanded Mode Only) */}
                {!isCollapsed && (
                  <div className="flex-1 min-w-0 flex items-center justify-between">
                    <div className="truncate">
                      <div className="text-xs tracking-tight truncate leading-tight font-mono">
                        {item.label}
                      </div>
                      <div className="text-[9px] text-slate-500 truncate leading-tight font-sans mt-0.5">
                        {item.description}
                      </div>
                    </div>

                    {item.badge && (
                      <span
                        className={`text-[9px] font-mono px-1.5 py-0.5 rounded-md border font-bold shrink-0 ml-1.5 ${item.badgeColor}`}
                      >
                        {item.badge}
                      </span>
                    )}
                  </div>
                )}

                {/* Floating Tooltip in Collapsed Mode */}
                {isCollapsed && (
                  <div className="absolute left-full ml-2 px-2.5 py-1.5 bg-[#0f1623] border border-slate-700 rounded-lg text-xs font-mono text-white opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap shadow-xl z-50">
                    <div className="font-bold text-cyan-300">{item.label}</div>
                    <div className="text-[10px] text-slate-400 font-sans">{item.description}</div>
                    {item.badge && (
                      <div className="mt-1 text-[9px] text-emerald-400 font-mono font-bold">
                        {item.badge}
                      </div>
                    )}
                  </div>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom: Telemetry Signals, App Version & Collapse Toggle */}
      <div className="p-2 border-t border-slate-800/80 bg-[#070b13]/60 space-y-2">
        {/* Connection Pulse Strip */}
        {!isCollapsed ? (
          <div className="p-2 rounded-lg bg-[#0b101b] border border-slate-800/80 text-[10px] font-mono text-slate-400 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isMt5Connected ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
                  }`}
                />
                <span className="text-slate-300">MT5 Bridge</span>
              </span>
              <span className={isMt5Connected ? "text-emerald-400 font-bold" : "text-rose-400"}>
                {isMt5Connected ? "LIVE" : "OFFLINE"}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    dbHealthy ? "bg-emerald-400" : "bg-rose-500"
                  }`}
                />
                <span className="text-slate-300">MySQL V2</span>
              </span>
              <span className="text-slate-400">10.4.32</span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isWsConnected ? "bg-cyan-400 animate-ping" : "bg-amber-500"
                  }`}
                />
                <span className="text-slate-300">1s Telemetry</span>
              </span>
              <span className={isWsConnected ? "text-cyan-400" : "text-amber-400"}>
                {isWsConnected ? "ACTIVE" : "STANDBY"}
              </span>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1.5 py-1">
            <span
              title={`MT5 Bridge: ${isMt5Connected ? "Connected" : "Offline"}`}
              className={`w-2 h-2 rounded-full ${
                isMt5Connected ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
              }`}
            />
            <span
              title={`MySQL: ${dbHealthy ? "Healthy" : "Error"}`}
              className={`w-2 h-2 rounded-full ${dbHealthy ? "bg-emerald-400" : "bg-rose-500"}`}
            />
            <span
              title={`WebSocket: ${isWsConnected ? "Connected" : "Disconnected"}`}
              className={`w-2 h-2 rounded-full ${
                isWsConnected ? "bg-cyan-400 animate-ping" : "bg-amber-500"
              }`}
            />
          </div>
        )}

        {/* Collapse / Expand Toggle Button */}
        <button
          onClick={onToggleCollapse}
          className="w-full flex items-center justify-center gap-2 p-2 rounded-lg bg-slate-900/80 hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800 text-[11px] font-mono transition"
          title={isCollapsed ? "Expand Navigation Rail (w-56)" : "Collapse Navigation Rail (w-16)"}
        >
          {isCollapsed ? (
            <ChevronRight className="w-4 h-4 text-cyan-400" />
          ) : (
            <>
              <ChevronLeft className="w-4 h-4 text-cyan-400" />
              <span>Collapse Sidebar</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
};

