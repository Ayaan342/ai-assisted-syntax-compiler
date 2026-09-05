# Automatic correction (Phase 6)

Phase 6 connects the traditional compiler recovery candidates to the existing
Logistic Regression classifier. It does not add another model and does not call
an LLM.

## Pipeline

1. The compiler detects a syntax error.
2. Traditional recovery generates safe source-edit candidates.
3. `ErrorContext` describes the unexpected token, expected tokens, nearby
   tokens, grammar context, and delimiter depths.
4. The classifier predicts a correction class and its class probabilities.
5. Candidates are mapped to correction classes and ranked by the corresponding
   model probability.
6. A high-confidence candidate is applied to a temporary source string.
7. The lexer and parser validate the edit. A valid edit is accepted; otherwise,
   the next ranked candidate is tried.
8. The compiler is run again to find and correct the next independent error.

The compiler remains the final authority: model confidence alone never makes a
source edit valid.

## Explainable ranking

`ai/candidate_ranker.py` contains the centralized mapping from candidate action
and token structure to the nine trained classes. The numeric compatibility score
is exactly that class's probability from the classifier. Parser validation,
predicted-class equality, grammar-context equality, and original candidate order
are deterministic tie-breaks only; no artificial “AI score” is added.

Examples include `INSERT + RPAREN -> INSERT_RPAREN`, deletion of an extra token
to `DELETE_EXTRA_TOKEN`, parenthesis/bracket replacement to `REPLACE_BRACKET`,
and replacing `retrun` with `return` to `CORRECT_KEYWORD`.

## Confidence policy

The defaults are:

- auto-apply threshold: `0.80`
- future-LLM-fallback threshold: `0.60`
- maximum corrections: `10`
- maximum candidate attempts per diagnostic: `5`
- maximum repeated attempts at one diagnostic location: `2`

These confidence thresholds are initial, tunable engineering defaults, not
scientifically calibrated values. High confidence permits temporary application
and parser validation. Medium confidence returns a validated suggestion without
changing the result source. Low confidence stays unresolved and sets
`needs_llm_fallback`; Phase 6 does not invoke an LLM.

Use `CorrectionPolicy` in Python, or CLI options such as
`--auto-apply-threshold`, `--llm-fallback-threshold`, `--max-corrections`, and
`--max-candidate-attempts`.

## Relevant-error validation

`validate_candidate()` preserves `valid`, which means whole-program validity,
and adds `relevant_valid` for iterative correction. A local edit passes when the
target diagnostic disappears, lexical errors do not increase, and parsing does
not regress to an earlier source position. Therefore a missing semicolon can be
accepted even when a separate missing parenthesis remains later in the file.

Every accepted source must differ from all earlier source states. Correction,
candidate-attempt, and repeated-location limits provide additional loop safety.

## Suggested and applied corrections

Each history item has one explicit status:

- `APPLIED`: confidence permits automation and parser validation passed.
- `SUGGESTED`: a candidate validated, but confidence or suggestion-only mode
  prevents source mutation.
- `UNRESOLVED`: confidence is low, no safe candidate exists, or all candidates
  fail parser validation.

`CorrectionResult.to_dict()` serializes the original/corrected source, ordered
history, model predictions, candidate ranks and probabilities, validation
details, unresolved syntax diagnostics, policy, stop reason, and future fallback
flag for a later API/frontend.

## Keyword correction

The deterministic lexer is unchanged: `retrun` is still an `IDENTIFIER`.
Traditional recovery uses nearby identifiers, parser expectations, grammar
context, and edit distance to offer `REPLACE "retrun" WITH "return"`. The ML
model ranks it as `CORRECT_KEYWORD`, and the parser must validate the replacement
before it is accepted.

## Semantic boundary

After the corrected source is syntactically valid, the existing semantic analyzer
runs. Semantic diagnostics are returned separately and do not undo a successful
syntax correction. For example, an undeclared variable may remain after a valid
semicolon insertion.

## CLI

```powershell
py main.py --correct examples\invalid\broken_if.mc
py main.py --suggest-corrections examples\invalid\missing_semicolon.mc
py main.py --correct --auto-apply-threshold 0.30 --llm-fallback-threshold 0.20 examples\invalid\multiple_errors.mc
```

The final command demonstrates configurable thresholds with the current
synthetic model, whose confidence varies across source templates.
