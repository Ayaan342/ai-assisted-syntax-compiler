import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { CodeEditor } from "./CodeEditor";
import type { CorrectionHistory, CorrectionResponse } from "../types/compiler";
import {
  candidateEdits,
  changedLinePairs,
  describeCandidate,
  describeEdit,
  unresolvedReason,
} from "../utils/correctionPresentation";

export function canApplyCorrection(result: CorrectionResponse) {
  return (
    result.original_code !== result.corrected_code &&
    result.corrections_applied > 0 &&
    result.fully_syntactically_valid &&
    result.history.some(
      (item) => item.status === "APPLIED" && item.validation?.relevant_valid,
    )
  );
}

function SelectionMeta({ history }: { history: CorrectionHistory }) {
  if (history.ambiguity_selection?.attempted) {
    return (
      <span>
        AI intent selection
        {history.ambiguity_selection.confidence == null
          ? ""
          : ` ${(history.ambiguity_selection.confidence * 100).toFixed(1)}%`}
      </span>
    );
  }
  if (history.llm_fallback?.attempted)
    return <span>AI structural fallback</span>;
  return <span>ML {(history.prediction.confidence * 100).toFixed(1)}%</span>;
}

function EditList({ history }: { history: CorrectionHistory }) {
  const candidate = history.selected_candidate;
  if (!candidate) return null;
  return (
    <ol className="atomic-edits">
      {candidateEdits(candidate).map((edit, index) => (
        <li key={`${edit.offset}-${index}`}>
          <span>{describeEdit(edit)}</span>
          <small>
            Ln {edit.span.start.line}:{edit.span.start.column}
          </small>
        </li>
      ))}
    </ol>
  );
}

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
        <span>Run Correct to review exact edits from the backend.</span>
      </div>
    );

  const canApply = canApplyCorrection(result);
  const firstHistory = result.history[0];
  const applied = result.history.filter(
    (history) => history.status === "APPLIED" && history.selected_candidate,
  );
  const diff = changedLinePairs(result.original_code, result.corrected_code);
  const disabledReason = unresolvedReason(result.stop_reason, firstHistory);

  return (
    <div className="correction-panel">
      <div className="review-header">
        <div>
          <strong>
            {canApply
              ? `${result.corrections_applied} validated correction${result.corrections_applied === 1 ? "" : "s"} ready`
              : "No validated correction is ready"}
          </strong>
          <span id="apply-explanation">
            {canApply
              ? "Review the exact change below. The editor remains unchanged."
              : `${disabledReason} The original source remains unchanged.`}
          </span>
        </div>
        <button
          className={canApply ? "primary" : ""}
          disabled={!canApply}
          aria-describedby="apply-explanation"
          onClick={onApply}
        >
          Apply Corrected Code
        </button>
      </div>

      {applied.length > 0 && (
        <section className="prepared-changes" aria-label="Prepared changes">
          {applied.map((history) => (
            <article key={history.sequence}>
              <div>
                <span>Correction {history.sequence}</span>
                <strong>{describeCandidate(history.selected_candidate)}</strong>
              </div>
              {history.selected_candidate?.action === "COMPOUND" && (
                <span>
                  {history.selected_candidate.edits.length} coordinated edits
                </span>
              )}
              <EditList history={history} />
            </article>
          ))}
        </section>
      )}

      {diff.length > 0 && (
        <div className="inline-diff" aria-label="Changed source lines">
          {diff.map((pair) => (
            <div className="diff-pair" key={pair.line}>
              <code className="diff-before">
                <span>-</span>
                {pair.before || " "}
              </code>
              <code className="diff-after">
                <span>+</span>
                {pair.after || " "}
              </code>
            </div>
          ))}
        </div>
      )}

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

      <section className="history" aria-label="Correction history">
        <div className="history-heading">Correction history</div>
        {result.history.map((history) => {
          const validated =
            history.status === "APPLIED" &&
            history.validation?.relevant_valid === true;
          return (
            <article key={history.sequence}>
              <div className="history-step">Correction {history.sequence}</div>
              <div className="history-title">
                <strong>{describeCandidate(history.selected_candidate)}</strong>
                <span className={validated ? "accent" : "warning"}>
                  {validated ? (
                    <>
                      <CheckCircle /> Validated
                    </>
                  ) : (
                    <>
                      <WarningCircle /> Unresolved
                    </>
                  )}
                </span>
              </div>
              <EditList history={history} />
              <div className="history-meta">
                <span>
                  Ln {history.original_error.line}:{history.original_error.column}
                </span>
                <SelectionMeta history={history} />
                {history.selected_candidate && (
                  <code>{history.selected_candidate.id}</code>
                )}
              </div>
            </article>
          );
        })}
      </section>

    </div>
  );
}
