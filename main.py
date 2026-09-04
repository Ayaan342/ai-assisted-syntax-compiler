"""Command-line token and AST demo for Mini-C."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compiler.ast_nodes import pretty_ast
from compiler.lexer import tokenize
from compiler.parser import parse
from compiler.semantic_analyzer import analyze_source_semantics
from compiler.symbol_table import pretty_symbol_table
from ai.error_context import build_error_contexts


def format_value(value: object) -> str:
    rendered = repr(value)
    return rendered if len(rendered) <= 34 else rendered[:31] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Mini-C source using PLY Lex/Yacc")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--tokens", action="store_true", help="print the PLY Lex token stream")
    mode.add_argument("--ast", action="store_true", help="parse and print the AST")
    mode.add_argument("--errors", action="store_true", help="show syntax recovery analysis")
    mode.add_argument("--error-context", action="store_true", help="print AI-ready error context as JSON")
    mode.add_argument("--symbols", action="store_true", help="print the scoped symbol table")
    mode.add_argument("--semantic-errors", action="store_true", help="show semantic diagnostics")
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=Path("examples/valid/demo.mc"),
        help="Mini-C source file (default: examples/valid/demo.mc)",
    )
    args = parser.parse_args()

    try:
        source = args.source.read_text(encoding="utf-8")
    except OSError as exc:
        parser.error(str(exc))

    if args.symbols or args.semantic_errors:
        analysis = analyze_source_semantics(source)
        print(f"Source: {args.source}")
        if analysis.semantic_result is None:
            print("Semantic analysis skipped because lexical or syntax errors are present.")
            return 1
        if args.symbols:
            print("\nSYMBOL TABLE")
            print("------------")
            print(pretty_symbol_table(analysis.semantic_result.symbol_table))
        else:
            diagnostics = analysis.semantic_result.diagnostics
            print(f"Semantic errors: {len(diagnostics)}")
            for index, error in enumerate(diagnostics, start=1):
                print(f"\nSemantic Error {index}: {error.code}")
                print("-" * 40)
                print(f"Location: {error.line}:{error.column} @{error.span.start.offset}")
                print(f"Identifier: {error.identifier or '(none)'}")
                print(f"Scope: {error.scope_id or '(none)'}")
                print(f"Message: {error.message}")
                if error.expected_type is not None:
                    print(f"Expected: {error.expected_type}")
                if error.actual_type is not None:
                    print(f"Actual: {error.actual_type}")
        return 0 if analysis.success else 1

    if args.ast or args.errors or args.error_context:
        result = parse(source)
        print(f"Source: {args.source}")
        if result.lexical_errors:
            print(f"Lexical errors: {len(result.lexical_errors)}")
            for error in result.lexical_errors:
                print(f"  {error.code} at {error.line}:{error.column}: {error.message}")
        if result.syntax_errors and args.ast:
            print(f"Syntax errors: {len(result.syntax_errors)}")
            for error in result.syntax_errors:
                print(f"  {error.code} at {error.line}:{error.column}: {error.message}")
        if args.errors:
            if not result.syntax_errors:
                print("Syntax errors: 0")
            for index, error in enumerate(result.syntax_errors, start=1):
                print(f"\nSyntax Error {index} ({error.diagnostic_id})")
                print("-" * 32)
                print(f"Location: {error.line}:{error.column} @{error.span.start.offset}")
                print(f"Context: {error.grammar_context or 'unknown'}")
                print(f"Unexpected: {error.unexpected_token or 'EOF'} {error.unexpected_lexeme or ''}".rstrip())
                print("Expected: " + (", ".join(error.expected_tokens) or "unknown"))
                print(f"Message: {error.message}")
                print(f"Recovery: {error.recovery_status}; continued={error.parsing_continued}")
                print("Correction candidates:")
                if not error.correction_candidates:
                    print("  (no safe structural source edit generated)")
                for candidate_index, candidate in enumerate(error.correction_candidates, start=1):
                    print(
                        f"  {candidate_index}. {candidate.action.value} "
                        f"{candidate.token_type or ''} {candidate.text!r} at offset {candidate.offset}"
                    )
        if args.error_context:
            contexts = build_error_contexts(source, result)
            print(json.dumps([context.to_dict() for context in contexts], indent=2))
        if args.ast and result.ast is not None:
            print("\nAST")
            print("---")
            print(pretty_ast(result.ast))
        return 0 if result.valid else 1

    tokens, errors = tokenize(source)
    print(f"Source: {args.source}")
    print(f"{'TYPE':<20} {'LEXEME':<18} {'VALUE':<34} LOCATION")
    print("-" * 90)
    for token in tokens:
        lexeme = repr(token.lexeme)
        print(
            f"{token.type:<20} {lexeme:<18} {format_value(token.value):<34} "
            f"{token.line}:{token.column} @{token.offset}"
        )

    print(f"\nTokens: {len(tokens)}")
    if errors:
        print(f"Lexical errors: {len(errors)}")
        for error in errors:
            print(
                f"  {error.code} at {error.line}:{error.column}: "
                f"{error.message} (lexeme={error.lexeme!r})"
            )
        return 1
    print("Lexical errors: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
