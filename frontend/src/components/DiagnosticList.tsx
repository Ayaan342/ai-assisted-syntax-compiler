import { WarningCircle, CheckCircle } from "@phosphor-icons/react";
import type { Diagnostic, Phase } from "../types/compiler";
import { diagnosticSummary } from "../utils/correctionPresentation";
export function DiagnosticList({
  diagnostics,
  onSelect,
  analyzed,
}: {
  diagnostics: Diagnostic[];
  onSelect: (d: Diagnostic) => void;
  analyzed: boolean;
}) {
  if (!diagnostics.length)
    return (
      <div className="empty">
        <CheckCircle size={26} />
        <strong>
          {analyzed ? "No diagnostics in this result" : "Ready when you are"}
        </strong>
        <span>
          {analyzed
            ? "The backend reported no errors."
            : "Analyze your source to inspect compiler diagnostics."}
        </span>
      </div>
    );
  return (
    <div className="diagnostic-list">
      {(["lexical", "syntax", "semantic"] as Phase[]).map((phase) => {
        const group = diagnostics.filter((d) => d.phase === phase);
        return (
          group.length > 0 && (
            <section key={phase}>
              <h3>
                {phase.toUpperCase()} <span>{group.length}</span>
              </h3>
              {group.map((d, i) => (
                <article className="diagnostic-item" key={`${d.code}-${i}`}>
                  <button
                    className="diagnostic-row"
                    onClick={() => onSelect(d)}
                  >
                    <WarningCircle size={18} />
                    <span>
                      <strong>{diagnosticSummary(d)}</strong>
                      <span>
                        {d.code} · {d.phase}
                      </span>
                    </span>
                    <code>
                      Ln {d.line}:{d.column}
                    </code>
                  </button>
                  <details className="diagnostic-detail">
                    <summary>Technical compiler detail</summary>
                    <p>{d.message}</p>
                  </details>
                </article>
              ))}
            </section>
          )
        );
      })}
    </div>
  );
}
