# Mini-C Language Specification (Phase 1)

## Purpose and boundaries

Mini-C is a teaching language for an AI-assisted compiler front-end. It deliberately
supports a useful subset of C while excluding pointers, structs, unions, enums,
typedefs, macros, preprocessing, `goto`, function pointers, dynamic memory, and full
standard-library or ISO C compatibility. Phase 1 defines and tokenizes the complete
planned language surface; parsing and semantics begin in later phases.

The deterministic compiler remains authoritative. Misspellings such as `innt` and
`retrun` are identifiers at this stage and are never silently corrected by the lexer.

## Lexical conventions

- Source is Unicode text. Identifiers begin with an ASCII letter or underscore and
  continue with word characters.
- Spaces, tabs, form feeds, vertical tabs, and line endings separate tokens.
- `//` comments end at the next line ending. `/* ... */` comments may span lines.
  Comments do not become tokens, but their newlines contribute to source positions.
- Locations use one-based lines and columns and zero-based absolute offsets. Token
  spans are half-open.
- Keywords are case-sensitive.

## Keywords

| Group | Lexemes |
|---|---|
| Types | `int`, `float`, `char`, `bool`, `void` |
| Selection | `if`, `else` |
| Iteration | `while`, `for` |
| Control | `break`, `continue`, `return` |
| Boolean literals | `true`, `false` |

## Literals

- Integer: one or more decimal digits, such as `0` or `123`.
- Float: a decimal point or exponent is required, such as `3.14`, `2.`, `.5`, or
  `1e-3`.
- Character: exactly one unescaped character or one escape sequence in single
  quotes, such as `'A'` or `'\n'`.
- String: zero or more non-newline characters or escape sequences in double quotes,
  such as `"hello"`.
- Boolean: `true` and `false`.

Literal token values are converted to Python `int`, `float`, `str`, and `bool`
values while their exact source lexemes remain available.

## Operators and delimiters

- Arithmetic: `+`, `-`, `*`, `/`, `%`
- Assignment: `=`, `+=`, `-=`, `*=`, `/=`, `%=`
- Increment/decrement: `++`, `--`
- Relational/equality: `<`, `>`, `<=`, `>=`, `==`, `!=`
- Logical: `&&`, `||`, `!`
- Delimiters: `;`, `,`, `(`, `)`, `{`, `}`, `[`, `]`

Longest-match rules ensure compound operators are emitted as single tokens.
Precedence and associativity belong to the Phase 2 CFG rather than the lexer.

## Planned syntactic forms

The Phase 2 CFG will support scalar and one-dimensional array declarations,
assignments, prefix/postfix increment and decrement, expressions, nested blocks,
`if`/`else`, `while`, `for`, loop control, function definitions and calls,
parameters, and return statements. The AST and array representation will be designed
so multidimensional arrays can be added later.

## Lexical diagnostics

Lexical analysis continues whenever a safe boundary is known. Diagnostics are
structured records containing phase, stable error code, message, offending lexeme,
line, column, offset, and source span. Phase 1 recognizes illegal characters,
malformed numeric literals, malformed or unterminated character literals,
unterminated string literals, malformed string escape syntax where Python-compatible
decoding rejects it, and unterminated block comments.

## AI boundary

Phase 1 only defines serializable contextual records and predictor interfaces.
Future lexical validation may flag suspicious identifier tokens using their context,
but it must propose rather than silently apply a change. Every future correction is
re-tokenized and re-parsed before acceptance.

