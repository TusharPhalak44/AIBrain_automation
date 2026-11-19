/**
 * Centralized API Service Layer for XM Global MT5 Portal V2.
 * Strictly maps 1-to-1 to FastAPI routes with encoded symbol handling.
 */

const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const fullUrl = API_BASE ? `${API_BASE}${url}` : url;
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (options.body && typeof options.body === "string" && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(fullUrl, { ...options, headers });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const errorJson = await response.json();
      if (errorJson.detail) {
        errorDetail = typeof errorJson.detail === "string" ? errorJson.detail : errorJson.detail.message || JSON.stringify(errorJson.detail);
      } else if (errorJson.message) {
        errorDetail = errorJson.message;
      }
    } catch {
      // Ignore JSON parse error on non-JSON response
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

export const api = {
  settings: {
    get: () => request<any>("/api/settings"),
    update: (payload: any) =>
      request<any>("/api/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    testGemini: (apiKey?: string, model?: string) =>
      request<any>("/api/settings/test-gemini", {
        method: "POST",
        body: JSON.stringify({ api_key: apiKey, model }),
      }),
    getGeminiModels: () => request<any>("/api/settings/gemini-models"),
  },

  accounts: {
    getLiveState: () => request<any>("/api/accounts/live-state"),
    getProfiles: () => request<any[]>("/api/accounts/profiles"),
    getProfile: (type: string) => request<any>(`/api/accounts/${encodeURIComponent(type)}`),
    saveProfile: (type: string, payload: any) =>
      request<any>(`/api/accounts/${encodeURIComponent(type)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    connect: (payload?: {
      account_type?: string;
      login_id?: string | number;
      password?: string;
      server_name?: string;
      terminal_path?: string;
    }) =>
      request<any>("/api/accounts/connect", {
        method: "POST",
        body: JSON.stringify(payload || {}),
      }),
    syncSymbols: () =>
      request<any>("/api/accounts/sync", {
        method: "POST",
      }),
    detectPath: () =>
      request<any>("/api/accounts/detect-path", {
        method: "POST",
      }),
    switch: (targetAccountType: string, actionOnPositions = "KEEP_EA_PROTECTED", confirmToken?: string) =>
      request<any>("/api/accounts/switch", {
        method: "POST",
        body: JSON.stringify({
          target_account_type: targetAccountType,
          action_on_positions: actionOnPositions,
          confirm_token: confirmToken,
        }),
      }),
  },

  instruments: {
    getAll: () => request<any[]>("/api/instruments"),
  },

  pairs: {
    list: () => request<any[]>("/api/pairs"),
    update: (symbol: string, payload: any) =>
      request<any>(`/api/pairs/${encodeURIComponent(symbol)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    assignStrategy: (symbol: string, payload: { scalp_strategy_id?: number; swing_strategy_id?: number }) =>
      request<any>(`/api/pairs/${encodeURIComponent(symbol)}/assign-strategy`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },

  candles: {
    get: (symbol: string, timeframe = "M15", count = 250) =>
      request<any>(`/api/candles/${encodeURIComponent(symbol)}?timeframe=${timeframe}&count=${count}`),
  },

  trades: {
    getSummary: () => request<any>("/api/trades/live-summary"),
    getHistory: (params: { account_type?: string; symbol?: string; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (params.account_type) q.append("account_type", params.account_type);
      if (params.symbol) q.append("symbol", params.symbol);
      if (params.limit) q.append("limit", String(params.limit));
      return request<any[]>(`/api/trades?${q.toString()}`);
    },
    executeManualOrder: (payload: {
      symbol: string;
      order_type: "BUY" | "SELL";
      lots: number;
      sl: number;
      tp?: number;
      comment?: string;
    }) =>
      request<any>("/api/trades/execute", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    panicFlatten: () =>
      request<any>("/api/trades/panic-flatten", {
        method: "POST",
      }),
    closePosition: (ticket: number) =>
      request<any>(`/api/trades/${ticket}/close`, {
        method: "POST",
      }),
  },

  ai: {
    getReports: (params: { symbol?: string; account_type?: string; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (params.symbol) q.append("symbol", params.symbol);
      if (params.account_type) q.append("account_type", params.account_type);
      if (params.limit) q.append("limit", String(params.limit));
      return request<any[]>(`/api/ai/reports?${q.toString()}`);
    },
    scanPair: (symbol: string) =>
      request<any>(`/api/ai/scan/${encodeURIComponent(symbol)}`, {
        method: "POST",
      }),
    scanAll: () =>
      request<any>("/api/ai/scan-all", {
        method: "POST",
      }),
    updateInterval: (payload: { global_scan_interval_sec?: number; pair_intervals?: Record<string, number> }) =>
      request<any>("/api/ai/interval", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    stageCopilot: (payload: {
      symbol: string;
      mode?: string;
      direction: string;
      entry_price: number;
      sl: number;
      tp1: number;
      tp2: number;
      lots?: number;
      ai_analysis_summary?: string;
    }) =>
      request<any>("/api/ai/copilot/stage", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    approveCopilot: (tradeId: number) =>
      request<any>(`/api/ai/copilot/${tradeId}/approve`, {
        method: "POST",
      }),
    rejectCopilot: (tradeId: number) =>
      request<any>(`/api/ai/copilot/${tradeId}/reject`, {
        method: "POST",
      }),
    getNews: (symbol?: string) => {
      const q = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
      return request<any>(`/api/ai/news${q}`);
    },
    getRules: (params: { symbol?: string; status?: string; mode?: string } = {}) => {
      const q = new URLSearchParams();
      if (params.symbol) q.append("symbol", params.symbol);
      if (params.status) q.append("status", params.status);
      if (params.mode) q.append("mode", params.mode);
      return request<any[]>(`/api/ai/rules?${q.toString()}`);
    },
    updateRuleStatus: (ruleId: number, status: string) =>
      request<any>(`/api/ai/rules/${ruleId}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      }),
    runForensics: (tradeId: number) =>
      request<any>(`/api/ai/forensics/${tradeId}`, {
        method: "POST",
      }),
    getUpcomingSetups: () => request<any>("/api/ai/upcoming-setups"),
    getPatternMemory: (symbol?: string) => {
      const q = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
      return request<any[]>(`/api/ai/pattern-memory${q}`);
    },
    getPendingLimits: () => request<any[]>("/api/ai/pending-limits"),
    getCacheStatus: () => request<any>("/api/ai/cache/status"),
    clearCache: (forceAll: boolean = false) =>
      request<any>(`/api/ai/cache/clear${forceAll ? "?force_all=true" : ""}`, {
        method: "POST",
      }),
    updateCacheConfig: (payload: { auto_daily_enabled?: boolean; daily_purge_hour_utc?: number }) =>
      request<any>("/api/ai/cache/config", {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    getScannerConfig: () => request<any>("/api/ai/scanner/config"),
    updateScannerConfig: (payload: {
      global_scan_interval_sec?: number;
      scalp_planning_tf?: string;
      scalp_execution_tf?: string;
      swing_planning_tf?: string;
      swing_execution_tf?: string;
      pair_enabled_map?: Record<string, boolean>;
    }) =>
      request<any>("/api/ai/scanner/config", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    getPromptPreview: (symbol: string = "GOLD#") =>
      request<any>(`/api/ai/prompt-preview?symbol=${encodeURIComponent(symbol)}`),
    togglePair: (symbol: string) =>
      request<any>(`/api/ai/pairs/${encodeURIComponent(symbol)}/toggle`, {
        method: "POST",
      }),
  },

  strategies: {
    list: () => request<any[]>("/api/strategies"),
    validate: (code: string) =>
      request<any>("/api/strategies/validate", {
        method: "POST",
        body: JSON.stringify({ python_code: code }),
      }),
    create: (payload: { name: string; description?: string; target_mode: string; python_code: string; default_params?: any }) =>
      request<any>("/api/strategies", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (id: number, payload: any) =>
      request<any>(`/api/strategies/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    delete: (id: number) =>
      request<any>(`/api/strategies/${id}`, {
        method: "DELETE",
      }),
    restoreDefaults: () =>
      request<any>("/api/strategies/restore-defaults", {
        method: "POST",
      }),
    deleteBacktest: (runId: number) =>
      request<any>(`/api/strategies/backtests/${runId}`, {
        method: "DELETE",
      }),
    backtest: (payload: any) =>
      request<any>("/api/strategies/backtest", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    getBacktests: (symbol?: string, strategyId?: number) => {
      const q = new URLSearchParams();
      if (symbol) q.append("symbol", symbol);
      if (strategyId) q.append("strategy_id", String(strategyId));
      return request<any[]>(`/api/strategies/backtests?${q.toString()}`);
    },
    saveSnapshot: (payload: {
      backtest_run_id?: number;
      strategy_id?: number;
      custom_label: string;
      symbol: string;
      timeframe: string;
      test_mode: string;
      strategy_code: string;
      params?: any;
      metrics: any;
    }) =>
      request<any>("/api/strategies/save-snapshot", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    getSavedVault: () => request<any[]>("/api/strategies/saved-vault"),
    deleteSavedVault: (runId: number) =>
      request<any>(`/api/strategies/saved-vault/${runId}`, {
        method: "DELETE",
      }),
  },

  telegram: {
    getRecipients: () => request<any[]>("/api/telegram/recipients"),
    createRecipient: (payload: any) =>
      request<any>("/api/telegram/recipients", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    deleteRecipient: (id: number) =>
      request<any>(`/api/telegram/recipients/${id}`, {
        method: "DELETE",
      }),
    testMessage: (chatId?: string) => {
      const q = chatId ? `?chat_id=${encodeURIComponent(chatId)}` : "";
      return request<any>(`/api/telegram/test${q}`, {
        method: "POST",
      });
    },
  },

  reports: {
    exportUrl: (format = "PDF", accountType?: string) => {
      const q = new URLSearchParams({ format });
      if (accountType) q.append("account_type", accountType);
      return `/api/reports/export?${q.toString()}`;
    },
  },

  usage: {
    getSummary: (params: {
      granularity?: string;
      start_date?: string;
      end_date?: string;
      symbol?: string;
      model_id?: string;
      call_purpose?: string;
      account_type?: string;
      usd_to_inr_rate?: number;
    } = {}) => {
      const q = new URLSearchParams();
      if (params.granularity) q.append("granularity", params.granularity);
      if (params.start_date) q.append("start_date", params.start_date);
      if (params.end_date) q.append("end_date", params.end_date);
      if (params.symbol) q.append("symbol", params.symbol);
      if (params.model_id) q.append("model_id", params.model_id);
      if (params.call_purpose) q.append("call_purpose", params.call_purpose);
      if (params.account_type) q.append("account_type", params.account_type);
      if (params.usd_to_inr_rate) q.append("usd_to_inr_rate", String(params.usd_to_inr_rate));
      return request<any>(`/api/usage/summary?${q.toString()}`);
    },
    exportCsvUrl: (params: {
      start_date?: string;
      end_date?: string;
      symbol?: string;
      model_id?: string;
      call_purpose?: string;
      account_type?: string;
    } = {}) => {
      const q = new URLSearchParams();
      if (params.start_date) q.append("start_date", params.start_date);
      if (params.end_date) q.append("end_date", params.end_date);
      if (params.symbol) q.append("symbol", params.symbol);
      if (params.model_id) q.append("model_id", params.model_id);
      if (params.call_purpose) q.append("call_purpose", params.call_purpose);
      if (params.account_type) q.append("account_type", params.account_type);
      return `/api/usage/export?${q.toString()}`;
    },
    getRates: () => request<any>("/api/usage/rates"),
    updateRates: (payload: { rates?: any[]; gemini_use_free_tier?: boolean }) =>
      request<any>("/api/usage/rates", {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
  },

  dbAdmin: {
    getStatus: () => request<any>("/api/db-admin/status"),
    testConnection: (payload: any) =>
      request<any>("/api/db-admin/test-connection", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    applyConnection: (payload: any) =>
      request<any>("/api/db-admin/apply-connection", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    switchTarget: (target: string) =>
      request<any>(`/api/db-admin/switch-target?target=${encodeURIComponent(target)}`, {
        method: "POST",
      }),
    exportSqlUrl: () => "/api/db-admin/export-sql",
    exportSettingsJsonUrl: () => "/api/db-admin/export-settings-json",
    importSettingsJson: (payload: any) =>
      request<any>("/api/db-admin/import-settings-json", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },

  health: {
    get: () => request<any>("/api/health"),
    smokeCheck: () =>
      request<any>("/api/health/smoke-check", {
        method: "POST",
      }),
  },
};

