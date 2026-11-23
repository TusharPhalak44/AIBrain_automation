import React, { useState, useEffect } from "react";
import {
  X,
  Key,
  Database,
  Radio,
  Sliders,
  Send,
  Eye,
  EyeOff,
  CheckCircle2,
  FolderSearch,
  RefreshCw,
  Activity,
  Zap,
  Download,
  Upload,
  Server,
  HardDrive,
} from "lucide-react";
import { api } from "../../services/api";
import { useToast } from "../Toast";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  isMt5Connected: boolean;
  dbHealthy: boolean;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  isMt5Connected,
  dbHealthy,
}) => {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState<"ACCOUNTS" | "AI" | "RISK" | "TELEGRAM" | "DIAG" | "DATABASE">("ACCOUNTS");

  // Account Form
  const [accountType, setAccountType] = useState<"DEMO" | "LIVE">("DEMO");
  const [loginId, setLoginId] = useState("");
  const [serverName, setServerName] = useState("XMGlobal-MT5 9");
  const [password, setPassword] = useState("");
  const [hasStoredPassword, setHasStoredPassword] = useState(false);
  const [terminalPath, setTerminalPath] = useState(
    "C:\\Program Files\\XM Global MT5\\terminal64.exe"
  );
  const [showPassword, setShowPassword] = useState(false);
  const [isSavingAccount, setIsSavingAccount] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);

  // Gemini AI Form
  const [geminiApiKey, setGeminiApiKey] = useState("");
  const [hasStoredGeminiKey, setHasStoredGeminiKey] = useState(false);
  const [geminiModel, setGeminiModel] = useState("gemini-3.8-flash");
  const [isSavingAI, setIsSavingAI] = useState(false);
  const [isTestingGemini, setIsTestingGemini] = useState(false);
  const [geminiTestStatus, setGeminiTestStatus] = useState<string | null>(null);

  // Risk Locks
  const [scalpRiskPct, setScalpRiskPct] = useState(0.5);
  const [swingRiskPct, setSwingRiskPct] = useState(1.0);
  const [maxMarginUsagePct, setMaxMarginUsagePct] = useState(18.0);
  const [dailyDDPct, setDailyDDPct] = useState(2.5);
  const [weeklyDDPct, setWeeklyDDPct] = useState(5.0);

  // Telegram
  const [telegramToken, setTelegramToken] = useState("");
  const [telegramChatId, setTelegramChatId] = useState("");
  const [isSendingTestTelegram, setIsSendingTestTelegram] = useState(false);

  // Diagnostics
  const [smokeReport, setSmokeReport] = useState<any | null>(null);
  const [isRunningSmokeCheck, setIsRunningSmokeCheck] = useState(false);

  // Database & Remote Hosting
  const [dbStatus, setDbStatus] = useState<any>(null);
  const [remoteHost, setRemoteHost] = useState("");
  const [remotePort, setRemotePort] = useState(3306);
  const [remoteUser, setRemoteUser] = useState("");
  const [remotePassword, setRemotePassword] = useState("");
  const [remoteDbName, setRemoteDbName] = useState("");
  const [syncLocalData, setSyncLocalData] = useState(true);
  const [isTestingDb, setIsTestingDb] = useState(false);
  const [isApplyingDb, setIsApplyingDb] = useState(false);
  const [dbTestResult, setDbTestResult] = useState<any>(null);
  const [activeDbTarget, setActiveDbTarget] = useState<string>("LOCAL_XAMPP");

  useEffect(() => {
    if (isOpen) {
      loadSettings();
      loadAccount(accountType);
      loadDbStatus();
    }
  }, [isOpen, accountType]);

  const loadDbStatus = async () => {
    try {
      const data = await api.dbAdmin.getStatus();
      setDbStatus(data);
      if (data.active_target) setActiveDbTarget(data.active_target);
      if (data.remote_profile) {
        if (data.remote_profile.host) setRemoteHost(data.remote_profile.host);
        if (data.remote_profile.port) setRemotePort(data.remote_profile.port);
        if (data.remote_profile.user) setRemoteUser(data.remote_profile.user);
        if (data.remote_profile.database) setRemoteDbName(data.remote_profile.database);
        if (data.remote_profile.has_password) setRemotePassword("••••••••");
      }
    } catch (e: any) {
      console.warn("Could not load db status:", e);
    }
  };

  const handleTestRemoteDb = async () => {
    setIsTestingDb(true);
    setDbTestResult(null);
    try {
      const res = await api.dbAdmin.testConnection({
        host: remoteHost,
        port: remotePort,
        user: remoteUser,
        password: remotePassword === "••••••••" ? "" : remotePassword,
        database: remoteDbName,
      });
      setDbTestResult(res);
      if (res.success) {
        toast.success("Remote MySQL Connected", res.message);
      } else {
        toast.error("Connection Failed", res.message);
      }
    } catch (e: any) {
      toast.error("Test Failed", e.message || String(e));
    } finally {
      setIsTestingDb(false);
    }
  };

  const handleApplyRemoteDb = async () => {
    setIsApplyingDb(true);
    try {
      const res = await api.dbAdmin.applyConnection({
        host: remoteHost,
        port: remotePort,
        user: remoteUser,
        password: remotePassword === "••••••••" ? "" : remotePassword,
        database: remoteDbName,
        sync_data: syncLocalData,
      });
      toast.success("Remote MySQL Applied", res.message);
      loadDbStatus();
    } catch (e: any) {
      toast.error("Migration Failed", e.message || String(e));
    } finally {
      setIsApplyingDb(false);
    }
  };

  const handleSwitchDbTarget = async (target: string) => {
    try {
      await api.dbAdmin.switchTarget(target);
      setActiveDbTarget(target);
      toast.info("Target Switched", `Active database target set to ${target}.`);
      loadDbStatus();
    } catch (e: any) {
      toast.error("Switch Failed", e.message || String(e));
    }
  };

  const loadSettings = async () => {
    try {
      const data = await api.settings.get();
      const m = data.gemini_live_model || "gemini-3.8-flash";
      setGeminiModel(m.includes("2.5") ? "gemini-3.8-flash" : m);
      setHasStoredGeminiKey(Boolean(data.has_gemini_api_key));
      setScalpRiskPct(data.scalp_risk_pct ?? 0.5);
      setSwingRiskPct(data.swing_risk_pct ?? 1.0);
      setMaxMarginUsagePct(data.max_margin_usage_pct ?? 18.0);
      setDailyDDPct(data.daily_dd_limit_pct ?? 2.5);
      setWeeklyDDPct(data.weekly_dd_limit_pct ?? 5.0);
      setTelegramChatId(data.telegram_admin_chat_id || "");
    } catch (e: any) {
      console.error("Failed to load settings:", e);
    }
  };

  const loadAccount = async (type: string) => {
    try {
      const data = await api.accounts.getProfile(type);
      setLoginId(data.login_id ? String(data.login_id) : "");
      setServerName(data.server_name || "XMGlobal-MT5 10");
      if (data.terminal_path) setTerminalPath(data.terminal_path);
      setHasStoredPassword(Boolean(data.has_password));
      setPassword("");
    } catch (e: any) {
      console.error("Failed to load account profile:", e);
    }
  };

  const handleAutoDetectPath = async () => {
    try {
      const res = await api.accounts.detectPath();
      if (res.detected_path) {
        setTerminalPath(res.detected_path);
        toast.success("Terminal Detected", res.detected_path);
      } else {
        toast.warning("Auto-detect", "Default terminal path not found on drive.");
      }
    } catch (e: any) {
      toast.error("Auto-detect Failed", e.message);
    }
  };

  const handleSaveAccount = async () => {
    setIsSavingAccount(true);
    try {
      const payload: any = {
        login_id: loginId.trim(),
        server_name: serverName.trim(),
        terminal_path: terminalPath.trim(),
      };
      if (password && password.trim() && password !== "••••••••") {
        payload.password = password.trim();
      }

      await api.accounts.saveProfile(accountType, payload);
      toast.success("Profile Saved", `${accountType} credentials (Login: ${loginId.trim()}) persisted to MySQL.`);
      setPassword("");
      await loadAccount(accountType);
    } catch (e: any) {
      toast.error("Save Failed", e.message);
    } finally {
      setIsSavingAccount(false);
    }
  };

  const handleConnectAccount = async () => {
    setIsConnecting(true);
    try {
      const payload: any = {
        account_type: accountType,
        login_id: loginId.trim(),
        server_name: serverName.trim(),
        terminal_path: terminalPath.trim(),
      };
      if (password && password.trim() && password !== "••••••••") {
        payload.password = password.trim();
      }

      const res = await api.accounts.connect(payload);
      toast.success("MT5 Connected", res.message || `Connected to ${accountType}.`);
      setPassword("");
      await loadAccount(accountType);
    } catch (e: any) {
      await loadAccount(accountType).catch(() => {});
      toast.error("MT5 Connection Failed", e.message);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleSyncPairs = async () => {
    try {
      const res = await api.accounts.syncSymbols();
      const count = Object.keys(res.pairs || {}).length;
      toast.success("Symbol Specs Synced", `Synchronized ${count} XM pairs.`);
    } catch (e: any) {
      toast.error("Sync Failed", e.message);
    }
  };

  const handleSaveAI = async () => {
    setIsSavingAI(true);
    try {
      const payload: any = {
        gemini_live_model: geminiModel,
        gemini_forensic_model: geminiModel,
      };
      if (geminiApiKey && geminiApiKey !== "••••••••") {
        payload.gemini_api_key = geminiApiKey.trim();
      }

      await api.settings.update(payload);
      toast.success("AI Settings Saved", "Gemini configuration persisted to MySQL.");
      setGeminiApiKey("");
      await loadSettings();
    } catch (e: any) {
      toast.error("Save AI Failed", e.message);
    } finally {
      setIsSavingAI(false);
    }
  };

  const handleTestGeminiKey = async () => {
    setIsTestingGemini(true);
    setGeminiTestStatus(null);
    try {
      const keyToSend = geminiApiKey && geminiApiKey !== "••••••••" ? geminiApiKey.trim() : undefined;
      const res = await api.settings.testGemini(keyToSend, geminiModel);
      const modelTested = res.tested_model || res.model || geminiModel;
      setGeminiTestStatus(`Verified in ${res.latency_ms}ms (${modelTested})`);
      toast.success("Gemini API Key Verified", res.message);
    } catch (e: any) {
      setGeminiTestStatus(`Failed: ${e.message}`);
      toast.error("Gemini Verification Error", e.message);
    } finally {
      setIsTestingGemini(false);
    }
  };

  const handleSaveRisk = async () => {
    try {
      await api.settings.update({
        scalp_risk_pct: scalpRiskPct,
        swing_risk_pct: swingRiskPct,
        max_margin_usage_pct: maxMarginUsagePct,
        daily_dd_limit_pct: dailyDDPct,
        weekly_dd_limit_pct: weeklyDDPct,
      });
      toast.success("Risk Locks Saved", "Operational risk parameters active in MySQL.");
    } catch (e: any) {
      toast.error("Save Risk Failed", e.message);
    }
  };

  const handleSaveTelegram = async () => {
    try {
      const payload: any = {
        telegram_admin_chat_id: telegramChatId.trim(),
      };
      if (telegramToken && telegramToken !== "••••••••") {
        payload.telegram_bot_token = telegramToken.trim();
      }
      await api.settings.update(payload);
      toast.success("Telegram Saved", "Telegram configuration updated.");
      setTelegramToken("");
    } catch (e: any) {
      toast.error("Telegram Save Failed", e.message);
    }
  };

  const handleTestTelegramMessage = async () => {
    setIsSendingTestTelegram(true);
    try {
      const res = await api.telegram.testMessage(telegramChatId.trim() || undefined);
      toast.success("Telegram Dispatched", res.message);
    } catch (e: any) {
      toast.error("Telegram Error", e.message);
    } finally {
      setIsSendingTestTelegram(false);
    }
  };

  const handleRunSmokeCheck = async () => {
    setIsRunningSmokeCheck(true);
    try {
      const res = await api.health.smokeCheck();
      setSmokeReport(res);
      toast.success("Diagnostics Complete", `System status: ${res.status} (${res.elapsed_ms}ms)`);
    } catch (e: any) {
      toast.error("Diagnostics Error", e.message);
    } finally {
      setIsRunningSmokeCheck(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-xs z-50 flex items-center justify-center p-4 animate-in fade-in">
      <div className="bg-[#121824] border border-slate-800 rounded-2xl max-w-2xl w-full shadow-2xl flex flex-col overflow-hidden max-h-[92vh]">
        {/* Header */}
        <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between bg-[#0E131D]">
          <div className="font-bold text-white text-sm flex items-center gap-2">
            <Sliders className="w-4 h-4 text-blue-400" />
            <span>PORTAL CONFIGURATION & RISK VAULT</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigator */}
        <div className="flex border-b border-slate-800 bg-slate-900/60 px-5 text-xs font-semibold">
          {[
            { id: "ACCOUNTS", label: "MT5 Profiles" },
            { id: "AI", label: "Gemini AI" },
            { id: "RISK", label: "Risk Locks" },
            { id: "TELEGRAM", label: "Telegram" },
            { id: "DATABASE", label: "MySQL & Cloud Hosting" },
            { id: "DIAG", label: "Diagnostics" },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id as any)}
              className={`py-2.5 px-3 border-b-2 transition ${
                activeTab === t.id
                  ? "border-blue-500 text-white font-bold"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Body Content */}
        <div className="p-5 flex-1 overflow-y-auto space-y-4 text-xs">
          {/* TAB 1: MT5 ACCOUNTS */}
          {activeTab === "ACCOUNTS" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-slate-400 font-semibold">Context Profile:</span>
                  <button
                    onClick={() => setAccountType("DEMO")}
                    className={`px-3 py-1 rounded-lg font-bold transition ${
                      accountType === "DEMO"
                        ? "bg-blue-600 text-white"
                        : "bg-slate-800 text-slate-400 hover:text-white"
                    }`}
                  >
                    DEMO PROFILE
                  </button>
                  <button
                    onClick={() => setAccountType("LIVE")}
                    className={`px-3 py-1 rounded-lg font-bold transition ${
                      accountType === "LIVE"
                        ? "bg-red-600 text-white"
                        : "bg-slate-800 text-slate-400 hover:text-white"
                    }`}
                  >
                    LIVE PROFILE
                  </button>
                </div>

                <button
                  onClick={handleSyncPairs}
                  className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-[11px] font-semibold border border-slate-700"
                  title="Synchronize live XM contract & spread specs"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Sync Pairs</span>
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 block mb-1">Login ID (Account Number)</label>
                  <input
                    type="text"
                    value={loginId}
                    onChange={(e) => setLoginId(e.target.value)}
                    placeholder="e.g. 337246863"
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-mono"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">Server Name</label>
                  <input
                    type="text"
                    value={serverName}
                    onChange={(e) => setServerName(e.target.value)}
                    placeholder="e.g. XMGlobal-MT5 9"
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-mono"
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="text-slate-400">MT5 Password</label>
                  {hasStoredPassword && (
                    <span className="text-[10px] text-emerald-400 font-semibold flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> Password stored securely in vault
                    </span>
                  )}
                </div>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={hasStoredPassword ? "•••••••• (Password saved in AES-256 vault - enter only to change)" : "Enter MT5 password"}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 pr-9 font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-200"
                    title={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="text-slate-400">Terminal Executable Path</label>
                  <button
                    onClick={handleAutoDetectPath}
                    className="text-[10px] text-blue-400 hover:underline flex items-center gap-1 font-semibold"
                  >
                    <FolderSearch className="w-3 h-3" /> Auto-Detect
                  </button>
                </div>
                <input
                  type="text"
                  value={terminalPath}
                  onChange={(e) => setTerminalPath(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-mono text-[11px]"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800/80">
                <button
                  disabled={isSavingAccount}
                  onClick={handleSaveAccount}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold rounded-lg transition"
                >
                  {isSavingAccount ? "Saving to MySQL..." : "Save Profile to MySQL"}
                </button>
                <button
                  disabled={isConnecting}
                  onClick={handleConnectAccount}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg shadow transition flex items-center gap-2"
                >
                  <Radio className="w-4 h-4" />
                  <span>{isConnecting ? "Connecting to MT5..." : "Save & Connect MT5"}</span>
                </button>
              </div>
            </div>
          )}

          {/* TAB 2: GEMINI AI */}
          {activeTab === "AI" && (
            <div className="space-y-4">
              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="text-slate-400">Gemini API Key</label>
                  {hasStoredGeminiKey && (
                    <span className="text-[10px] text-emerald-400 font-semibold flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> Encrypted via Fernet Vault
                    </span>
                  )}
                </div>
                <input
                  type="password"
                  value={geminiApiKey}
                  onChange={(e) => setGeminiApiKey(e.target.value)}
                  placeholder={hasStoredGeminiKey ? "•••••••• (Leave blank to keep existing key)" : "AIzaSy..."}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-mono text-xs"
                />
              </div>

              <div>
                <label className="text-slate-400 block mb-1">Supervisory Model (Gemini 3.x)</label>
                <select
                  value={geminiModel}
                  onChange={(e) => setGeminiModel(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-semibold text-xs"
                >
                  <option value="gemini-3.8-flash">gemini-3.8-flash (Recommended: Low Latency Live Scanner - Free & Paid)</option>
                  <option value="gemini-3.5-flash-lite">gemini-3.5-flash-lite (Ultra-Low Latency - Free & Paid)</option>
                  <option value="gemini-3.6-flash">gemini-3.6-flash (Fast Multimodal - Free & Paid)</option>
                  <option value="gemini-3-flash-preview">gemini-3-flash-preview (Gemini 3 Preview - Free Tier Safe)</option>
                  <option value="gemini-3.1-pro-preview">gemini-3.1-pro-preview (Paid Billing Tier Only: Deep Reasoning)</option>
                </select>
              </div>

              {geminiTestStatus && (
                <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-xs font-mono text-slate-300">
                  {geminiTestStatus}
                </div>
              )}

              <div className="flex justify-between items-center pt-2 border-t border-slate-800/80">
                <button
                  disabled={isTestingGemini}
                  onClick={handleTestGeminiKey}
                  className="flex items-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold rounded-lg transition"
                >
                  <Zap className="w-3.5 h-3.5 text-amber-400" />
                  <span>{isTestingGemini ? "Pinging Gemini..." : "Test Gemini Key"}</span>
                </button>
                <button
                  disabled={isSavingAI}
                  onClick={handleSaveAI}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg transition"
                >
                  {isSavingAI ? "Saving..." : "Save AI Settings"}
                </button>
              </div>
            </div>
          )}

          {/* TAB 3: RISK LOCKS */}
          {activeTab === "RISK" && (
            <div className="space-y-4">
              <div className="p-3 bg-red-950/20 border border-red-500/30 rounded-lg text-slate-300 leading-relaxed">
                <strong className="text-red-400 font-bold block mb-1">
                  Deterministic Hard Risk Locks (Strictly Below AI Layer):
                </strong>
                These risk boundaries live locally in Python and MQL5. Gemini supervisory decisions cannot override
                or bypass these limits.
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 block mb-1">Scalp Risk % (Per Trade)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={scalpRiskPct}
                    onChange={(e) => setScalpRiskPct(parseFloat(e.target.value))}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">Swing Risk % (Per Trade)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={swingRiskPct}
                    onChange={(e) => setSwingRiskPct(parseFloat(e.target.value))}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-slate-400 block mb-1">Max Margin Cap %</label>
                  <input
                    type="number"
                    step="0.5"
                    value={maxMarginUsagePct}
                    onChange={(e) => setMaxMarginUsagePct(parseFloat(e.target.value))}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-bold text-amber-400"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">Daily DD Lock %</label>
                  <input
                    type="number"
                    step="0.1"
                    value={dailyDDPct}
                    onChange={(e) => setDailyDDPct(parseFloat(e.target.value))}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-bold text-red-400"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">Weekly DD Lock %</label>
                  <input
                    type="number"
                    step="0.1"
                    value={weeklyDDPct}
                    onChange={(e) => setWeeklyDDPct(parseFloat(e.target.value))}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-bold text-red-400"
                  />
                </div>
              </div>

              <div className="flex justify-end pt-2 border-t border-slate-800/80">
                <button
                  onClick={handleSaveRisk}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg transition"
                >
                  Save Risk Locks
                </button>
              </div>
            </div>
          )}

          {/* TAB 4: TELEGRAM */}
          {activeTab === "TELEGRAM" && (
            <div className="space-y-4">
              <div>
                <label className="text-slate-400 block mb-1">Telegram Bot Token (from @BotFather)</label>
                <input
                  type="password"
                  value={telegramToken}
                  onChange={(e) => setTelegramToken(e.target.value)}
                  placeholder="Enter bot token"
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-mono"
                />
              </div>
              <div>
                <label className="text-slate-400 block mb-1">Admin Telegram Chat ID</label>
                <input
                  type="text"
                  value={telegramChatId}
                  onChange={(e) => setTelegramChatId(e.target.value)}
                  placeholder="e.g. 123456789"
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-slate-100 font-mono"
                />
              </div>

              <div className="flex justify-between items-center pt-2 border-t border-slate-800/80">
                <button
                  disabled={isSendingTestTelegram}
                  onClick={handleTestTelegramMessage}
                  className="flex items-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold rounded-lg transition"
                >
                  <Send className="w-3.5 h-3.5 text-blue-400" />
                  <span>{isSendingTestTelegram ? "Sending..." : "Send Test Alert"}</span>
                </button>
                <button
                  onClick={handleSaveTelegram}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg transition"
                >
                  Save Telegram Config
                </button>
              </div>
            </div>
          )}

          {/* TAB: DATABASE & CLOUD HOSTING */}
          {activeTab === "DATABASE" && (
            <div className="space-y-4">
              {/* Target Selector & Status */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-xs font-bold text-white flex items-center gap-1.5">
                      <Database className="w-4 h-4 text-cyan-400" />
                      <span>Active MySQL Target</span>
                    </span>
                    <span className="text-[11px] text-slate-400">
                      Switch between local development XAMPP and remote web-hosting / cPanel MySQL.
                    </span>
                  </div>

                  <div className="flex bg-slate-950 border border-slate-800 rounded-lg p-0.5">
                    <button
                      onClick={() => handleSwitchDbTarget("LOCAL_XAMPP")}
                      className={`px-3 py-1 rounded text-xs font-bold transition ${
                        activeDbTarget === "LOCAL_XAMPP"
                          ? "bg-cyan-600 text-white"
                          : "text-slate-400 hover:text-white"
                      }`}
                    >
                      LOCAL XAMPP
                    </button>
                    <button
                      onClick={() => handleSwitchDbTarget("REMOTE_HOSTED")}
                      className={`px-3 py-1 rounded text-xs font-bold transition ${
                        activeDbTarget === "REMOTE_HOSTED"
                          ? "bg-cyan-600 text-white"
                          : "text-slate-400 hover:text-white"
                      }`}
                    >
                      REMOTE HOSTED
                    </button>
                  </div>
                </div>

                {dbStatus && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-2 border-t border-slate-800/80 font-mono text-[11px]">
                    <div className="bg-slate-950 p-2 rounded border border-slate-800">
                      <div className="text-slate-500">Host & Port</div>
                      <div className="font-bold text-slate-200 truncate">
                        {dbStatus.host}:{dbStatus.port}
                      </div>
                    </div>
                    <div className="bg-slate-950 p-2 rounded border border-slate-800">
                      <div className="text-slate-500">Database</div>
                      <div className="font-bold text-cyan-400 truncate">{dbStatus.database_name}</div>
                    </div>
                    <div className="bg-slate-950 p-2 rounded border border-slate-800">
                      <div className="text-slate-500">Latency</div>
                      <div className="font-bold text-emerald-400">{dbStatus.latency_ms}ms</div>
                    </div>
                    <div className="bg-slate-950 p-2 rounded border border-slate-800">
                      <div className="text-slate-500">Total Rows</div>
                      <div className="font-bold text-purple-300">{dbStatus.total_rows} rows</div>
                    </div>
                  </div>
                )}
              </div>

              {/* Remote MySQL Credentials Form */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 space-y-3">
                <div className="flex items-center gap-2 text-xs font-bold text-white">
                  <Server className="w-4 h-4 text-cyan-400" />
                  <span>Remote Web-Hosting / cPanel Credentials</span>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div className="col-span-2">
                    <label className="text-slate-400 block mb-1">MySQL Host / IP</label>
                    <input
                      type="text"
                      value={remoteHost}
                      onChange={(e) => setRemoteHost(e.target.value)}
                      placeholder="e.g. sql.myhosting.com or 192.168.1.10"
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-100 font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Port</label>
                    <input
                      type="number"
                      value={remotePort}
                      onChange={(e) => setRemotePort(parseInt(e.target.value) || 3306)}
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-100 font-mono"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="text-slate-400 block mb-1">Username</label>
                    <input
                      type="text"
                      value={remoteUser}
                      onChange={(e) => setRemoteUser(e.target.value)}
                      placeholder="e.g. u12345_trading"
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-100 font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Password</label>
                    <input
                      type="password"
                      value={remotePassword}
                      onChange={(e) => setRemotePassword(e.target.value)}
                      placeholder="Remote DB password"
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-100 font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Database Name</label>
                    <input
                      type="text"
                      value={remoteDbName}
                      onChange={(e) => setRemoteDbName(e.target.value)}
                      placeholder="e.g. u12345_xm_v2"
                      className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-100 font-mono"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <label className="flex items-center gap-2 cursor-pointer text-slate-300">
                    <input
                      type="checkbox"
                      checked={syncLocalData}
                      onChange={(e) => setSyncLocalData(e.target.checked)}
                      className="rounded bg-slate-950 border-slate-700 text-cyan-600 focus:ring-0"
                    />
                    <span>Sync existing local tables & settings to remote on apply</span>
                  </label>

                  <div className="flex gap-2">
                    <button
                      disabled={isTestingDb || !remoteHost || !remoteUser || !remoteDbName}
                      onClick={handleTestRemoteDb}
                      className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold rounded text-xs border border-slate-700 transition disabled:opacity-50"
                    >
                      {isTestingDb ? "Pinging..." : "Test Connection"}
                    </button>
                    <button
                      disabled={isApplyingDb || !remoteHost || !remoteUser || !remoteDbName}
                      onClick={handleApplyRemoteDb}
                      className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white font-bold rounded text-xs transition disabled:opacity-50"
                    >
                      {isApplyingDb ? "Migrating..." : "Apply & Migrate"}
                    </button>
                  </div>
                </div>

                {dbTestResult && (
                  <div
                    className={`p-2.5 rounded text-xs font-mono border ${
                      dbTestResult.success
                        ? "bg-emerald-950/30 border-emerald-500/30 text-emerald-300"
                        : "bg-red-950/30 border-red-500/30 text-red-300"
                    }`}
                  >
                    <div>{dbTestResult.message}</div>
                    {dbTestResult.server_version && <div>Server: {dbTestResult.server_version}</div>}
                  </div>
                )}
              </div>

              {/* Data Export & Backup Hub */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5 space-y-3">
                <div className="flex items-center gap-2 text-xs font-bold text-white">
                  <HardDrive className="w-4 h-4 text-emerald-400" />
                  <span>Database Export & Settings Backup Hub</span>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => window.open(api.dbAdmin.exportSqlUrl(), "_blank")}
                    className="flex items-center justify-center gap-2 p-3 bg-slate-950 hover:bg-slate-800 border border-slate-800 rounded-lg text-slate-200 font-bold text-xs transition"
                  >
                    <Download className="w-4 h-4 text-cyan-400" />
                    <span>Download phpMyAdmin SQL Dump (.sql)</span>
                  </button>

                  <button
                    onClick={() => window.open(api.dbAdmin.exportSettingsJsonUrl(), "_blank")}
                    className="flex items-center justify-center gap-2 p-3 bg-slate-950 hover:bg-slate-800 border border-slate-800 rounded-lg text-slate-200 font-bold text-xs transition"
                  >
                    <Download className="w-4 h-4 text-emerald-400" />
                    <span>Export Settings JSON Backup (.json)</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* TAB 5: DIAGNOSTICS */}
          {activeTab === "DIAG" && (
            <div className="space-y-4">
              <div className="space-y-2.5 font-mono text-xs">
                <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 flex justify-between items-center">
                  <span>XAMPP MariaDB / MySQL (xm_trading_v2)</span>
                  <span className={dbHealthy ? "text-emerald-400 font-bold" : "text-red-400 font-bold"}>
                    {dbHealthy ? "CONNECTED :3306" : "OFFLINE / UNREACHABLE"}
                  </span>
                </div>
                <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 flex justify-between items-center">
                  <span>MetaTrader 5 Windows DLL Bridge</span>
                  <span className={isMt5Connected ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
                    {isMt5Connected ? "CONNECTED & SYNCED" : "TERMINAL OFFLINE"}
                  </span>
                </div>
                <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 flex justify-between items-center">
                  <span>Deal Reconciler & Watchdog</span>
                  <span className="text-emerald-400 font-bold">ACTIVE (10s LOOP)</span>
                </div>
                <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 flex justify-between items-center">
                  <span>Live Interval Execution Scheduler</span>
                  <span className="text-emerald-400 font-bold">RUNNING (1s WS TICK)</span>
                </div>
              </div>

              {smokeReport && (
                <div className="p-3.5 bg-slate-950 rounded-xl border border-slate-800 space-y-2 text-xs font-mono">
                  <div className="font-bold text-white flex justify-between">
                    <span>Smoke Test Results</span>
                    <span className={smokeReport.status === "HEALTHY" ? "text-emerald-400" : "text-amber-400"}>
                      {smokeReport.status} ({smokeReport.elapsed_ms}ms)
                    </span>
                  </div>
                  <div className="text-slate-300 space-y-1 text-[11px]">
                    <div>• MySQL: {smokeReport.results?.mysql?.message}</div>
                    <div>• MT5 Bridge: {smokeReport.results?.mt5_bridge?.message}</div>
                    <div>• Gemini AI: {smokeReport.results?.gemini_ai?.message}</div>
                    <div>• Spool Records: {smokeReport.results?.watchdog?.spool_count}</div>
                  </div>
                </div>
              )}

              <div className="flex justify-end pt-2 border-t border-slate-800/80">
                <button
                  disabled={isRunningSmokeCheck}
                  onClick={handleRunSmokeCheck}
                  className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition"
                >
                  <Activity className="w-4 h-4" />
                  <span>{isRunningSmokeCheck ? "Running Smoke Check..." : "Run 1-Click System Smoke Check"}</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
