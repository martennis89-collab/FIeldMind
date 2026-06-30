import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

/**
 * Minimal error boundary. Catches render errors in its subtree and shows a
 * friendly recoverable card instead of a white screen. Logs the error to
 * console so it's still surfaced for debugging.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, errorMessage: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, errorMessage: error?.message || "Unknown error" };
  }

  componentDidCatch(error, info) {
    // Keep console visibility for testing/debugging
    console.error("ErrorBoundary caught:", error, info);
  }

  reset = () => this.setState({ hasError: false, errorMessage: null });

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div
        data-testid="error-boundary-fallback"
        className="rounded-md border p-6 my-6 text-center"
        style={{
          background: "var(--status-danger-bg)",
          borderColor: "var(--status-danger)",
        }}
      >
        <AlertTriangle
          className="w-8 h-8 mx-auto mb-2"
          style={{ color: "var(--status-danger)" }}
        />
        <div
          className="font-display text-lg font-medium mb-1"
          style={{ color: "var(--status-danger)" }}
        >
          Something went wrong while rendering this view.
        </div>
        <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
          {this.props.label || "We hit an unexpected error."} You can retry, or
          come back to it in a moment.
        </p>
        {this.state.errorMessage && (
          <div
            className="text-[11px] font-mono mb-4 px-3 py-2 rounded inline-block max-w-full overflow-auto"
            style={{ background: "var(--bg-paper)", color: "var(--text-muted)" }}
            data-testid="error-boundary-message"
          >
            {this.state.errorMessage}
          </div>
        )}
        <div>
          <button
            type="button"
            onClick={this.reset}
            data-testid="error-boundary-retry"
            className="text-sm px-4 py-2 rounded inline-flex items-center gap-2"
            style={{ background: "var(--brand-primary)", color: "white" }}
          >
            <RefreshCw className="w-4 h-4" /> Try again
          </button>
        </div>
      </div>
    );
  }
}
