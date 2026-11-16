import React, { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught an unhandled error:", error, errorInfo);
  }

  private handleRecover = () => {
    this.setState({ hasError: false, error: null });
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center p-8 m-4 rounded-xl border border-red-500/30 bg-red-950/20 text-center">
          <div className="w-14 h-14 rounded-full bg-red-900/40 border border-red-500/40 flex items-center justify-center mb-4 text-red-400">
            <AlertTriangle className="w-7 h-7" />
          </div>
          <h2 className="text-xl font-bold text-white mb-2">View Render Failure</h2>
          <p className="text-slate-400 max-w-md text-sm mb-4">
            An unexpected error occurred rendering this component. Defensive state guards have isolated the fault.
          </p>
          {this.state.error && (
            <div className="bg-slate-900/90 text-red-300 font-mono text-xs p-3 rounded border border-red-500/20 max-w-xl text-left overflow-x-auto mb-6">
              {this.state.error.message}
            </div>
          )}
          <button
            onClick={this.handleRecover}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-semibold transition"
          >
            <RefreshCw className="w-4 h-4" />
            Recover View
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

