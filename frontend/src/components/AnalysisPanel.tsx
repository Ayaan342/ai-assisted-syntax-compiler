import {
  Check,
  Circle,
  Cpu,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import type {
  AnalysisResponse,
  Candidate,
  CorrectionHistory,
  CorrectionResponse,
  Diagnostic,
  Validation,
} from "../types/compiler";
import {
  candidateEdits,
  describeCandidate,
  describeEdit,
  diagnosticSummary,
  safeProviderOutcome,
  validatedAttempts,
} from "../utils/correctionPresentation";

function CandidateBreakdown({ candidate }: { candidate: Candidate }) {
  return (
    <div className="decision-candidate">
      <div>
        <strong>{describeCandidate(candidate)}</strong>
        <code>{candidate.id}</code>
      </div>
      {candidate.action === "COMPOUND" && (
        <span>{candidate.edits.length} coordinated edits</span>
      )}
      <ol>
        {candidateEdits(candidate).map((edit, index) => (
          <li key={`${edit.offset}-${index}`}>
            <span>{describeEdit(edit)}</span>
            <small>
              Ln {edit.span.start.line}:{edit.span.start.column}
            </small>
          </li>
        ))}
      </ol>
    </div>
  );
}

function finalValidation(history: CorrectionHistory | undefined) {
  return (
    history?.validation ??
    history?.ambiguity_selection?.validation ??
    history?.llm_fallback?.validation ??
    null
  );
}

function ValidationStage({
  validation,
  history,
}: {
  validation: Validation | null;
  history: CorrectionHistory | undefined;
}) {
  const passed = validation?.relevant_valid === true;
  return (
    <div className="decision-stage">
      <div className="decision-stage-heading">
        <strong>Final compiler validation</strong>
        <span className={passed ? "stage-result accent" : "stage-result muted"}>
          {validation ? (passed ? "Passed" : "Failed") : "Not run"}
        </span>
      </div>
      <p>
        {validation
          ? passed
            ? "The selected edit was re-lexed and re-parsed successfully."
            : "The selected edit did not pass compiler validation."
          : history
            ? "No candidate was selected, so final validation was not applicable."
            : "Run Correct to validate a compiler-supported edit."}
      </p>
    </div>
  );
}

export function AnalysisPanel({
  analysis,
  correction,
  selected,
}: {
  analysis: AnalysisResponse | null;
  correction: CorrectionResponse | null;
  selected: Diagnostic | null;
}) {
  const history =
    correction?.history.find(
      (item) => item.diagnostic_id === selected?.diagnostic_id,
    ) ?? correction?.history[0];
  const diagnostic = selected ?? history?.original_error;
  const attempts = validatedAttempts(history);
  const candidatePool = attempts.map(
    (attempt) => attempt.ranked_candidate.candidate,
  );
  if (
    history?.selected_candidate &&
    !candidatePool.some(
      (candidate) => candidate.id === history.selected_candidate?.id,
    )
  ) {
    candidatePool.push(history.selected_candidate);
  }
  const displayedCandidates = history
    ? candidatePool
    : diagnostic?.correction_candidates ?? [];
  const validation = finalValidation(history);
  const selectedCandidate = history?.selected_candidate ?? null;
  const correctionReady =
    !!correction &&
    correction.corrections_applied > 0 &&
    correction.fully_syntactically_valid &&
    validation?.relevant_valid === true;

  const ambiguity = history?.ambiguity_selection;
  const fallback = history?.llm_fallback;
  const aiLabel = ambiguity ? "AI intent selection" : "AI structural fallback";
  const aiOutcome = ambiguity
    ? !ambiguity.available
      ? "Unavailable"
      : ambiguity.accepted
        ? "Selected"
        : safeProviderOutcome(ambiguity.error) ?? "Uncertain"
    : fallback
      ? !fallback.available
        ? "Unavailable"
        : fallback.accepted
          ? "Accepted"
          : safeProviderOutcome(fallback.error) ?? "Rejected"
      : null;

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

      <section className="panel-section decision-section">
        <div className="section-label">CORRECTION DECISION</div>

        <div className="decision-stage">
          <div className="decision-stage-heading">
            <strong>Compiler evidence</strong>
            <span className="stage-result">
              {history
                ? `${displayedCandidates.length} valid candidate${displayedCandidates.length === 1 ? "" : "s"}`
                : `${displayedCandidates.length} candidate${displayedCandidates.length === 1 ? "" : "s"}`}
            </span>
          </div>
          {diagnostic ? (
            <>
              <div className="diagnostic-summary">
                <strong className="warning">{diagnosticSummary(diagnostic)}</strong>
                {diagnostic.unexpected_lexeme && (
                  <span>
                    Found <code>{JSON.stringify(diagnostic.unexpected_lexeme)}</code>
                  </span>
                )}
                <small>
                  {diagnostic.code} · Ln {diagnostic.line}:{diagnostic.column} ·{" "}
                  {diagnostic.phase}
                </small>
              </div>
              <details className="message-detail">
                <summary>Technical compiler detail</summary>
                <p>{diagnostic.message}</p>
              </details>
            </>
          ) : (
            <p>
              {analysis?.success
                ? "Source passed all compiler checks."
                : "Analyze the source to collect compiler evidence."}
            </p>
          )}
          {displayedCandidates.length > 0 && (
            <div className="candidate-pool">
              {displayedCandidates.map((candidate) => (
                <div
                  className={`candidate-option ${selectedCandidate?.id === candidate.id ? "selected" : ""}`}
                  key={candidate.id}
                >
                  <span>{describeCandidate(candidate)}</span>
                  <code>{candidate.id}</code>
                  {candidate.action === "COMPOUND" && (
                    <small>{candidate.edits.length} coordinated edits</small>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="decision-stage">
          <div className="decision-stage-heading">
            <strong>ML ranking</strong>
            <span className="stage-result">
              {history
                ? ambiguity || fallback
                  ? "Inconclusive"
                  : selectedCandidate
                    ? "Candidate selected"
                    : "No selection"
                : "Not run"}
            </span>
          </div>
          {history ? (
            <div className="decision-values">
              <code>{history.prediction.label}</code>
              <span>{(history.prediction.confidence * 100).toFixed(1)}%</span>
            </div>
          ) : (
            <p>Run Correct to rank compiler-generated candidates.</p>
          )}
        </div>

        {aiOutcome && (
          <div className="decision-stage">
            <div className="decision-stage-heading">
              <strong>{aiLabel}</strong>
              <span
                className={`stage-result ${ambiguity?.accepted || fallback?.accepted ? "accent" : "warning"}`}
              >
                {aiOutcome}
              </span>
            </div>
            {ambiguity?.confidence != null && (
              <div className="decision-values">
                <span>Selection confidence</span>
                <code>{(ambiguity.confidence * 100).toFixed(1)}%</code>
              </div>
            )}
            <p>
              {ambiguity?.reason ??
                (fallback?.accepted ? fallback.suggestion?.reason : null) ??
                (aiOutcome === "Provider unavailable"
                  ? "The provider could not complete this selection."
                  : aiOutcome === "Suggestion rejected by safety policy"
                    ? "Compiler evidence did not support the proposed edit."
                    : "No reliable AI selection was accepted.")}
            </p>
          </div>
        )}

        <ValidationStage validation={validation} history={history} />

        <div className="decision-stage final-result">
          <div className="decision-stage-heading">
            <strong>Final result</strong>
            <span className={`stage-result ${correctionReady ? "accent" : "muted"}`}>
              {correctionReady ? "Ready to apply" : "No correction ready"}
            </span>
          </div>
          {selectedCandidate ? (
            <CandidateBreakdown candidate={selectedCandidate} />
          ) : (
            <p>
              {history
                ? "The original source remains unchanged."
                : "No correction decision has been requested."}
            </p>
          )}
        </div>
      </section>

      <div className="panel-note">
        <ShieldCheck size={14} />
        <span>
          Compiler validation is authoritative. ML and AI only rank or select
          supported repairs.
        </span>
      </div>
    </aside>
  );
}
