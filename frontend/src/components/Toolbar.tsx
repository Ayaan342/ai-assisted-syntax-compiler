import {
  BracketsCurly,
  Play,
  ArrowCounterClockwise,
  Wrench,
  ArrowClockwise,
} from "@phosphor-icons/react";
import type { Health } from "../types/compiler";
export function Toolbar({
  health,
  checking,
  busy,
  onAnalyze,
  onCorrect,
  onReset,
  onRetry,
}: {
  health: Health | null;
  checking: boolean;
  busy: string | null;
  onAnalyze: () => void;
  onCorrect: () => void;
  onReset: () => void;
  onRetry: () => void;
}) {
  return (
    <header className="toolbar">
      <div className="brand">
        <BracketsCurly size={27} weight="bold" />
        <div>
          <h1>
            Mini-C<span> / Compiler Workbench</span>
          </h1>
          <p>AI-assisted syntax detection & correction</p>
        </div>
      </div>
      <div className="connections">
        <button
          onClick={onRetry}
          title="Refresh backend status"
          className="connection"
        >
          <span className={`status-dot ${health ? "connected" : ""}`} />
          {checking
            ? "Connecting"
            : health
              ? "Backend connected"
              : "Backend offline"}
          <ArrowClockwise size={12} />
        </button>
        <span>
          ML{" "}
          <b>
            {health
              ? health.ml_model_loaded
                ? "ready"
                : "unavailable"
              : "unknown"}
          </b>
        </span>
        <span>
          Groq{" "}
          <b>
            {health
              ? health.groq_configured
                ? "configured"
                : "unavailable"
              : "unknown"}
          </b>
        </span>
      </div>
      <nav className="toolbar-actions" aria-label="Compiler actions">
        <button onClick={onReset} title="Restore default source">
          <ArrowCounterClockwise />
          Reset
        </button>
        <button disabled={!!busy} onClick={onAnalyze}>
          <Play weight="fill" />
          {busy === "analyze" ? "Analyzing…" : "Analyze"}
        </button>
        <button className="primary" disabled={!!busy} onClick={onCorrect}>
          <Wrench />
          {busy === "correct" ? "Correcting…" : "Correct"}
        </button>
      </nav>
    </header>
  );
}
