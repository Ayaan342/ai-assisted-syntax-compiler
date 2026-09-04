# Phase 3 Syntax Error Recovery

## Compiler authority and scope

PLY Yacc and the Mini-C CFG remain the syntax authority. Phase 3 adds traditional
recovery, correction-candidate enumeration, delimiter awareness, and serializable
context. It does not rank candidates, assign confidence, silently modify user source,
or use an ML/LLM model.

Parser recovery and source correction are deliberately separate:

- A **recovery action** changes only the temporary token stream or Yacc recovery
  state so parsing can continue.
- A **correction candidate** describes a possible edit to the original source. It is
  not applied during normal parsing.

## Recovery strategy

The parser uses three bounded techniques.

### Local token insertion

When the current Yacc state explicitly accepts a high-confidence structural token,
the parser injects a zero-width synthetic token into its temporary stream and pushes
the unexpected real token back. Supported safe insertions are `;`, `(`, `)`, `]`,
and `}` in matching grammar contexts. This is phrase-level recovery; it does not edit
the source.

### Local token deletion or replacement

An immediately duplicated assignment operator can be discarded from the temporary
stream. A bracket used where a condition requires a parenthesis can be replaced in
the temporary stream. Both actions are recorded independently from their equivalent
source-edit candidates.

### Panic mode and Yacc `error` productions

If no safe local operation exists, the parser lets PLY shift its special `error`
symbol. Targeted productions synchronize at a boundary appropriate to the construct:

```text
statement           → error SEMICOLON
return-statement    → RETURN error SEMICOLON
block               → LBRACE error RBRACE
if-statement        → IF LPAREN error RPAREN statement [ ELSE statement ]
while-statement     → WHILE LPAREN error RPAREN statement
for-statement       → FOR LPAREN error RPAREN statement
function-definition → type IDENTIFIER LPAREN error RPAREN block
postfix-expression  → postfix-expression LPAREN error RPAREN
postfix-expression  → postfix-expression LBRACKET error RBRACKET
```

Thus malformed statements recover at `;` or `}`, conditions/headers/calls/parameter
lists at `)`, and array access at `]`. These productions are intentionally narrow so
they do not silently accept arbitrary malformed programs.

## Candidate generation

`CorrectionCandidate` supports:

- `INSERT`: a zero-width source span and insertion text;
- `DELETE`: the exact half-open span to remove;
- `REPLACE`: the exact span and replacement text.

Each candidate has a stable per-diagnostic ID, action, token type and lexeme, offset,
span, replacement text, reason, grammar context, originating diagnostic ID, origin
(`traditional_recovery`), and reserved `parser_validated` and `score` fields. Scores
remain unset in Phase 3.

Candidates are generated only when supported by parser expectations and local
structure. A missing condition `)` can reasonably yield insertion, deletion of the
unmatched `(`, and replacement of `{`; no fixed candidate count is imposed.

`apply_candidate` performs one offset-checked edit. `validate_candidate` applies one
candidate, re-lexes, and re-parses the result. Validation reports validity but never
selects a candidate.

## Delimiter awareness

`DelimiterTracker` maintains nesting depths for parentheses, braces, and brackets,
the opening-delimiter stack, mismatched closer records, and probable missing closers.
It provides a snapshot at an error offset for recovery and AI context. This utility
supplements rather than replaces CFG parsing.

## Cascading-error suppression

- Diagnostics are suppressed when the same original offset/parser-state pair repeats.
- Repeated EOF diagnostics at one offset collapse into one useful error even when
  several closing delimiters are missing.
- Recovery is capped independently at 75 attempts and 25 emitted diagnostics.
- Narrow synchronization productions discard a malformed construct only up to its
  natural boundary.
- The parser does not expose a recovered partial AST as a valid AST; valid sources
  retain exactly the Phase 2 AST behavior.

These measures prevent recovery loops and favor a small set of actionable errors.

## AI-ready context

`ErrorContext.from_diagnostic` produces a model-independent record containing:

- diagnostic ID, phase, message, line, column, and offset;
- unexpected token type/lexeme and the current token;
- previous and following token types, lexemes, and positions;
- Yacc expected-token set and parser state;
- grammar context and enclosing construct;
- delimiter depths;
- nearby source text and snippet offsets;
- recovery status, continuation flag, and recovery metadata;
- all traditional correction candidates.

The result is JSON serializable and suitable for later Scikit-learn/PyTorch features,
structured LLM prompts, API responses, and frontend visualization. Misspelled keywords
remain ordinary identifier tokens; their lexemes and surrounding context are retained.

