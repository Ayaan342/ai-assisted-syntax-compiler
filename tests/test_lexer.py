from __future__ import annotations

from pathlib import Path

import pytest

from compiler.lexer import MiniCLexer, tokenize


def types(source: str) -> list[str]:
    return [token.type for token in tokenize(source)[0]]


def test_all_keywords_and_boolean_values() -> None:
    source = "int float char bool void if else while for break continue return true false"
    tokens, errors = tokenize(source)
    assert errors == []
    assert [token.type for token in tokens] == [
        "INT", "FLOAT", "CHAR", "BOOL", "VOID", "IF", "ELSE", "WHILE",
        "FOR", "BREAK", "CONTINUE", "RETURN", "TRUE", "FALSE",
    ]
    assert tokens[-2].value is True
    assert tokens[-1].value is False


def test_identifiers_include_underscores_and_digits() -> None:
    tokens, errors = tokenize("x studentCount _total value2 innt retrun whille")
    assert errors == []
    assert all(token.type == "IDENTIFIER" for token in tokens)
    assert [token.lexeme for token in tokens] == source_words(
        "x studentCount _total value2 innt retrun whille"
    )


def source_words(source: str) -> list[str]:
    return source.split()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("+ - * / %", ["PLUS", "MINUS", "TIMES", "DIVIDE", "MODULO"]),
        ("= += -= *= /= %=", ["ASSIGN", "PLUS_ASSIGN", "MINUS_ASSIGN", "TIMES_ASSIGN", "DIVIDE_ASSIGN", "MODULO_ASSIGN"]),
        ("++ --", ["INCREMENT", "DECREMENT"]),
        ("< > <= >= == !=", ["LT", "GT", "LE", "GE", "EQ", "NE"]),
        ("&& || !", ["AND", "OR", "NOT"]),
        ("; , ( ) { } [ ]", ["SEMICOLON", "COMMA", "LPAREN", "RPAREN", "LBRACE", "RBRACE", "LBRACKET", "RBRACKET"]),
    ],
)
def test_operators_and_delimiters(source: str, expected: list[str]) -> None:
    assert types(source) == expected


def test_longest_match_for_compound_operators() -> None:
    assert types("a++ >= b && a += 1;") == [
        "IDENTIFIER", "INCREMENT", "GE", "IDENTIFIER", "AND",
        "IDENTIFIER", "PLUS_ASSIGN", "INTEGER_LITERAL", "SEMICOLON",
    ]


def test_literal_values_and_lexemes() -> None:
    source = "0 123 3.14 2. .5 1e3 2.5e-2 'A' '\\n' \"hello\\n\""
    tokens, errors = tokenize(source)
    assert errors == []
    assert [token.type for token in tokens] == [
        "INTEGER_LITERAL", "INTEGER_LITERAL", "FLOAT_LITERAL", "FLOAT_LITERAL",
        "FLOAT_LITERAL", "FLOAT_LITERAL", "FLOAT_LITERAL", "CHAR_LITERAL",
        "CHAR_LITERAL", "STRING_LITERAL",
    ]
    assert [token.value for token in tokens] == [
        0, 123, 3.14, 2.0, 0.5, 1000.0, 0.025, "A", "\n", "hello\n"
    ]
    assert tokens[2].lexeme == "3.14"
    assert tokens[-1].lexeme == '"hello\\n"'


def test_comments_are_discarded_and_lines_remain_correct() -> None:
    source = "int x; // one line\n/* two\nlines */\nfloat y;"
    tokens, errors = tokenize(source)
    assert errors == []
    assert [token.type for token in tokens] == [
        "INT", "IDENTIFIER", "SEMICOLON", "FLOAT", "IDENTIFIER", "SEMICOLON"
    ]
    assert tokens[3].line == 4
    assert tokens[3].column == 1


def test_precise_line_column_offset_and_half_open_span() -> None:
    source = "int x;\n  x += 2;"
    tokens, _ = tokenize(source)
    x_assignment = tokens[3]
    assert (x_assignment.line, x_assignment.column, x_assignment.offset) == (2, 3, 9)
    assert x_assignment.span.end.offset == 10
    assert tokens[4].column == 5


def test_crlf_positions() -> None:
    tokens, errors = tokenize("int x;\r\n\treturn x;")
    assert errors == []
    return_token = tokens[3]
    assert (return_token.line, return_token.column) == (2, 2)


def test_illegal_characters_are_structured_and_lexing_continues() -> None:
    tokens, errors = tokenize("int x = 1 @ 2;")
    assert len(errors) == 1
    error = errors[0]
    assert error.to_dict()["phase"] == "lexical"
    assert error.code == "ILLEGAL_CHARACTER"
    assert (error.line, error.column, error.lexeme) == (1, 11, "@")
    assert [token.value for token in tokens if token.type == "INTEGER_LITERAL"] == [1, 2]


@pytest.mark.parametrize("source", ["12abc", "2value", "1.2.3"])
def test_malformed_numbers(source: str) -> None:
    tokens, errors = tokenize(f"int x = {source};")
    assert len(errors) == 1
    assert errors[0].code == "MALFORMED_NUMBER"
    assert errors[0].lexeme == source
    assert types_from(tokens)[-1] == "SEMICOLON"


def types_from(tokens) -> list[str]:
    return [token.type for token in tokens]


def test_malformed_and_unterminated_character_literals() -> None:
    tokens, errors = tokenize("char a = 'xy';\nchar b = 'z\nint n = 1;")
    assert [error.code for error in errors] == ["MALFORMED_CHAR", "UNTERMINATED_CHAR"]
    assert errors[1].line == 2
    assert "INT" in types_from(tokens)


def test_unterminated_string_recovers_at_newline() -> None:
    tokens, errors = tokenize('"hello\nint x;')
    assert len(errors) == 1
    assert errors[0].code == "UNTERMINATED_STRING"
    assert types_from(tokens) == ["INT", "IDENTIFIER", "SEMICOLON"]
    assert tokens[0].line == 2


def test_unterminated_block_comment_reports_to_eof() -> None:
    tokens, errors = tokenize("int x; /* never closed\nstill comment")
    assert types_from(tokens) == ["INT", "IDENTIFIER", "SEMICOLON"]
    assert len(errors) == 1
    assert errors[0].code == "UNTERMINATED_COMMENT"
    assert errors[0].line == 1


def test_lexer_instance_can_be_reused_without_state_leakage() -> None:
    lexer = MiniCLexer()
    _, first_errors = lexer.scan("@")
    second_tokens, second_errors = lexer.scan("int x;")
    assert len(first_errors) == 1
    assert second_errors == []
    assert types_from(second_tokens) == ["INT", "IDENTIFIER", "SEMICOLON"]
    assert second_tokens[0].line == 1


def test_demo_program_tokenizes_without_errors() -> None:
    path = Path(__file__).parents[1] / "examples" / "valid" / "demo.mc"
    tokens, errors = tokenize(path.read_text(encoding="utf-8"))
    assert errors == []
    assert tokens[0].type == "INT"
    assert sum(token.type == "FOR" for token in tokens) == 1
    assert sum(token.type == "WHILE" for token in tokens) == 1
    assert sum(token.type == "RETURN" for token in tokens) == 4

