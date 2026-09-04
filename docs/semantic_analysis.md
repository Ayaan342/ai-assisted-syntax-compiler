# Phase 4 Symbol Table and Semantic Analysis

## Pipeline boundary

Semantic analysis consumes only a syntactically valid `Program` AST. If lexical or
syntax diagnostics exist, `analyze_source_semantics` returns no semantic result. It
does not participate in syntax recovery and never proposes automatic corrections.

## Symbols and scopes

The symbol table is a tree rooted at `GLOBAL`. Supported symbol kinds are:

- `function`: return type and ordered parameter types;
- `variable`: scalar declared type;
- `array`: element type and optional constant size metadata;
- `parameter`: scalar parameter type.

Scopes have deterministic IDs, a kind, parent, children, declarations, and an
optional source span. Scope kinds are `global`, `function`, `block`, and `loop`.
Lookup searches the current scope and then each parent up to global scope.

Declarations in child scopes do not leak outward. Shadowing an enclosing declaration
is allowed. Reusing any name in the same scope is rejected regardless of symbol kind.
The outermost function body shares the function scope; nested compound statements
create block scopes. A `for` statement creates a loop scope so its initializer
variable is not visible after the loop.

Semantic analysis uses two passes:

1. Register all global function signatures and global declarations.
2. Check global values and then analyze function parameters and bodies.

This permits calls to functions defined later in the source.

## Type model

Declared scalar types are `int`, `float`, `char`, `bool`, and `void`. The internal
model additionally represents arrays, functions, string literals, and an error type
used to suppress cascades.

Rules are intentionally stricter than C:

- `int` and `float` are numeric. `char` and `bool` are not numeric.
- Mixed `int`/`float` arithmetic produces `float`; integer arithmetic produces `int`.
- The only implicit conversion is widening from `int` to `float`.
- `float` to `int`, numeric to `bool`, and unrelated-type assignments are rejected.
- `<`, `<=`, `>`, and `>=` require numeric operands and produce `bool`.
- `==` and `!=` accept equal scalar types or mixed numeric types and produce `bool`.
- `&&`, `||`, and `!` require strict `bool` operands.
- `if`, `while`, and non-empty `for` conditions require `bool`; integer truthiness is
  not supported.
- Variables, arrays, and parameters cannot have type `void`.

## Assignments and updates

Simple assignment uses the compatibility rules above. Compound assignment requires
numeric operands and its computed result must remain assignable to the target, so an
`int += float` narrowing operation is rejected.

Prefix and postfix updates require an assignable identifier or array element with
type `int` or `float`. Literals, compound expressions, Boolean values, arrays, and
functions are not valid update targets.

## Functions and returns

A call target must resolve to a function. Argument count and each argument type are
checked against the registered signature; `int` arguments may widen to `float`.

`return;` is valid only in a `void` function. A value is required in non-void
functions and must be assignment-compatible with the declared return type. Phase 4
does not yet prove that every control-flow path returns.

## Arrays

Array access requires an array symbol and an `int` index. Arrays cannot be used as
ordinary scalar values. Array assignment works through an indexed element. Array
sizes must have type `int`; bounds evaluation is intentionally deferred.

## Loop control

The traversal tracks loop depth. `break` and `continue` are accepted inside `while`
and `for`, including nested blocks, and rejected elsewhere.

## Diagnostics

Semantic diagnostics are separate from lexical and syntax diagnostics. Each contains
phase, code, severity, message, identifier where applicable, expected/actual types,
scope ID, line, column, absolute offset, and source span.

Implemented codes include:

- `SEM-UNDECLARED-IDENTIFIER`
- `SEM-DUPLICATE-DECLARATION`
- `SEM-TYPE-MISMATCH`
- `SEM-INVALID-ASSIGNMENT`
- `SEM-FUNCTION-ARG-COUNT`
- `SEM-FUNCTION-ARG-TYPE`
- `SEM-NOT-CALLABLE`
- `SEM-INVALID-RETURN`
- `SEM-INVALID-ARRAY-USE`
- `SEM-INVALID-ARRAY-INDEX`
- `SEM-BREAK-OUTSIDE-LOOP`
- `SEM-CONTINUE-OUTSIDE-LOOP`
- `SEM-VOID-VALUE-USE`

The optional AI-facing `SemanticContext` serializes a diagnostic together with its
scope, visible identifiers, and expected/actual types. No model or AI behavior is
implemented in this phase; the central AI-assisted correction path remains focused
on lexical/syntax recovery context.

