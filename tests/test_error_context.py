from ai.error_context import ErrorContext, TokenContext


def test_error_context_is_ai_ready_and_serializable() -> None:
    token = TokenContext("IDENTIFIER", "retrun", 3, 5, 24)
    context = ErrorContext(
        phase="lexical_validation",
        message="Suspicious identifier",
        line=3,
        column=5,
        current_token=token,
        previous_tokens=(TokenContext("RBRACE", "}", 2, 1, 18),),
        expected_tokens=("RETURN",),
        grammar_context="statement",
        delimiter_depth={"brace": 1},
        nearby_source="retrun x;",
        metadata={"source": "synthetic"},
    )
    payload = context.to_dict()
    assert payload["current_token"]["lexeme"] == "retrun"
    assert payload["expected_tokens"] == ["RETURN"]
    assert payload["delimiter_depth"] == {"brace": 1}

