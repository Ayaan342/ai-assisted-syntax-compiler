import { Check, Circle, Cpu, WarningCircle } from "@phosphor-icons/react";
import type {
  AnalysisResponse,
  CorrectionResponse,
  Diagnostic,
} from "../types/compiler";
export function AnalysisPanel({
  analysis,
  correction,
  selected,
}: {
  analysis: AnalysisResponse | null;
  correction: CorrectionResponse | null;
  selected: Diagnostic | null;
}) {
  const history = correction?.history[0];
  const diagnostic = selected ?? history?.original_error;
  return (
    <aside className="analysis-panel">
      <div className="panel-heading">
        <Cpu size={17} />
        <h2>Analysis & correction</h2>
      </div>
      <div className="pipeline-status">
        {(["lexical", "syntax", "semantic"] as const).map((phase) => (
          <div key={phase}>
            <span>{phase}</span>
            {analysis ? (
              phase === "semantic" && !analysis.semantic.ran ? (
                <span className="muted">Not run</span>
              ) : analysis[phase].success ? (
                <span className="accent">
                  <Check /> Passed
                </span>
              ) : (
                <span className="warning">
                  <WarningCircle /> Errors
                </span>
              )
            ) : (
              <span className="muted">
                <Circle /> Pending
              </span>
            )}
          </div>
        ))}
      </div>
      <section className="panel-section">
        <div className="section-label">COMPILER DIAGNOSTIC</div>
        {diagnostic ? (
          <>
            <h3 className="warning">
              {diagnostic.phase} error{" "}
              <small>
                Ln {diagnostic.line}:{diagnostic.column}
              </small>
            </h3>
            <code className="diagnostic-code">{diagnostic.code}</code>
            {diagnostic.unexpected_lexeme && (
              <div className="key-value">
                <span>Found</span>
                <code>{JSON.stringify(diagnostic.unexpected_lexeme)}</code>
              </div>
            )}
            <details className="message-detail">
              <summary>Full compiler message</summary>
              <p>{diagnostic.message}</p>
            </details>
          </>
        ) : (
          <p className="muted">
            {analysis?.success
              ? "Source passed all compiler checks."
              : "Analyze the source to inspect its first diagnostic."}
          </p>
        )}
      </section>
      <section className="panel-section">
        <div className="section-label">TRADITIONAL RECOVERY</div>
        {diagnostic?.correction_candidates?.length ? (
          diagnostic.correction_candidates.map((c) => (
            <div className="candidate" key={c.id}>
              <code>{c.action}</code>
              <strong>
                {c.text ? JSON.stringify(c.text) : c.token_lexeme}
              </strong>
              <small>{c.reason}</small>
            </div>
          ))
        ) : (
          <p className="muted">No compiler candidates to display.</p>
        )}
      </section>
      <section className="panel-section">
        <div className="section-label">ML PREDICTION</div>
        <strong className="prediction">
          {history?.prediction.label ?? "Awaiting correction"}
        </strong>
        <div className="key-value">
          <span>Model confidence</span>
          <code>
            {history
              ? `${(history.prediction.confidence * 100).toFixed(1)}%`
              : "Not run"}
          </code>
        </div>
        <div className="key-value">
          <span>Groq fallback</span>
          <span>
            {history?.llm_fallback
              ? !history.llm_fallback.available
                ? "Unavailable"
                : history.llm_fallback.attempted
                  ? "Used"
                  : "Not used"
              : "Not used"}
          </span>
        </div>
        <div className="key-value">
          <span>Parser validation</span>
          <span className={history?.validation?.relevant_valid ? "accent" : ""}>
            {history?.validation
              ? history.validation.relevant_valid
                ? "Passed"
                : "Failed"
              : history?.llm_fallback?.validation
                ? "Failed"
                : "Not run"}
          </span>
        </div>
      </section>
      <div className="panel-note">
        The model proposes. The compiler validates.
        <br />
        Review source changes before applying.
      </div>
    </aside>
  );
}
