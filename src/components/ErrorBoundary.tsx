import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, RotateCw } from "lucide-react";

/**
 * ErrorBoundary — catches render/lifecycle throws so a single component crash
 * (a WebGL context failure, a store-selector throw, a modal bug) degrades to a
 * recoverable card instead of white-screening the whole SPA.
 *
 * A class can't call hooks, so the localized fallback markup lives in the
 * ErrorFallback function child; i18next default-value fallbacks keep it readable
 * even if i18n isn't ready (e.g. in tests). Pass `fallback={null}` to silently
 * drop a decorative layer (the ambient WebGL backdrop) on failure.
 */

function ErrorFallback({ onReset }: { onReset: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-[60vh] w-full items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-4 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-8 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(var(--surface-2))] text-amber-500">
          <AlertTriangle className="h-6 w-6" />
        </div>
        <div className="space-y-1.5">
          <h2 className="text-lg font-semibold tracking-tight text-[hsl(var(--text))]">
            {t("errors.crashTitle", "Something went wrong")}
          </h2>
          <p className="text-sm text-[hsl(var(--text-muted))]">
            {t(
              "errors.crashBody",
              "This panel hit an unexpected error. You can try again without losing your session.",
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition hover:opacity-90"
        >
          <RotateCw className="h-4 w-4" />
          {t("errors.crashReset", "Try again")}
        </button>
      </div>
    </div>
  );
}

interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * Custom fallback rendered instead of the default card. Pass `null` to render
   * nothing (decorative layers that should just vanish on failure).
   */
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  reset = () => this.setState({ hasError: false, error: null });

  render() {
    if (this.state.hasError) {
      // `fallback` may be an explicit `null` (decorative layers) — distinguish from undefined.
      if (this.props.fallback !== undefined) return this.props.fallback;
      return <ErrorFallback onReset={this.reset} />;
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
