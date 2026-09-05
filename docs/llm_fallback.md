# Groq LLM fallback (Phase 7)

Phase 7 adds one narrow fallback after the compiler and Logistic Regression model
have tried the normal Phase 6 path. Groq does not replace the lexer, parser,
traditional recovery, candidate ranker, or compiler validation.

## Flow

1. The compiler detects the error.
2. Traditional recovery produces candidates and ML ranks them.
3. A high-confidence compiler candidate that validates is used normally.
4. If ML confidence is below the fallback threshold, or no traditional candidate
   validates, Groq receives structured compiler context.
5. Groq proposes exactly one minimal `INSERT`, `DELETE`, or `REPLACE` edit.
6. The proposal becomes the existing `CorrectionCandidate` type.
7. `validate_candidate()` applies it temporarily, re-lexes, and re-parses.
8. The edit is accepted only when the targeted error is resolved without a local
   regression. Otherwise the original source remains unchanged.

The compiler remains the final authority.

## Configuration and secrets

`GroqFallbackService` loads `GROQ_API_KEY` from the environment or `.env` using
`python-dotenv`. The key is held privately by the client adapter and is never
printed, logged, placed in prompts, or included in result serialization. A missing
key produces an unavailable fallback record without disrupting normal compiler
behavior.

The single model is configured by `DEFAULT_GROQ_MODEL` in `ai/llm_fallback.py`.
The default is `llama-3.1-8b-instant`, with temperature `0.1` and a maximum of
`180` output tokens. The service constructor permits changing the model in one
place.

## Structured request

Groq receives only a JSON compiler-context object rather than an unstructured
“fix this code” request. It includes:

- Mini-C grammar context
- unexpected token and lexeme
- expected tokens
- previous, current, and next tokens
- nearby source and its absolute offset range
- delimiter depths
- traditional correction candidates
- ML class, confidence, and probabilities

The system instruction requests one minimal edit and no rewritten program.

## Structured response

The required JSON object has exactly five fields:

```json
{
  "action": "INSERT",
  "replacement_text": ")",
  "target_start": 42,
  "target_end": 42,
  "reason": "Missing closing parenthesis"
}
```

The parser rejects extra/missing fields, unsupported actions, invalid ranges,
non-empty delete text, non-zero-width inserts, empty delete/replace ranges, and
oversized replacement text. Source bounds are checked during candidate conversion.

Provider failures and malformed responses become clean rejected fallback results;
raw provider responses are not retained.

## History and CLI

Each relevant correction-history entry records whether fallback was available and
attempted, the model name, structured suggestion, converted candidate, compiler
validation, acceptance, and a sanitized error if one occurred.

The existing command enables fallback automatically:

```powershell
py main.py --correct examples\invalid\missing_semicolon.mc
```

Suggestion-only mode never calls or applies the fallback. Automated tests inject
fake services and clients, so the test suite makes no real API requests.

## Limitations

- Only one Groq request is allowed for an unresolved diagnostic.
- Only one minimal source edit is accepted per response.
- The service does not retry a malformed suggestion.
- The nearby snippet may not contain enough context for every unusual program.
- Network, authentication, quota, or model errors leave the source unchanged.
- Semantic errors are still reported separately after syntax becomes valid.
