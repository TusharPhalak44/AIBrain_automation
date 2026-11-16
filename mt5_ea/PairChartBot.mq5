//+------------------------------------------------------------------+
//|                                                PairChartBot.mq5  |
//|                             XM Global V2 Trading Portal Architect|
//|                        Deterministic Dual-Mode Chart-Bound Robot |
//+------------------------------------------------------------------+
#property copyright "XM Global V2 Trading Portal"
#property link      "https://github.com/xm-trading-v2"
#property version   "2.00"
#property description "Dual-Mode (Scalp 1001 & Swing 2001) Per-Chart Execution & Protection Engine"

#include <Trade\Trade.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\PositionInfo.mqh>

//--- Input Parameters
input group "=== Strategy Identification ==="
input ulong    InpMagicScalp         = 1001;    // Scalp Magic Number
input ulong    InpMagicSwing         = 2001;    // Swing Magic Number

input group "=== Risk & Target Management ==="
input double   InpPartialCloseR      = 1.5;     // Partial Profit Target (in R-Multiples)
input double   InpScalpTrailATRMult  = 1.2;     // Scalp ATR Trailing Multiplier (M5)
input double   InpSwingTrailATRMult  = 1.8;     // Swing ATR Trailing Multiplier (H1)
input double   InpDailyDDLimitPct    = 2.5;     // Hard Daily Drawdown Limit (%)
input bool     InpEnableHeartbeat    = true;    // Write JSON Heartbeat to MQL5/Files

//--- Global Objects
CTrade         g_trade;
CSymbolInfo    g_sym;
CPositionInfo  g_pos;

int            g_hAtrM5              = INVALID_HANDLE;
int            g_hAtrH1              = INVALID_HANDLE;
datetime       g_lastMidnight        = 0;
double         g_dailyBaselineEquity = 0.0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   if(!g_sym.Name(_Symbol))
   {
      PrintFormat("[CRITICAL] Failed to initialize symbol info for %s", _Symbol);
      return INIT_FAILED;
   }
   g_sym.Refresh();

   // Initialize ATR handles
   g_hAtrM5 = iATR(_Symbol, PERIOD_M5, 14);
   g_hAtrH1 = iATR(_Symbol, PERIOD_H1, 14);

   if(g_hAtrM5 == INVALID_HANDLE || g_hAtrH1 == INVALID_HANDLE)
   {
      PrintFormat("[WARNING] Could not allocate ATR indicators for %s", _Symbol);
   }

   // Set timer for 5s heartbeat and daily baseline check
   EventSetTimer(5);

   UpdateDailyBaseline();
   WriteChartHeartbeat();

   PrintFormat("[INIT] PairChartBot attached to %s | Scalp Magic: %d | Swing Magic: %d",
               _Symbol, InpMagicScalp, InpMagicSwing);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   if(g_hAtrM5 != INVALID_HANDLE) IndicatorRelease(g_hAtrM5);
   if(g_hAtrH1 != INVALID_HANDLE) IndicatorRelease(g_hAtrH1);
   PrintFormat("[DEINIT] PairChartBot removed from %s (Reason: %d)", _Symbol, reason);
}

//+------------------------------------------------------------------+
//| Expert timer function (every 5 seconds)                          |
//+------------------------------------------------------------------+
void OnTimer()
{
   UpdateDailyBaseline();
   if(InpEnableHeartbeat)
   {
      WriteChartHeartbeat();
   }
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!g_sym.RefreshRates()) return;

   // 1. Enforce Hard Daily Drawdown Breaker
   if(CheckDailyDrawdownBreaker())
   {
      return; // Locked out for the day
   }

   // 2. Scan open positions on _Symbol
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!g_pos.SelectByTicket(ticket)) continue;

      // Strict Chart Isolation: Match current _Symbol only
      if(g_pos.Symbol() != _Symbol) continue;

      ulong magic = g_pos.Magic();
      if(magic != InpMagicScalp && magic != InpMagicSwing) continue;

      // 3. Zero-Naked-Trade Enforcement
      EnforceZeroNakedTrade(ticket, magic);

      // 4. Volume-Tier Partial Close & Break-Even Engine
      ManageProfitTargetAndBreakEven(ticket, magic);

      // 5. Dynamic Trailing Stop Engine
      ManageTrailingStop(ticket, magic);
   }
}

//+------------------------------------------------------------------+
//| Enforce hard broker SL on naked positions                        |
//+------------------------------------------------------------------+
void EnforceZeroNakedTrade(ulong ticket, ulong magic)
{
   double currentSL = g_pos.StopLoss();
   if(currentSL > 0.0) return; // Already protected

   double openPrice = g_pos.PriceOpen();
   ENUM_POSITION_TYPE pType = g_pos.PositionType();
   double atr = GetATR(magic == InpMagicScalp ? PERIOD_M5 : PERIOD_H1);
   if(atr <= 0.0) atr = g_sym.Point() * 150.0; // Emergency default

   double emergencySL = 0.0;
   if(pType == POSITION_TYPE_BUY)
      emergencySL = NormalizeDouble(openPrice - (1.5 * atr), g_sym.Digits());
   else
      emergencySL = NormalizeDouble(openPrice + (1.5 * atr), g_sym.Digits());

   g_trade.SetExpertMagicNumber(magic);
   if(g_trade.PositionModify(ticket, emergencySL, g_pos.TakeProfit()))
   {
      PrintFormat("[SAFETY LOCK] Attached Emergency SL on naked position #%d at %s", ticket, DoubleToString(emergencySL, g_sym.Digits()));
   }
   else
   {
      PrintFormat("[EMERGENCY] Failed to attach SL on #%d! Closing immediately.", ticket);
      g_trade.PositionClose(ticket);
   }
}

//+------------------------------------------------------------------+
//| Volume-Tier Partial Close at +1.5R & Break-Even                  |
//+------------------------------------------------------------------+
void ManageProfitTargetAndBreakEven(ulong ticket, ulong magic)
{
   double openPrice = g_pos.PriceOpen();
   double sl = g_pos.StopLoss();
   if(sl <= 0.0) return;

   double initialRisk = MathAbs(openPrice - sl);
   if(initialRisk <= 0.0) return;

   ENUM_POSITION_TYPE pType = g_pos.PositionType();
   double currentPrice = (pType == POSITION_TYPE_BUY) ? g_sym.Bid() : g_sym.Ask();
   double gain = (pType == POSITION_TYPE_BUY) ? (currentPrice - openPrice) : (openPrice - currentPrice);

   // Check if target +1.5R reached
   if(gain >= InpPartialCloseR * initialRisk)
   {
      double volume = g_pos.Volume();
      double volStep = g_sym.LotsStep();
      double volMin = g_sym.LotsMin();
      string comment = g_pos.Comment();

      // Ensure BE Buffer (spread + small buffer)
      double spreadBuffer = g_sym.Spread() * g_sym.Point();
      double bePrice = (pType == POSITION_TYPE_BUY) ? (openPrice + spreadBuffer) : (openPrice - spreadBuffer);
      bePrice = NormalizeDouble(bePrice, g_sym.Digits());

      // If volume is too small to split (< 2 * step, e.g. 0.01 lot)
      if(volume < 2.0 * volStep)
      {
         // Skip partial close, directly secure Break-Even
         if(pType == POSITION_TYPE_BUY && sl < bePrice)
         {
            g_trade.SetExpertMagicNumber(magic);
            g_trade.PositionModify(ticket, bePrice, g_pos.TakeProfit());
            PrintFormat("[BE LOCK] Micro-lot #%d moved to BE (%s)", ticket, DoubleToString(bePrice, g_sym.Digits()));
         }
         else if(pType == POSITION_TYPE_SELL && (sl > bePrice || sl == 0.0))
         {
            g_trade.SetExpertMagicNumber(magic);
            g_trade.PositionModify(ticket, bePrice, g_pos.TakeProfit());
            PrintFormat("[BE LOCK] Micro-lot #%d moved to BE (%s)", ticket, DoubleToString(bePrice, g_sym.Digits()));
         }
      }
      else
      {
         // Split volume >= 2 * step
         // Check if already closed partial (identified via comment or volume)
         if(StringFind(comment, "[TP1]") < 0)
         {
            double halfLot = MathFloor((volume * 0.5) / volStep) * volStep;
            if(halfLot >= volMin)
            {
               g_trade.SetExpertMagicNumber(magic);
               if(g_trade.PositionClosePartial(ticket, halfLot))
               {
                  PrintFormat("[PARTIAL TP1] Closed %s lots on #%d at +1.5R", DoubleToString(halfLot, 2), ticket);
                  // Secure Break-Even on remaining runner
                  g_trade.PositionModify(ticket, bePrice, g_pos.TakeProfit());
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Dynamic ATR-Based Trailing Stop                                  |
//+------------------------------------------------------------------+
void ManageTrailingStop(ulong ticket, ulong magic)
{
   double openPrice = g_pos.PriceOpen();
   double currentSL = g_pos.StopLoss();
   ENUM_POSITION_TYPE pType = g_pos.PositionType();

   // Only trail if trade is in profit past entry
   if(pType == POSITION_TYPE_BUY && g_sym.Bid() <= openPrice) return;
   if(pType == POSITION_TYPE_SELL && g_sym.Ask() >= openPrice) return;

   ENUM_TIMEFRAMES tf = (magic == InpMagicScalp) ? PERIOD_M5 : PERIOD_H1;
   double mult = (magic == InpMagicScalp) ? InpScalpTrailATRMult : InpSwingTrailATRMult;
   double atr = GetATR(tf);
   if(atr <= 0.0) return;

   double trailDist = mult * atr;
   double newSL = 0.0;

   if(pType == POSITION_TYPE_BUY)
   {
      newSL = NormalizeDouble(g_sym.Bid() - trailDist, g_sym.Digits());
      if(newSL > currentSL && newSL > openPrice)
      {
         g_trade.SetExpertMagicNumber(magic);
         g_trade.PositionModify(ticket, newSL, g_pos.TakeProfit());
      }
   }
   else
   {
      newSL = NormalizeDouble(g_sym.Ask() + trailDist, g_sym.Digits());
      if((newSL < currentSL || currentSL == 0.0) && newSL < openPrice)
      {
         g_trade.SetExpertMagicNumber(magic);
         g_trade.PositionModify(ticket, newSL, g_pos.TakeProfit());
      }
   }
}

//+------------------------------------------------------------------+
//| Check and enforce 2.5% Daily Drawdown Lock                       |
//+------------------------------------------------------------------+
bool CheckDailyDrawdownBreaker()
{
   if(g_dailyBaselineEquity <= 0.0) return false;

   double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   double ddPct = ((g_dailyBaselineEquity - currentEquity) / g_dailyBaselineEquity) * 100.0;

   if(ddPct >= InpDailyDDLimitPct)
   {
      PrintFormat("[CIRCUIT BREAKER] Daily DD Limit Reached on %s: %.2f%% >= %.2f%%! Flattening intraday trades.",
                  _Symbol, ddPct, InpDailyDDLimitPct);

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0) continue;
         if(g_pos.SelectByTicket(ticket) && g_pos.Symbol() == _Symbol)
         {
            ulong m = g_pos.Magic();
            if(m == InpMagicScalp || m == InpMagicSwing)
            {
               g_trade.PositionClose(ticket);
            }
         }
      }
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Daily Baseline Update anchored at broker 00:00                   |
//+------------------------------------------------------------------+
void UpdateDailyBaseline()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   datetime todayMidnight = StructToTime(dt);

   if(todayMidnight != g_lastMidnight)
   {
      g_lastMidnight = todayMidnight;
      g_dailyBaselineEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      PrintFormat("[BASELINE] Updated Daily Equity Baseline for %s at broker 00:00: $%.2f",
                  _Symbol, g_dailyBaselineEquity);
   }
}

//+------------------------------------------------------------------+
//| Read ATR value for specified timeframe                           |
//+------------------------------------------------------------------+
double GetATR(ENUM_TIMEFRAMES tf)
{
   int handle = (tf == PERIOD_M5) ? g_hAtrM5 : g_hAtrH1;
   if(handle == INVALID_HANDLE) return 0.0;

   double buf[1];
   if(CopyBuffer(handle, 0, 1, 1, buf) <= 0) return 0.0;
   return buf[0];
}

//+------------------------------------------------------------------+
//| Write JSON Heartbeat to MQL5/Files                               |
//+------------------------------------------------------------------+
void WriteChartHeartbeat()
{
   string cleanSymbol = _Symbol;
   StringReplace(cleanSymbol, "#", "_hash");
   StringReplace(cleanSymbol, "/", "_");

   string filename = StringFormat("chartbot_%s.json", cleanSymbol);
   int hFile = FileOpen(filename, FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(hFile != INVALID_HANDLE)
   {
      string json = StringFormat(
         "{\"symbol\":\"%s\",\"account_login\":%I64d,\"algo_trading_allowed\":%s,\"spread_points\":%d,\"timestamp\":%I64d}",
         _Symbol,
         AccountInfoInteger(ACCOUNT_LOGIN),
         (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED)) ? "true" : "false",
         g_sym.Spread(),
         (long)TimeCurrent()
      );
      FileWriteString(hFile, json);
      FileClose(hFile);
   }
}
//+------------------------------------------------------------------+

