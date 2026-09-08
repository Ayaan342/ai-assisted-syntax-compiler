import {
  BracketsCurly,
  Play,
  ArrowCounterClockwise,
  Wrench,
  ArrowClockwise,
} from "@phosphor-icons/react";
import type { AnalysisResponse, Health } from "../types/compiler";
export function Toolbar({
  health,
  analysis,
  checking,
  busy,
  onAnalyze,
  onCorrect,
  onReset,
  onRetry,
}: {
  health: Health | null;
  analysis: AnalysisResponse | null;
  checking: boolean;
  busy: string | null;
  onAnalyze: () => void;
  onCorrect: () => void;
  onReset: () => void;
  onRetry: () => void;
}) {
  const hasSyntaxErrors = !!analysis && !analysis.syntax.success;
  const semanticOnly =
    !!analysis &&
    analysis.syntax.success &&
    analysis.semantic.ran &&
    analysis.semantic.success === false;
  const sourceIsValid = analysis?.success === true;
  const correctDisabled = !!busy || semanticOnly || sourceIsValid;
  const correctTitle = semanticOnly
    ? "Semantic errors require manual code changes"
    : sourceIsValid
      ? "No syntax correction is needed"
      : "Prepare compiler-validated corrections";
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
      </div>
      <nav className="toolbar-actions" aria-label="Compiler actions">
        <button onClick={onReset} title="Restore default source">
          <ArrowCounterClockwise />
          Reset
        </button>
        <button
          className={!analysis ? "primary" : ""}
          disabled={!!busy}
          onClick={onAnalyze}
        >
          <Play weight="fill" />
          {busy === "analyze" ? "Analyzing…" : "Analyze"}
        </button>
        <button
          className={hasSyntaxErrors ? "primary" : ""}
          disabled={correctDisabled}
          title={correctTitle}
          onClick={onCorrect}
        >
          <Wrench />
          {busy === "correct" ? "Correcting…" : "Correct"}
        </button>
      </nav>
    </header>
  );
}
