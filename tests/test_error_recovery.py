from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai.error_context import ErrorContext, build_error_contexts
from compiler.ast_nodes import Program
from compiler.correction import (
    CorrectionAction,
    CorrectionCandidate,
    apply_candidate,
    validate_candidate,
)
from compiler.error_recovery import DelimiterTracker
from compiler.lexer import tokenize
from compiler.parser import MiniCParser, parse
from compiler.source_location import SourceLocation, SourceSpan


def diagnostic(source: str):
    result = parse(source)
    assert result.syntax_errors
    return result.syntax_errors[0]


def candidate_with_action(error, action: CorrectionAction):
    return next(candidate for candidate in error.correction_candidates if candidate.action is action)


def test_missing_semicolon_after_declaration() -> None:
    error = diagnostic("int main(){ int x = 10 return 0; }")
    candidate = candidate_with_action(error, CorrectionAction.INSERT)
    assert candidate.token_type == "SEMICOLON"
    assert error.grammar_context == "declaration"


def test_missing_semicolon_after_assignment() -> None:
    error = diagnostic("int main(){ x = 10 return 0; }")
    assert candidate_with_action(error, CorrectionAction.INSERT).text == ";"


def test_missing_semicolon_after_return() -> None:
    error = diagnostic("int main(){ return 10 }")
    assert error.grammar_context == "return_statement"
    assert candidate_with_action(error, CorrectionAction.INSERT).token_type == "SEMICOLON"


def test_missing_rparen_in_if() -> None:
    error = diagnostic("int main(){ if (x > 5 { return 0; } }")
    assert error.grammar_context == "if_condition"
    assert error.correction_candidates[0].token_type == "RPAREN"


def test_missing_lparen_after_if() -> None:
    error = diagnostic("int main(){ if x > 5) { return 0; } }")
    candidate = candidate_with_action(error, CorrectionAction.INSERT)
    assert (candidate.token_type, candidate.text) == ("LPAREN", "(")


def test_missing_rparen_in_while() -> None:
    error = diagnostic("int main(){ while (x < 5 { x++; } return 0; }")
    assert error.grammar_context == "while_condition"
    assert error.correction_candidates[0].token_type == "RPAREN"


def test_malformed_for_header() -> None:
    error = diagnostic("int main(){ for(int i=0; i<5; i++ { break; } }")
    assert error.grammar_context == "for_header"
    assert error.correction_candidates[0].token_type == "RPAREN"


def test_wrong_bracket_in_if_condition() -> None:
    error = diagnostic("int main(){ if [x > 5) { return 0; } }")
    replacement = candidate_with_action(error, CorrectionAction.REPLACE)
    assert replacement.token_type == "LPAREN"
    assert replacement.text == "("
    assert error.recovery_action.strategy == "token_replacement"


def test_extra_assignment_operator() -> None:
    error = diagnostic("int main(){ int x = = 10; return 0; }")
    deletion = candidate_with_action(error, CorrectionAction.DELETE)
    assert deletion.token_lexeme == "="
    assert error.recovery_action.strategy == "token_deletion"


def test_missing_closing_brace_at_eof() -> None:
    error = diagnostic("int main(){ return 0;")
    assert error.code == "UNEXPECTED_EOF"
    assert candidate_with_action(error, CorrectionAction.INSERT).token_type == "RBRACE"


def test_malformed_function_parameter_list() -> None:
    result = parse("int add(int a, ) { return a; }")
    assert result.syntax_errors
    assert result.syntax_errors[0].unexpected_token == "RPAREN"
    assert len(result.syntax_errors) < 5


def test_malformed_function_call() -> None:
    result = parse("int main(){ foo(1,); return 0; }")
    assert result.syntax_errors
    assert any(error.unexpected_token == "RPAREN" for error in result.syntax_errors)


def test_function_call_comma_recovery_stays_inside_return_expression() -> None:
    extra = diagnostic(
        "int add(int x,int y){return x+y;} int main(){return add(1,,2);}"
    )
    assert extra.grammar_context == "function_call"
    deletion = candidate_with_action(extra, CorrectionAction.DELETE)
    assert deletion.token_type == "COMMA"
    assert validate_candidate(
        "int add(int x,int y){return x+y;} int main(){return add(1,,2);}",
        deletion,
    ).valid

    source = "int add(int x,int y){return x+y;} int main(){return add(1 2);}"
    missing = diagnostic(source)
    assert missing.grammar_context == "function_call"
    insertion = candidate_with_action(missing, CorrectionAction.INSERT)
    assert (insertion.token_type, insertion.text) == ("COMMA", ",")
    assert validate_candidate(source, insertion).valid


@pytest.mark.parametrize(
    "source,token_type",
    [
        ("int main(){ return 0; } }", "RBRACE"),
        ("int main(){ if(true)) { return 0; } }", "RPAREN"),
        ("int main(){ int a[2]; return a[0]]; }", "RBRACKET"),
    ],
)
def test_surplus_closing_delimiter_generates_valid_local_deletion(
    source: str, token_type: str
) -> None:
    error = diagnostic(source)
    deletions = [
        candidate
        for candidate in error.correction_candidates
        if candidate.action is CorrectionAction.DELETE
        and candidate.token_type == token_type
    ]
    assert len(deletions) == 1
    assert validate_candidate(source, deletions[0]).valid


def test_duplicate_opening_bracket_generates_valid_local_deletion() -> None:
    source = "int main(){ int a[2]; int i=0; return a[[i]; }"
    error = diagnostic(source)
    deletion = candidate_with_action(error, CorrectionAction.DELETE)
    assert (deletion.token_type, deletion.token_lexeme) == ("LBRACKET", "[")
    assert validate_candidate(source, deletion).valid


def test_missing_rparen_and_extra_lparen_are_both_compiler_valid() -> None:
    source = "int main(){ return (0; }"
    error = diagnostic(source)
    alternatives = [
        candidate
        for candidate in error.correction_candidates
        if candidate.action in {CorrectionAction.INSERT, CorrectionAction.DELETE}
    ]
    assert {(candidate.action, candidate.token_type) for candidate in alternatives} == {
        (CorrectionAction.INSERT, "RPAREN"),
        (CorrectionAction.DELETE, "LPAREN"),
    }
    assert all(validate_candidate(source, candidate).valid for candidate in alternatives)


def test_malformed_array_access() -> None:
    error = diagnostic("int main(){ x = arr[i; return 0; }")
    assert error.grammar_context == "array_access"
    assert candidate_with_action(error, CorrectionAction.INSERT).token_type == "RBRACKET"


def test_missing_rbracket_inside_return_keeps_array_access_context() -> None:
    error = diagnostic("int main(){ int a[2]; int i=0; return a[i; }")
    assert error.grammar_context == "array_access"
    candidate = candidate_with_action(error, CorrectionAction.INSERT)
    assert candidate.token_type == "RBRACKET"
    assert candidate.text == "]"


def test_incomplete_expression() -> None:
    error = diagnostic("int main(){ x = x + ; return 0; }")
    deletion = candidate_with_action(error, CorrectionAction.DELETE)
    assert deletion.token_type == "PLUS"


def test_malformed_return_uses_targeted_error_production() -> None:
    error = diagnostic("int main(){ return + ; int y; }")
    assert error.recovery_action.strategy == "yacc_error_production"
    assert error.grammar_context == "return_statement"


def test_panic_recovery_at_semicolon() -> None:
    result = parse("int main(){ x = + ; int y = 2; return y; }")
    assert result.syntax_errors[0].recovery_action.synchronization_token == "SEMICOLON"
    assert result.syntax_errors[0].parsing_continued


def test_panic_recovery_at_closing_brace() -> None:
    result = parse("int main(){ if(true){ x = + } return 0; }")
    assert result.syntax_errors
    assert len(result.syntax_errors) <= 3


def test_panic_recovery_at_closing_parenthesis() -> None:
    result = parse("int main(){ if (x + ) { return 0; } return 1; }")
    assert result.syntax_errors
    assert any(error.unexpected_token == "RPAREN" for error in result.syntax_errors)


def test_multiple_independent_syntax_errors() -> None:
    source = (Path(__file__).parents[1] / "examples" / "invalid" / "multiple_errors.mc").read_text(encoding="utf-8")
    result = parse(source)
    assert len(result.syntax_errors) == 4
    assert [error.recovery_action.inserted_token for error in result.syntax_errors] == [
        "SEMICOLON", "RPAREN", "RPAREN", "SEMICOLON"
    ]
    assert all(error.parsing_continued for error in result.syntax_errors)


@pytest.mark.parametrize(
    "source",
    [
        "int main(){((((;}",
        "int main(){ if if if; }",
        "int main(){ x = = = = ; }",
        "int main(int, , ,) { }",
    ],
)
def test_no_infinite_recovery_loop(source: str) -> None:
    result = parse(source)
    assert len(result.syntax_errors) <= 25


def test_no_duplicate_diagnostic_storm_at_eof() -> None:
    result = parse("int main(){ if(true){ while(false){ return 0;")
    eof_errors = [error for error in result.syntax_errors if error.code == "UNEXPECTED_EOF"]
    assert len(eof_errors) == 1


def test_stable_diagnostic_ids_and_codes() -> None:
    source = "int main(){ int x=1 return x }"
    first = parse(source).syntax_errors
    second = parse(source).syntax_errors
    assert [error.diagnostic_id for error in first] == [error.diagnostic_id for error in second]
    assert first[0].diagnostic_id == "SYN-0001"
    assert all(error.code in {"UNEXPECTED_TOKEN", "UNEXPECTED_EOF"} for error in first)


def test_insert_candidate_has_source_position_and_zero_width_span() -> None:
    source = "int main(){ int x=1 return x; }"
    candidate = candidate_with_action(diagnostic(source), CorrectionAction.INSERT)
    assert candidate.offset == source.index("return")
    assert candidate.span.start == candidate.span.end


def test_delete_candidate_has_exact_token_span() -> None:
    source = "int main(){ int x = = 10; }"
    candidate = candidate_with_action(diagnostic(source), CorrectionAction.DELETE)
    assert source[candidate.span.start.offset : candidate.span.end.offset] == "="
    assert candidate.span.end.offset - candidate.span.start.offset == 1


def test_replace_candidate_has_exact_token_span() -> None:
    source = "int main(){ if [x) return 0; }"
    candidate = candidate_with_action(diagnostic(source), CorrectionAction.REPLACE)
    assert source[candidate.span.start.offset : candidate.span.end.offset] == "["
    assert candidate.text == "("


def test_broken_if_has_multiple_plausible_candidates() -> None:
    error = diagnostic("int main(){ if (x > 5 { return 0; } }")
    assert [candidate.action for candidate in error.correction_candidates] == [
        CorrectionAction.INSERT, CorrectionAction.DELETE, CorrectionAction.REPLACE
    ]


def test_delimiter_depth_tracking() -> None:
    tokens, _ = tokenize("int main(){ if (x > 5 { return 0; } }")
    tracker = DelimiterTracker(tokens)
    brace = next(token for token in tokens if token.type == "LBRACE" and token.line == 1 and token.column > 15)
    snapshot = tracker.snapshot_at(brace.offset)
    assert snapshot.paren == 1
    assert snapshot.brace == 1
    assert snapshot.bracket == 0


def test_delimiter_tracker_reports_unclosed_delimiters() -> None:
    tokens, _ = tokenize("int main(){ if(x) {")
    tracker = DelimiterTracker(tokens)
    assert tracker.probable_closers() == ("RBRACE", "RBRACE")


def test_ai_ready_error_context_serialization() -> None:
    source = "int main(){ if (x { return 0; } }"
    result = parse(source)
    context = build_error_contexts(source, result)[0]
    payload = context.to_dict()
    json.dumps(payload)
    assert payload["diagnostic_id"] == "SYN-0001"
    assert payload["correction_candidates"]
    assert payload["recovery_metadata"]["strategy"] == "token_insertion"


def test_ai_context_contains_expected_and_nearby_tokens() -> None:
    source = "int main(){ if x) return 0; }"
    result = parse(source)
    context = ErrorContext.from_diagnostic(result.syntax_errors[0], result.tokens, source)
    assert "LPAREN" in context.expected_tokens
    assert context.current_token is not None
    assert context.next_tokens
    assert context.nearby_source


def test_ai_context_contains_delimiter_depths() -> None:
    source = "int main(){ if (x { return 0; } }"
    result = parse(source)
    context = build_error_contexts(source, result)[0]
    assert context.delimiter_depth["paren"] == 1
    assert set(context.delimiter_depth) == {"paren", "brace", "bracket"}


def test_apply_insert_candidate() -> None:
    source = "int main(){ int x=1 return x; }"
    candidate = candidate_with_action(diagnostic(source), CorrectionAction.INSERT)
    assert apply_candidate(source, candidate) == "int main(){ int x=1 ;return x; }"


def test_apply_delete_candidate() -> None:
    source = "int main(){ int x = = 10; return 0; }"
    candidate = candidate_with_action(diagnostic(source), CorrectionAction.DELETE)
    assert apply_candidate(source, candidate) == "int main(){ int x =  10; return 0; }"


def test_apply_replace_candidate() -> None:
    source = "int main(){ if [x) return 0; }"
    candidate = candidate_with_action(diagnostic(source), CorrectionAction.REPLACE)
    assert apply_candidate(source, candidate) == "int main(){ if (x) return 0; }"


def test_apply_rejects_invalid_candidate_span() -> None:
    location = SourceLocation(1, 1, 99)
    candidate = CorrectionCandidate(
        id="manual",
        action=CorrectionAction.INSERT,
        token_type="SEMICOLON",
        token_lexeme=";",
        offset=99,
        span=SourceSpan(location, location),
        text=";",
        reason="test",
        grammar_context="statement",
        diagnostic_id="SYN-0001",
    )
    with pytest.raises(ValueError):
        apply_candidate("short", candidate)


def test_validate_candidate_reparses_without_selecting_it() -> None:
    source = "int main(){ if (true { return 0; } }"
    candidate = candidate_with_action(diagnostic(source), CorrectionAction.INSERT)
    validation = validate_candidate(source, candidate)
    assert validation.valid
    assert validation.candidate.parser_validated is True
    assert validation.remaining_syntax_errors == 0


def test_valid_programs_still_parse() -> None:
    source = (Path(__file__).parents[1] / "examples" / "valid" / "demo.mc").read_text(encoding="utf-8")
    result = parse(source)
    assert result.valid
    assert isinstance(result.ast, Program)


def test_existing_ast_structure_is_unchanged() -> None:
    result = parse("int main(){ int x=1; return x; }")
    assert result.ast is not None
    function = result.ast.functions[0]
    assert function.name == "main"
    assert [type(statement).__name__ for statement in function.body.statements] == [
        "VariableDeclaration", "ReturnStatement"
    ]


def test_existing_lexer_behavior_is_unchanged() -> None:
    tokens, errors = tokenize("retrun x; innt y; whille (true) {}")
    assert errors == []
    assert tokens[0].type == "IDENTIFIER" and tokens[0].lexeme == "retrun"
    assert tokens[3].type == "IDENTIFIER" and tokens[3].lexeme == "innt"
    assert tokens[6].type == "IDENTIFIER" and tokens[6].lexeme == "whille"
