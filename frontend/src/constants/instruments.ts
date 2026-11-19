/**
 * Centralized Single Source of Truth (SSOT) 14-Pair Instrument Registry & Formatting Helpers.
 *
 * Supported 14 High-Liquidity XM Ultra Low / Cash CFD Instruments:
 * - FOREX (6): EURUSD# (5 digits), USDJPY# (3 digits), GBPUSD# (5 digits), USDCAD# (5 digits), AUDUSD# (5 digits), GBPJPY# (3 digits)
 * - COMMODITIES (4): GOLD# (2 digits), SILVER# (3 digits), OILCash# (2 digits), BRENTCash# (2 digits)
 * - CRYPTO 24/7 (4): BTCUSD# (2 digits), ETHUSD# (2 digits), SOLUSD# (2 digits), XRPUSD# (4 digits)
 */

export type AssetClass = "FOREX" | "COMMODITIES" | "CRYPTO";

export interface InstrumentInfo {
  symbol: string;
  name: string;
  displaySymbol: string;
  baseCurrency: string;
  quoteCurrency: string;
  assetClass: AssetClass;
  digits: number;
  contractSize: number;
  tickSize: number;
  tickValue: number;
  defaultSpread: number;
  maxSpread: number;
  defaultSlippage: number;
  is24_7: boolean;
  activeSessions: string[];
  aliases: string[];
}

export const INSTRUMENTS: InstrumentInfo[] = [
  // =========================================================================
  // FOREX (6)
  // =========================================================================
  {
    symbol: "EURUSD#",
    name: "Euro / US Dollar",
    displaySymbol: "EUR/USD",
    baseCurrency: "EUR",
    quoteCurrency: "USD",
    assetClass: "FOREX",
    digits: 5,
    contractSize: 100000,
    tickSize: 0.00001,
    tickValue: 1.0,
    defaultSpread: 12,
    maxSpread: 18,
    defaultSlippage: 2,
    is24_7: false,
    activeSessions: ["London", "New York"],
    aliases: ["EURUSD", "EURUSD.raw", "EURUSDm", "EURUSD#"],
  },
  {
    symbol: "USDJPY#",
    name: "US Dollar / Japanese Yen",
    displaySymbol: "USD/JPY",
    baseCurrency: "USD",
    quoteCurrency: "JPY",
    assetClass: "FOREX",
    digits: 3,
    contractSize: 100000,
    tickSize: 0.001,
    tickValue: 0.67,
    defaultSpread: 14,
    maxSpread: 20,
    defaultSlippage: 2,
    is24_7: false,
    activeSessions: ["Tokyo", "New York"],
    aliases: ["USDJPY", "USDJPY.raw", "USDJPYm", "USDJPY#"],
  },
  {
    symbol: "GBPUSD#",
    name: "British Pound / US Dollar",
    displaySymbol: "GBP/USD",
    baseCurrency: "GBP",
    quoteCurrency: "USD",
    assetClass: "FOREX",
    digits: 5,
    contractSize: 100000,
    tickSize: 0.00001,
    tickValue: 1.0,
    defaultSpread: 15,
    maxSpread: 25,
    defaultSlippage: 2,
    is24_7: false,
    activeSessions: ["London", "New York"],
    aliases: ["GBPUSD", "GBPUSD.raw", "GBPUSDm", "GBPUSD#"],
  },
  {
    symbol: "USDCAD#",
    name: "US Dollar / Canadian Dollar",
    displaySymbol: "USD/CAD",
    baseCurrency: "USD",
    quoteCurrency: "CAD",
    assetClass: "FOREX",
    digits: 5,
    contractSize: 100000,
    tickSize: 0.00001,
    tickValue: 0.74,
    defaultSpread: 16,
    maxSpread: 22,
    defaultSlippage: 2,
    is24_7: false,
    activeSessions: ["New York"],
    aliases: ["USDCAD", "USDCAD.raw", "USDCADm", "USDCAD#"],
  },
  {
    symbol: "AUDUSD#",
    name: "Australian Dollar / US Dollar",
    displaySymbol: "AUD/USD",
    baseCurrency: "AUD",
    quoteCurrency: "USD",
    assetClass: "FOREX",
    digits: 5,
    contractSize: 100000,
    tickSize: 0.00001,
    tickValue: 1.0,
    defaultSpread: 14,
    maxSpread: 20,
    defaultSlippage: 2,
    is24_7: false,
    activeSessions: ["Sydney", "Tokyo", "London"],
    aliases: ["AUDUSD", "AUDUSD.raw", "AUDUSDm", "AUDUSD#"],
  },
  {
    symbol: "GBPJPY#",
    name: "British Pound / Japanese Yen",
    displaySymbol: "GBP/JPY",
    baseCurrency: "GBP",
    quoteCurrency: "JPY",
    assetClass: "FOREX",
    digits: 3,
    contractSize: 100000,
    tickSize: 0.001,
    tickValue: 0.67,
    defaultSpread: 22,
    maxSpread: 35,
    defaultSlippage: 2,
    is24_7: false,
    activeSessions: ["London", "Tokyo"],
    aliases: ["GBPJPY", "GBPJPY.raw", "GBPJPYm", "GBPJPY#"],
  },

  // =========================================================================
  // COMMODITIES (4)
  // =========================================================================
  {
    symbol: "GOLD#",
    name: "Spot Gold (100 oz)",
    displaySymbol: "XAU/USD",
    baseCurrency: "XAU",
    quoteCurrency: "USD",
    assetClass: "COMMODITIES",
    digits: 2,
    contractSize: 100,
    tickSize: 0.01,
    tickValue: 1.0,
    defaultSpread: 25,
    maxSpread: 80,
    defaultSlippage: 2,
    is24_7: false,
    activeSessions: ["London", "New York"],
    aliases: ["GOLD", "GOLD#", "XAUUSD", "XAUUSD#", "GOLDm"],
  },
  {
    symbol: "SILVER#",
    name: "Spot Silver (5000 oz)",
    displaySymbol: "XAG/USD",
    baseCurrency: "XAG",
    quoteCurrency: "USD",
    assetClass: "COMMODITIES",
    digits: 3,
    contractSize: 5000,
    tickSize: 0.001,
    tickValue: 5.0,
    defaultSpread: 28,
    maxSpread: 45,
    defaultSlippage: 2,
    is24_7: false,
    activeSessions: ["London", "New York"],
    aliases: ["SILVER", "SILVER#", "XAGUSD", "XAGUSD#", "SILVERm"],
  },
  {
    symbol: "OILCash#",
    name: "WTI Crude Oil Cash",
    displaySymbol: "WTI OIL",
    baseCurrency: "OIL",
    quoteCurrency: "USD",
    assetClass: "COMMODITIES",
    digits: 2,
    contractSize: 100,
    tickSize: 0.01,
    tickValue: 1.0,
    defaultSpread: 35,
    maxSpread: 60,
    defaultSlippage: 3,
    is24_7: false,
    activeSessions: ["London", "New York"],
    aliases: ["OILCash", "OILCash#", "USOIL#", "USOIL", "OIL#", "OIL", "USOILCash"],
  },
  {
    symbol: "BRENTCash#",
    name: "Brent Crude Oil Cash",
    displaySymbol: "BRENT OIL",
    baseCurrency: "BRENT",
    quoteCurrency: "USD",
    assetClass: "COMMODITIES",
    digits: 2,
    contractSize: 100,
    tickSize: 0.01,
    tickValue: 1.0,
    defaultSpread: 35,
    maxSpread: 60,
    defaultSlippage: 3,
    is24_7: false,
    activeSessions: ["London", "New York"],
    aliases: ["BRENTCash", "BRENTCash#", "UKOIL#", "UKOIL", "BRENT#", "BRENT", "UKOILCash"],
  },

  // =========================================================================
  // CRYPTO 24/7 (4)
  // =========================================================================
  {
    symbol: "BTCUSD#",
    name: "Bitcoin CFD (24/7)",
    displaySymbol: "BTC/USD",
    baseCurrency: "BTC",
    quoteCurrency: "USD",
    assetClass: "CRYPTO",
    digits: 2,
    contractSize: 1,
    tickSize: 0.01,
    tickValue: 0.01,
    defaultSpread: 2500,
    maxSpread: 6000,
    defaultSlippage: 15,
    is24_7: true,
    activeSessions: ["24/7 Continuous"],
    aliases: ["BTCUSD", "BTCUSD#", "BTC#", "BTCUSDm"],
  },
  {
    symbol: "ETHUSD#",
    name: "Ethereum CFD (24/7)",
    displaySymbol: "ETH/USD",
    baseCurrency: "ETH",
    quoteCurrency: "USD",
    assetClass: "CRYPTO",
    digits: 2,
    contractSize: 1,
    tickSize: 0.01,
    tickValue: 0.01,
    defaultSpread: 350,
    maxSpread: 800,
    defaultSlippage: 15,
    is24_7: true,
    activeSessions: ["24/7 Continuous"],
    aliases: ["ETHUSD", "ETHUSD#", "ETH#", "ETHUSDm"],
  },
  {
    symbol: "SOLUSD#",
    name: "Solana CFD (24/7)",
    displaySymbol: "SOL/USD",
    baseCurrency: "SOL",
    quoteCurrency: "USD",
    assetClass: "CRYPTO",
    digits: 2,
    contractSize: 1,
    tickSize: 0.01,
    tickValue: 0.01,
    defaultSpread: 60,
    maxSpread: 120,
    defaultSlippage: 15,
    is24_7: true,
    activeSessions: ["24/7 Continuous"],
    aliases: ["SOLUSD", "SOLUSD#", "SOL#", "SOLUSDm"],
  },
  {
    symbol: "XRPUSD#",
    name: "Ripple CFD (24/7)",
    displaySymbol: "XRP/USD",
    baseCurrency: "XRP",
    quoteCurrency: "USD",
    assetClass: "CRYPTO",
    digits: 4,
    contractSize: 1000,
    tickSize: 0.0001,
    tickValue: 0.10,
    defaultSpread: 80,
    maxSpread: 150,
    defaultSlippage: 10,
    is24_7: true,
    activeSessions: ["24/7 Continuous"],
    aliases: ["XRPUSD", "XRPUSD#", "XRP#", "XRPUSDm"],
  },
];

export const INSTRUMENT_MAP: Record<string, InstrumentInfo> = INSTRUMENTS.reduce(
  (acc, inst) => {
    acc[inst.symbol] = inst;
    acc[inst.symbol.replace("#", "")] = inst;
    inst.aliases.forEach((alias) => {
      acc[alias] = inst;
    });
    return acc;
  },
  {} as Record<string, InstrumentInfo>
);

/**
 * Get InstrumentInfo safely with symbol aliases.
 */
export function getInstrument(symbol: string): InstrumentInfo {
  if (!symbol) return INSTRUMENTS[6]; // Default GOLD#
  const clean = symbol.trim().toUpperCase();
  return (
    INSTRUMENT_MAP[clean] ||
    INSTRUMENT_MAP[`${clean}#`] ||
    INSTRUMENT_MAP[clean.replace("#", "")] ||
    INSTRUMENTS[6]
  );
}

/**
 * Get decimal precision (digits) for a given symbol.
 */
export function getSymbolDigits(symbol: string): number {
  return getInstrument(symbol).digits;
}

/**
 * Format any numeric price using the exact decimal precision required for the symbol.
 * E.g., EURUSD# -> 1.08452, USDJPY# -> 154.320, GOLD# -> 2650.50, XRPUSD# -> 0.6145
 */
export function formatSymbolPrice(symbol: string, price: unknown): string {
  if (price === null || price === undefined || price === "") return "-";
  const num = typeof price === "number" ? price : parseFloat(String(price));
  if (!Number.isFinite(num)) return "-";
  const digits = getSymbolDigits(symbol);
  return num.toFixed(digits);
}

/**
 * Check if market is currently open for the given symbol.
 */
export function isMarketOpen(symbol: string, date: Date = new Date()): boolean {
  const inst = getInstrument(symbol);
  if (inst.is24_7) return true;

  const day = date.getUTCDay(); // 0 is Sunday, 5 is Friday, 6 is Saturday
  const hour = date.getUTCHours();

  // Friday after 22:00 UTC closed
  if (day === 5 && hour >= 22) return false;
  // Saturday all day closed
  if (day === 6) return false;
  // Sunday before 22:00 UTC closed
  if (day === 0 && hour < 22) return false;

  return true;
}

/**
 * Get current active trading session tag for symbol.
 */
export function getSymbolSession(symbol: string, date: Date = new Date()): string {
  const inst = getInstrument(symbol);
  if (inst.is24_7) return "24/7 Continuous";
  if (!isMarketOpen(symbol, date)) return "Weekend Closed";

  const hour = date.getUTCHours();
  const min = date.getUTCMinutes();
  const totalMin = hour * 60 + min;

  if (totalMin >= 0 && totalMin < 420) return "Asian (Tokyo)";
  if (totalMin >= 420 && totalMin < 720) return "London Open";
  if (totalMin >= 720 && totalMin < 990) return "London/NY Overlap";
  if (totalMin >= 990 && totalMin < 1260) return "New York Afternoon";
  return "Pacific Rollover";
}

/**
 * Visual color tokens for asset classes.
 */
export function getAssetClassColor(assetClass: AssetClass | string): {
  badge: string;
  text: string;
  border: string;
  bg: string;
  glow: string;
} {
  const norm = String(assetClass).toUpperCase();
  switch (norm) {
    case "FOREX":
      return {
        badge: "bg-sky-500/15 text-sky-400 border-sky-500/30",
        text: "text-sky-400",
        border: "border-sky-500/30",
        bg: "bg-sky-500/10",
        glow: "shadow-[0_0_12px_rgba(56,189,248,0.2)]",
      };
    case "COMMODITIES":
      return {
        badge: "bg-amber-500/15 text-amber-400 border-amber-500/30",
        text: "text-amber-400",
        border: "border-amber-500/30",
        bg: "bg-amber-500/10",
        glow: "shadow-[0_0_12px_rgba(245,158,11,0.2)]",
      };
    case "CRYPTO":
      return {
        badge: "bg-purple-500/15 text-purple-400 border-purple-500/30",
        text: "text-purple-400",
        border: "border-purple-500/30",
        bg: "bg-purple-500/10",
        glow: "shadow-[0_0_12px_rgba(168,85,247,0.2)]",
      };
    default:
      return {
        badge: "bg-slate-700/20 text-slate-300 border-slate-700/40",
        text: "text-slate-300",
        border: "border-slate-700/40",
        bg: "bg-slate-800/10",
        glow: "",
      };
  }
}
