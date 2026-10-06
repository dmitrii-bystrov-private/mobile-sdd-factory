import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";

type ToastTone = "success" | "error";

type ToastState = {
  id: number;
  message: string;
  tone: ToastTone;
} | null;

type ToastContextValue = {
  showToast: (message: string, tone?: ToastTone) => void;
  showActivity: (message: string) => void;
  clearActivity: () => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

type ToastProviderProps = {
  children: ReactNode;
};

export function ToastProvider({ children }: ToastProviderProps): JSX.Element {
  const [toast, setToast] = useState<ToastState>(null);
  const [activityMessage, setActivityMessage] = useState<string | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ id: Date.now(), message, tone });
  }, []);

  const showActivity = useCallback((message: string) => {
    setActivityMessage(message);
  }, []);

  const clearActivity = useCallback(() => {
    setActivityMessage(null);
  }, []);

  useEffect(() => {
    if (toast === null) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => setToast(null), 2200);
    return () => window.clearTimeout(timeoutId);
  }, [toast]);

  const value = useMemo(
    () => ({ showToast, showActivity, clearActivity }),
    [showToast, showActivity, clearActivity],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      {activityMessage ? (
        <div className="app-activity-overlay" role="status" aria-live="polite">
          <div className="app-activity-chip">
            <span className="app-activity-spinner" aria-hidden="true" />
            <strong>{activityMessage}</strong>
          </div>
        </div>
      ) : null}
      {toast ? (
        <div className={`app-toast app-toast-${toast.tone}`} key={toast.id} role="status" aria-live="polite">
          {toast.message}
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (context === null) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return context;
}
