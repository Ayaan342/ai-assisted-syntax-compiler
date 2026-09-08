import type {
  Candidate,
  CandidateEdit,
  CorrectionHistory,
  Diagnostic,
} from "../types/compiler";

const tokenText: Record<string, string> = {
  SEMICOLON: ";",
  COMMA: ",",
  LPAREN: "(",
  RPAREN: ")",
  LBRACKET: "[",
  RBRACKET: "]",
  LBRACE: "{",
  RBRACE: "}",
};

export function quoted(value: string | null | undefined) {
  return value ? JSON.stringify(value) : "the missing token";
}

export function displayToken(type: string | null | undefined) {
  if (!type) return null;
  return tokenText[type] ?? type.toLowerCase().replaceAll("_", " ");
}

export function diagnosticSummary(diagnostic: Diagnostic) {
  const insertion = diagnostic.correction_candidates?.find(
    (candidate) => candidate.action === "INSERT",
  );
  const expectedType =
    diagnostic.expected_tokens?.length === 1
      ? diagnostic.expected_tokens[0]
      : insertion?.token_type;
  const expected = displayToken(expectedType);
  const found = diagnostic.unexpected_lexeme;

  if (expected) return `Expected ${quoted(expected)}`;
  if (found) return `Unexpected ${quoted(found)}`;
  return diagnostic.message.split("; expected one of:")[0];
}

export function candidateEdits(candidate: Candidate): CandidateEdit[] {
  if (candidate.action === "COMPOUND") return candidate.edits;
  return [
    {
      action: candidate.action,
      token_type: candidate.token_type,
      token_lexeme: candidate.token_lexeme,
      offset: candidate.offset,
      span: candidate.span,
      text: candidate.text,
    },
  ];
}

export function describeEdit(edit: CandidateEdit) {
  if (edit.action === "INSERT") return `Insert ${quoted(edit.text)}`;
  if (edit.action === "DELETE") return `Delete ${quoted(edit.token_lexeme)}`;
  return `Replace ${quoted(edit.token_lexeme)} with ${quoted(edit.text)}`;
}

export function describeCandidate(candidate: Candidate | null) {
  if (!candidate) return "No candidate selected";
  if (candidate.action === "COMPOUND") return "Compound correction";
  return describeEdit(candidateEdits(candidate)[0]);
}

export function validatedAttempts(history: CorrectionHistory | undefined) {
  const attempts = history?.attempts ?? [];
  const seen = new Set<string>();
  return attempts.filter((attempt) => {
    const candidate = attempt.ranked_candidate.candidate;
    const valid = attempt.validation?.valid || attempt.validation?.relevant_valid;
    if (!valid || seen.has(candidate.id)) return false;
    seen.add(candidate.id);
    return true;
  });
}

export function safeProviderOutcome(error: string | null) {
  const value = error?.toLowerCase() ?? "";
  if (!value) return null;
  if (value.includes("semantic_content_invention") || value.includes("unsafe"))
    return "Suggestion rejected by safety policy";
  if (value.includes("confidence") || value.includes("threshold"))
    return "Confidence below threshold";
  if (value.includes("candidate") && value.includes("invalid"))
    return "Invalid candidate returned";
  if (value.includes("validation") || value.includes("parser"))
    return "Suggestion failed parser validation";
  if (value.includes("malformed") || value.includes("json"))
    return "Invalid response from AI provider";
  return "Provider unavailable";
}

export function unresolvedReason(
  stopReason: string,
  history: CorrectionHistory | undefined,
) {
  if (stopReason === "ambiguous_valid_candidates")
    return "Multiple compiler-valid repairs remain ambiguous.";
  if (stopReason === "no_safe_candidate") {
    const outcome = safeProviderOutcome(history?.llm_fallback?.error ?? null);
    return outcome === "Suggestion rejected by safety policy"
      ? "The AI suggestion was rejected because compiler evidence did not support it."
      : "No compiler-supported correction was found.";
  }
  if (history?.ambiguity_selection?.error)
    return "AI intent selection could not choose a validated candidate.";
  return "Remaining syntax errors prevent application.";
}

export function changedLinePairs(original: string, corrected: string) {
  const before = original.split("\n");
  const after = corrected.split("\n");
  const pairs: Array<{ line: number; before: string; after: string }> = [];
  const count = Math.max(before.length, after.length);

  for (let index = 0; index < count; index += 1) {
    if ((before[index] ?? "") !== (after[index] ?? "")) {
      pairs.push({
        line: index + 1,
        before: before[index] ?? "",
        after: after[index] ?? "",
      });
    }
  }
  return pairs;
}
