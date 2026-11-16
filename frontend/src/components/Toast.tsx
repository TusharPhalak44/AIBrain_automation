import React, { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from "lucide-react";

export type ToastType = "success" | "error" | "warning" | "info";

export interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
}

interface ToastContextType {
  toasts: ToastMessage[];
  addToast: (type: ToastType, title: string, message?: string) => void;
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  warning: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((type: ToastType, title: string, message?: string) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, type, title, message }]);
    setTimeout(() => {
      removeToast(id);
    }, 4500);
  }, [removeToast]);

  const success = useCallback((title: string, message?: string) => addToast("success", title, message), [addToast]);
  const error = useCallback((title: string, message?: string) => addToast("error", title, message), [addToast]);
  const warning = useCallback((title: string, message?: string) => addToast("warning", title, message), [addToast]);
  const info = useCallback((title: string, message?: string) => addToast("info", title, message), [addToast]);

  return (
    <ToastContext.Provider value={{ toasts, addToast, success, error, warning, info, removeToast }}>
      {children}
      {/* Toast Render Container */}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
        {toasts.map((t) => {
          const isSuccess = t.type === "success";
          const isError = t.type === "error";
          const isWarning = t.type === "warning";

          const bgClass = isSuccess
            ? "bg-slate-900/95 border-emerald-500/80 text-emerald-300"
            : isError
            ? "bg-slate-900/95 border-red-500/80 text-red-300"
            : isWarning
            ? "bg-slate-900/95 border-amber-500/80 text-amber-300"
            : "bg-slate-900/95 border-blue-500/80 text-blue-300";

          const Icon = isSuccess ? CheckCircle2 : isError ? AlertCircle : isWarning ? AlertTriangle : Info;

          return (
            <div
              key={t.id}
              className={`pointer-events-auto p-3.5 rounded-xl border shadow-2xl backdrop-blur-md flex items-start gap-3 transition-all duration-300 animate-in fade-in slide-in-from-top-2 ${bgClass}`}
            >
              <Icon className="w-5 h-5 flex-shrink-0 mt-0.5" />
              <div className="flex-1 text-xs">
                <div className="font-bold text-white tracking-wide">{t.title}</div>
                {t.message && <div className="text-slate-300 mt-0.5 leading-relaxed">{t.message}</div>}
              </div>
              <button
                onClick={() => removeToast(t.id)}
                className="text-slate-400 hover:text-white p-0.5 rounded transition"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}

