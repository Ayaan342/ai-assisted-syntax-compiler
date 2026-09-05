"""Read-only compiler analysis routes."""

from __future__ import annotations

from fastapi import APIRouter

from compiler.lexer import tokenize
from compiler.parser import parse
from compiler.semantic_analyzer import analyze_source_semantics

from ..schemas import (
    AnalyzeResponse,
    AstResponse,
    CodeRequest,
    SymbolsResponse,
    TokensResponse,
)


router = APIRouter(tags=["analysis"])


@router.post("/analyze", response_model=AnalyzeResponse, summary="Analyze Mini-C source")
def analyze_source(request: CodeRequest) -> AnalyzeResponse:
    parsed = parse(request.code)
    semantic = None
    if parsed.valid:
        semantic = analyze_source_semantics(request.code).semantic_result
    semantic_errors = semantic.diagnostics if semantic is not None else []
    return AnalyzeResponse(
        success=parsed.valid and semantic is not None and semantic.success,
        token_count=len(parsed.tokens),
        lexical={
            "success": not parsed.lexical_errors,
            "errors": [item.to_dict() for item in parsed.lexical_errors],
        },
        syntax={
            "success": parsed.ast is not None and not parsed.syntax_errors,
            "errors": [item.to_dict() for item in parsed.syntax_errors],
        },
        semantic={
            "ran": semantic is not None,
            "success": semantic.success if semantic is not None else None,
            "errors": [item.to_dict() for item in semantic_errors],
        },
        ast=parsed.ast.to_dict() if parsed.ast is not None else None,
        symbols=semantic.symbol_table.to_dict() if semantic is not None else None,
    )


@router.post("/tokens", response_model=TokensResponse, summary="Tokenize Mini-C source")
def source_tokens(request: CodeRequest) -> TokensResponse:
    tokens, errors = tokenize(request.code)
    return TokensResponse(
        success=not errors,
        token_count=len(tokens),
        tokens=[item.to_dict() for item in tokens],
        lexical_errors=[item.to_dict() for item in errors],
    )


@router.post("/ast", response_model=AstResponse, summary="Build the Mini-C AST")
def source_ast(request: CodeRequest) -> AstResponse:
    parsed = parse(request.code)
    return AstResponse(
        success=parsed.valid,
        ast=parsed.ast.to_dict() if parsed.ast is not None else None,
        lexical_errors=[item.to_dict() for item in parsed.lexical_errors],
        syntax_errors=[item.to_dict() for item in parsed.syntax_errors],
    )


@router.post("/symbols", response_model=SymbolsResponse, summary="Build scoped symbols")
def source_symbols(request: CodeRequest) -> SymbolsResponse:
    analysis = analyze_source_semantics(request.code)
    parsed = analysis.parse_result
    semantic = analysis.semantic_result
    return SymbolsResponse(
        success=semantic is not None and semantic.success,
        ran=semantic is not None,
        symbols=semantic.symbol_table.to_dict() if semantic is not None else None,
        lexical_errors=[item.to_dict() for item in parsed.lexical_errors],
        syntax_errors=[item.to_dict() for item in parsed.syntax_errors],
        semantic_errors=(
            [item.to_dict() for item in semantic.diagnostics]
            if semantic is not None
            else []
        ),
    )
