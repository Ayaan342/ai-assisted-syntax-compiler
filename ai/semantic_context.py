"""Serializable optional context derived from semantic diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compiler.errors import SemanticDiagnostic
from compiler.symbol_table import Scope, SymbolTable


@dataclass(frozen=True, slots=True)
class SemanticContext:
    diagnostic: SemanticDiagnostic
    current_scope: str | None
    visible_identifiers: tuple[dict[str, Any], ...]
    expected_type: str | None
    actual_type: str | None

    @classmethod
    def from_diagnostic(
        cls, diagnostic: SemanticDiagnostic, table: SymbolTable
    ) -> SemanticContext:
        scope = next(
            (item for item in table.all_scopes() if item.id == diagnostic.scope_id),
            None,
        )
        visible = scope.visible_symbols() if scope else {}
        return cls(
            diagnostic=diagnostic,
            current_scope=scope.id if scope else None,
            visible_identifiers=tuple(
                {
                    "name": symbol.name,
                    "kind": symbol.kind.value,
                    "type": symbol.type.display(),
                    "declared_in": symbol.scope_id,
                }
                for symbol in visible.values()
            ),
            expected_type=diagnostic.expected_type,
            actual_type=diagnostic.actual_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostic": self.diagnostic.to_dict(),
            "current_scope": self.current_scope,
            "visible_identifiers": list(self.visible_identifiers),
            "expected_type": self.expected_type,
            "actual_type": self.actual_type,
        }


def build_semantic_contexts(semantic_result: Any) -> list[SemanticContext]:
    return [
        SemanticContext.from_diagnostic(item, semantic_result.symbol_table)
        for item in semantic_result.diagnostics
    ]
