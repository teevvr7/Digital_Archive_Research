"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";

type ToastVariant = "success" | "error" | "info";

interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const VARIANT_STYLES: Record<ToastVariant, { icon: typeof CheckCircle2; className: string }> = {
  success: { icon: CheckCircle2, className: "bg-white border-green-200 text-green-800" },
  error: { icon: XCircle, className: "bg-white border-red-200 text-red-800" },
  info: { icon: Info, className: "bg-white border-blue-200 text-blue-800" },
};

const AUTO_DISMISS_MS = 4000;

/** App-wide toast notifications. Wrap the app once in <ToastProvider>, call useToast() anywhere. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // The portal must not render during SSR or the client's first (pre-hydration)
  // pass — `document` exists on the client immediately, but not on the server,
  // so rendering based on that check alone mismatches and breaks hydration.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (variant: ToastVariant, message: string) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setToasts((prev) => [...prev, { id, message, variant }]);
      setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const api: ToastApi = {
    success: (message: string) => push("success", message),
    error: (message: string) => push("error", message),
    info: (message: string) => push("info", message),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      {mounted &&
        createPortal(
          <div
            data-testid="toast-region"
            aria-live="polite"
            className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 w-full max-w-sm"
          >
            {toasts.map((t) => {
              const { icon: Icon, className } = VARIANT_STYLES[t.variant];
              return (
                <div
                  key={t.id}
                  data-testid={`toast-${t.variant}`}
                  className={`flex items-start gap-2 rounded-xl border shadow-lg px-4 py-3 text-sm ${className}`}
                >
                  <Icon className="w-4 h-4 mt-0.5 shrink-0" />
                  <p className="flex-1">{t.message}</p>
                  <button
                    onClick={() => dismiss(t.id)}
                    className="text-current opacity-50 hover:opacity-100 shrink-0"
                    aria-label="Dismiss"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              );
            })}
          </div>,
          document.body,
        )}
    </ToastContext.Provider>
  );
}

/** Returns { success, error, info } to fire a toast from anywhere under <ToastProvider>. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}
