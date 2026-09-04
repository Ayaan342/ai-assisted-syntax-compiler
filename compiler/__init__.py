"""Compiler front-end primitives for the AI-assisted Mini-C compiler."""

from .ast_nodes import ASTNode, Program, pretty_ast
from .correction import CorrectionAction, CorrectionCandidate, apply_candidate, validate_candidate
from .error_recovery import DelimiterTracker, RecoveryAction
from .errors import LexicalError, SyntaxDiagnostic
from .lexer import MiniCLexer, TokenInfo, tokenize
from .parser import MiniCParser, ParseResult, parse
from .source_location import SourceLocation, SourceSpan

__all__ = [
    "ASTNode",
    "CorrectionAction",
    "CorrectionCandidate",
    "DelimiterTracker",
    "LexicalError",
    "MiniCLexer",
    "MiniCParser",
    "ParseResult",
    "Program",
    "RecoveryAction",
    "SourceLocation",
    "SourceSpan",
    "SyntaxDiagnostic",
    "TokenInfo",
    "apply_candidate",
    "parse",
    "pretty_ast",
    "tokenize",
    "validate_candidate",
]
