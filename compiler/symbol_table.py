"""Scoped symbols and explicit Mini-C type representations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .source_location import SourceSpan


class BaseType(str, Enum):
    INT = "int"
    FLOAT = "float"
    CHAR = "char"
    BOOL = "bool"
    VOID = "void"
    STRING = "string"
    ERROR = "<error>"


class TypeKind(str, Enum):
    SCALAR = "scalar"
    ARRAY = "array"
    FUNCTION = "function"


@dataclass(frozen=True, slots=True)
class MiniCType:
    base: BaseType
    kind: TypeKind = TypeKind.SCALAR
    parameter_types: tuple[MiniCType, ...] = ()

    @classmethod
    def scalar(cls, name: str | BaseType) -> MiniCType:
        return cls(BaseType(name))

    @classmethod
    def array(cls, element: str | BaseType) -> MiniCType:
        return cls(BaseType(element), TypeKind.ARRAY)

    @classmethod
    def function(cls, result: str | BaseType, parameters: tuple[MiniCType, ...]) -> MiniCType:
        return cls(BaseType(result), TypeKind.FUNCTION, parameters)

    @property
    def is_numeric(self) -> bool:
        return self.kind is TypeKind.SCALAR and self.base in {BaseType.INT, BaseType.FLOAT}

    @property
    def is_error(self) -> bool:
        return self.base is BaseType.ERROR

    def display(self) -> str:
        if self.kind is TypeKind.ARRAY:
            return f"{self.base.value}[]"
        if self.kind is TypeKind.FUNCTION:
            params = ", ".join(item.display() for item in self.parameter_types)
            return f"function({params}) -> {self.base.value}"
        return self.base.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "base": self.base.value,
            "parameter_types": [item.to_dict() for item in self.parameter_types],
            "display": self.display(),
        }


ERROR_TYPE = MiniCType(BaseType.ERROR)
BOOL_TYPE = MiniCType(BaseType.BOOL)
INT_TYPE = MiniCType(BaseType.INT)
FLOAT_TYPE = MiniCType(BaseType.FLOAT)
VOID_TYPE = MiniCType(BaseType.VOID)


class SymbolKind(str, Enum):
    VARIABLE = "variable"
    ARRAY = "array"
    FUNCTION = "function"
    PARAMETER = "parameter"


class ScopeKind(str, Enum):
    GLOBAL = "global"
    FUNCTION = "function"
    BLOCK = "block"
    LOOP = "loop"


@dataclass(slots=True)
class Symbol:
    id: str
    name: str
    kind: SymbolKind
    type: MiniCType
    scope_id: str
    declaration_span: SourceSpan
    array_size: int | None = None

    @property
    def line(self) -> int:
        return self.declaration_span.start.line

    @property
    def column(self) -> int:
        return self.declaration_span.start.column

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "type": self.type.to_dict(),
            "scope_id": self.scope_id,
            "line": self.line,
            "column": self.column,
            "offset": self.declaration_span.start.offset,
            "span": self.declaration_span.to_dict(),
            "array_size": self.array_size,
        }


@dataclass(slots=True)
class Scope:
    id: str
    name: str
    kind: ScopeKind
    parent: Scope | None = None
    span: SourceSpan | None = None
    symbols: dict[str, Symbol] = field(default_factory=dict)
    children: list[Scope] = field(default_factory=list)

    def declare(self, symbol: Symbol) -> bool:
        if symbol.name in self.symbols:
            return False
        self.symbols[symbol.name] = symbol
        return True

    def lookup_local(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

    def lookup(self, name: str) -> Symbol | None:
        scope: Scope | None = self
        while scope is not None:
            symbol = scope.lookup_local(name)
            if symbol is not None:
                return symbol
            scope = scope.parent
        return None

    def visible_symbols(self) -> dict[str, Symbol]:
        result: dict[str, Symbol] = {}
        scope: Scope | None = self
        while scope is not None:
            for name, symbol in scope.symbols.items():
                result.setdefault(name, symbol)
            scope = scope.parent
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "parent_id": self.parent.id if self.parent else None,
            "span": self.span.to_dict() if self.span else None,
            "symbols": [symbol.to_dict() for symbol in self.symbols.values()],
            "children": [child.to_dict() for child in self.children],
        }


class SymbolTable:
    def __init__(self, program_span: SourceSpan | None = None) -> None:
        self.root = Scope("global", "GLOBAL", ScopeKind.GLOBAL, span=program_span)
        self._scope_counter = 0
        self._symbol_counter = 0

    def new_scope(self, parent: Scope, kind: ScopeKind, name: str, span: SourceSpan | None) -> Scope:
        self._scope_counter += 1
        scope = Scope(f"scope-{self._scope_counter:04d}", name, kind, parent, span)
        parent.children.append(scope)
        return scope

    def new_symbol(
        self,
        scope: Scope,
        name: str,
        kind: SymbolKind,
        type_: MiniCType,
        span: SourceSpan,
        *,
        array_size: int | None = None,
    ) -> Symbol:
        self._symbol_counter += 1
        return Symbol(
            f"symbol-{self._symbol_counter:04d}",
            name,
            kind,
            type_,
            scope.id,
            span,
            array_size,
        )

    def all_scopes(self) -> list[Scope]:
        result: list[Scope] = []

        def visit(scope: Scope) -> None:
            result.append(scope)
            for child in scope.children:
                visit(child)

        visit(self.root)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {"root": self.root.to_dict()}


def pretty_symbol_table(table: SymbolTable) -> str:
    lines: list[str] = []

    def visit(scope: Scope, depth: int) -> None:
        indent = "    " * depth
        lines.append(f"{indent}{scope.name} [{scope.kind.value}] ({scope.id})")
        for symbol in scope.symbols.values():
            lines.append(f"{indent}  - {symbol.name} : {symbol.type.display()} [{symbol.kind.value}]")
        for child in scope.children:
            visit(child, depth + 1)

    visit(table.root, 0)
    return "\n".join(lines)
