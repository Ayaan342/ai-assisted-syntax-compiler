"""Pydantic transport schemas; compiler-domain objects remain in compiler/ and ai/."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=100_000, description="Mini-C source code")


class DiagnosticSection(BaseModel):
    success: bool
    errors: list[dict[str, Any]]


class SemanticSection(BaseModel):
    ran: bool
    success: bool | None
    errors: list[dict[str, Any]]


class AnalyzeResponse(BaseModel):
    success: bool
    token_count: int
    lexical: DiagnosticSection
    syntax: DiagnosticSection
    semantic: SemanticSection
    ast: dict[str, Any] | None
    symbols: dict[str, Any] | None


class TokensResponse(BaseModel):
    success: bool
    token_count: int
    tokens: list[dict[str, Any]]
    lexical_errors: list[dict[str, Any]]


class AstResponse(BaseModel):
    success: bool
    ast: dict[str, Any] | None
    lexical_errors: list[dict[str, Any]]
    syntax_errors: list[dict[str, Any]]


class SymbolsResponse(BaseModel):
    success: bool
    ran: bool
    symbols: dict[str, Any] | None
    lexical_errors: list[dict[str, Any]]
    syntax_errors: list[dict[str, Any]]
    semantic_errors: list[dict[str, Any]]


class CorrectionResponse(BaseModel):
    success: bool
    original_code: str
    corrected_code: str
    fully_syntactically_valid: bool
    corrections_applied: int
    history: list[dict[str, Any]]
    predictions: list[dict[str, Any]]
    confidence_values: list[float]
    groq_fallback_used: bool
    ambiguity_selection_used: bool
    needs_llm_fallback: bool
    unresolved_syntax_diagnostics: list[dict[str, Any]]
    semantic_diagnostics: list[dict[str, Any]]
    stop_reason: str


class HealthResponse(BaseModel):
    status: str
    ml_model_loaded: bool
    groq_configured: bool
