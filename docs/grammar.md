# Mini-C Context-Free Grammar

This is the Phase 2 grammar implemented directly with PLY Yacc. `{ X }` means zero
or more repetitions, `[ X ]` means optional, and terminals are written as token
names. The actual implementation uses explicit empty and list productions.

## Program and functions

```text
program              → function-definition { function-definition }
function-definition  → type-specifier IDENTIFIER LPAREN parameter-list-opt RPAREN block
type-specifier       → INT | FLOAT | CHAR | BOOL | VOID
parameter-list-opt   → parameter-list | ε
parameter-list       → parameter { COMMA parameter }
parameter            → type-specifier IDENTIFIER
```

Only function definitions are supported at file scope. Function prototypes and
global variables are not part of the current subset.

## Blocks, declarations, and statements

```text
block                 → LBRACE statement-list-opt RBRACE
statement-list-opt    → { statement }
statement             → block
                      | declaration-statement
                      | expression-statement
                      | if-statement
                      | while-statement
                      | for-statement
                      | break-statement
                      | continue-statement
                      | return-statement

declaration-statement → declaration-core SEMICOLON
declaration-core      → type-specifier IDENTIFIER
                      | type-specifier IDENTIFIER ASSIGN expression
                      | type-specifier IDENTIFIER LBRACKET expression RBRACKET

expression-statement  → expression SEMICOLON | SEMICOLON
if-statement          → IF LPAREN expression RPAREN statement
                      | IF LPAREN expression RPAREN statement ELSE statement
while-statement       → WHILE LPAREN expression RPAREN statement
for-statement         → FOR LPAREN for-initializer SEMICOLON
                        optional-expression SEMICOLON optional-expression RPAREN statement
for-initializer       → declaration-core | expression | ε
optional-expression   → expression | ε
break-statement       → BREAK SEMICOLON
continue-statement    → CONTINUE SEMICOLON
return-statement      → RETURN optional-expression SEMICOLON
```

An `else` binds to the nearest unmatched `if`. Nested blocks and empty expression
statements are supported. Loop-context and return-type validation are semantic
checks deferred to Phase 4.

## Expressions

```text
expression             → assignment-expression
assignment-expression  → logical-or-expression
                       | unary-expression assignment-op assignment-expression
assignment-op          → ASSIGN | PLUS_ASSIGN | MINUS_ASSIGN
                       | TIMES_ASSIGN | DIVIDE_ASSIGN | MODULO_ASSIGN

logical-or-expression  → logical-and-expression
                       | logical-or-expression OR logical-and-expression
logical-and-expression → equality-expression
                       | logical-and-expression AND equality-expression
equality-expression    → relational-expression
                       | equality-expression (EQ | NE) relational-expression
relational-expression  → additive-expression
                       | relational-expression (LT | LE | GT | GE) additive-expression
additive-expression    → multiplicative-expression
                       | additive-expression (PLUS | MINUS) multiplicative-expression
multiplicative-expression
                       → unary-expression
                       | multiplicative-expression (TIMES | DIVIDE | MODULO) unary-expression

unary-expression       → postfix-expression
                       | (NOT | PLUS | MINUS | INCREMENT | DECREMENT) unary-expression
postfix-expression     → primary-expression
                       | postfix-expression LBRACKET expression RBRACKET
                       | postfix-expression LPAREN argument-list-opt RPAREN
                       | postfix-expression (INCREMENT | DECREMENT)
argument-list-opt      → argument-list | ε
argument-list          → assignment-expression { COMMA assignment-expression }
primary-expression     → IDENTIFIER
                       | INTEGER_LITERAL | FLOAT_LITERAL | CHAR_LITERAL
                       | STRING_LITERAL | TRUE | FALSE
                       | LPAREN expression RPAREN
```

Assignment targets are parsed syntactically as unary expressions. Determining
whether a target is assignable is intentionally left to semantic analysis.

## Precedence and associativity

From highest to lowest:

| Level | Operators/forms | Associativity |
|---:|---|---|
| 1 | calls, array access, postfix `++` and `--` | left |
| 2 | prefix `++`, `--`, `!`, unary `+`, unary `-` | right |
| 3 | `*`, `/`, `%` | left |
| 4 | `+`, `-` | left |
| 5 | `<`, `<=`, `>`, `>=` | left |
| 6 | `==`, `!=` | left |
| 7 | `&&` | left |
| 8 | `||` | left |
| 9 | `=`, `+=`, `-=`, `*=`, `/=`, `%=` | right |

PLY precedence declarations are present explicitly, while the layered expression
productions also make these relationships visible in the CFG.

## Unsupported in Phase 2

- pointers, address/dereference operators, structs, unions, enums, and typedefs
- preprocessor directives, macros, includes, and `goto`
- multidimensional declarations and array initializers
- comma and ternary expressions
- casts, `sizeof`, member access, bitwise operators, and C string concatenation
- function prototypes, variadic functions, and global declarations
- automatic correction selection or candidate ranking (recovery candidates are now
  generated by Phase 3)
- symbol tables and semantic/type validation (Phase 4)

Selected Yacc `error` productions and synchronization behavior are documented in
`error_recovery.md`.
