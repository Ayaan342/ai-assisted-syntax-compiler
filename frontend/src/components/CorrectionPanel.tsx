import { CodeEditor } from "./CodeEditor";
import type { CorrectionResponse } from "../types/compiler";
export function CorrectionPanel({
  result,
  onApply,
}: {
  result: CorrectionResponse | null;
  onApply: () => void;
}) {
  if (!result)
    return (
      <div className="empty">
        <strong>Review before you apply</strong>
        <span>
          Run Correct to review backend-proposed edits and validation.
        </span>
      </div>
    );
  const changed = result.original_code !== result.corrected_code;
  return (
    <div className="correction-panel">
      <div className="review-header">
        <div>
          <strong>
            {result.corrections_applied} correction
            {result.corrections_applied === 1 ? "" : "s"} prepared
          </strong>
          <span>
            {result.fully_syntactically_valid
              ? "Corrected source is syntax-valid"
              : "Unresolved errors remain"}{" "}
            · Editor unchanged
          </span>
        </div>
        <button className="primary" disabled={!changed} onClick={onApply}>
          Apply Corrected Code
        </button>
      </div>
      <div className="review-code">
        <CodeEditor
          code={result.corrected_code}
          diagnostics={[
            ...result.unresolved_syntax_diagnostics,
            ...result.semantic_diagnostics,
          ]}
          readOnly
        />
      </div>
      <div className="history">
        {result.history.map((h) => (
          <article key={h.sequence}>
            <div className="history-title">
              <strong>
                {h.selected_candidate?.action ?? "UNRESOLVED"}{" "}
                <code>
                  {h.selected_candidate?.text
                    ? JSON.stringify(h.selected_candidate.text)
                    : h.selected_candidate?.token_lexeme}
                </code>
              </strong>
              <span
                className={h.validation?.relevant_valid ? "accent" : "warning"}
              >
                {h.status === "APPLIED"
                  ? "Prepared for review"
                  : h.status.toLowerCase()}
              </span>
            </div>
            <p>{h.original_error.message}</p>
            <div className="history-meta">
              <span>
                Ln {h.original_error.line}:{h.original_error.column}
              </span>
              <span>{h.prediction.label}</span>
              <span>{(h.prediction.confidence * 100).toFixed(1)}% ML</span>
              <span>
                Groq {h.llm_fallback?.attempted ? "used" : "not used"}
              </span>
              <span>
                Validation{" "}
                {h.validation
                  ? h.validation.relevant_valid
                    ? "passed"
                    : "failed"
                  : h.llm_fallback?.validation
                    ? "failed"
                    : "not run"}
              </span>
            </div>
          </article>
        ))}
      </div>
      {result.unresolved_syntax_diagnostics.length > 0 && (
        <div className="review-warning">
          {result.unresolved_syntax_diagnostics.length} unresolved syntax
          diagnostic(s). Applying retains these errors.
        </div>
      )}
    </div>
  );
}
