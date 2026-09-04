"""Compiler front-end primitives for the AI-assisted Mini-C compiler."""

from .ast_nodes import ASTNode, Program, pretty_ast
from .correction import CorrectionAction, CorrectionCandidate, apply_candidate, validate_candidate
from .error_recovery import DelimiterTracker, RecoveryAction
from .errors import LexicalError, SemanticDiagnostic, SyntaxDiagnostic
from .lexer import MiniCLexer, TokenInfo, tokenize
from .parser import MiniCParser, ParseResult, parse
from .source_location import SourceLocation, SourceSpan
from .semantic_analyzer import (
    SemanticAnalyzer,
    SemanticPipelineResult,
    SemanticResult,
    analyze_semantics,
    analyze_source_semantics,
)
from .symbol_table import (
    BaseType,
    MiniCType,
    Scope,
    ScopeKind,
    Symbol,
    SymbolKind,
    SymbolTable,
    pretty_symbol_table,
)

__all__ = [
    "ASTNode",
    "CorrectionAction",
    "CorrectionCandidate",
    "BaseType",
    "DelimiterTracker",
    "LexicalError",
    "MiniCLexer",
    "MiniCParser",
    "ParseResult",
    "MiniCType",
    "Program",
    "RecoveryAction",
    "Scope",
    "ScopeKind",
    "SemanticAnalyzer",
    "SemanticDiagnostic",
    "SemanticPipelineResult",
    "SemanticResult",
    "SourceLocation",
    "SourceSpan",
    "SyntaxDiagnostic",
    "Symbol",
    "SymbolKind",
    "SymbolTable",
    "TokenInfo",
    "apply_candidate",
    "analyze_semantics",
    "analyze_source_semantics",
    "parse",
    "pretty_ast",
    "pretty_symbol_table",
    "tokenize",
    "validate_candidate",
]
