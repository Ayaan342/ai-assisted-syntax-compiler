"""Source-located Abstract Syntax Tree nodes for Mini-C."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, TypeAlias

from .source_location import SourceSpan


@dataclass(slots=True, kw_only=True)
class ASTNode:
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"node": type(self).__name__}
        for item in fields(self):
            value = getattr(self, item.name)
            result[item.name] = value.to_dict() if item.name == "span" else _serialize(value)
        return result


def _serialize(value: Any) -> Any:
    if isinstance(value, ASTNode):
        return value.to_dict()
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


@dataclass(slots=True, kw_only=True)
class Program(ASTNode):
    functions: list[FunctionDefinition]


@dataclass(slots=True, kw_only=True)
class FunctionDefinition(ASTNode):
    return_type: str
    name: str
    parameters: list[Parameter]
    body: Block


@dataclass(slots=True, kw_only=True)
class Parameter(ASTNode):
    type_name: str
    name: str


@dataclass(slots=True, kw_only=True)
class Block(ASTNode):
    statements: list[Statement]


@dataclass(slots=True, kw_only=True)
class VariableDeclaration(ASTNode):
    type_name: str
    name: str
    initializer: Expression | None = None


@dataclass(slots=True, kw_only=True)
class ArrayDeclaration(ASTNode):
    type_name: str
    name: str
    size: Expression


@dataclass(slots=True, kw_only=True)
class ExpressionStatement(ASTNode):
    expression: Expression | None


@dataclass(slots=True, kw_only=True)
class Assignment(ASTNode):
    target: Expression
    operator: str
    value: Expression


@dataclass(slots=True, kw_only=True)
class IfStatement(ASTNode):
    condition: Expression
    then_branch: Statement
    else_branch: Statement | None = None


@dataclass(slots=True, kw_only=True)
class WhileStatement(ASTNode):
    condition: Expression
    body: Statement


@dataclass(slots=True, kw_only=True)
class ForStatement(ASTNode):
    initializer: ASTNode | None
    condition: Expression | None
    update: Expression | None
    body: Statement


@dataclass(slots=True, kw_only=True)
class BreakStatement(ASTNode):
    pass


@dataclass(slots=True, kw_only=True)
class ContinueStatement(ASTNode):
    pass


@dataclass(slots=True, kw_only=True)
class ReturnStatement(ASTNode):
    value: Expression | None


@dataclass(slots=True, kw_only=True)
class BinaryExpression(ASTNode):
    operator: str
    left: Expression
    right: Expression


@dataclass(slots=True, kw_only=True)
class UnaryExpression(ASTNode):
    operator: str
    operand: Expression


@dataclass(slots=True, kw_only=True)
class UpdateExpression(ASTNode):
    operator: str
    operand: Expression
    prefix: bool


@dataclass(slots=True, kw_only=True)
class Identifier(ASTNode):
    name: str


@dataclass(slots=True, kw_only=True)
class Literal(ASTNode):
    value: Any
    literal_type: str


@dataclass(slots=True, kw_only=True)
class FunctionCall(ASTNode):
    callee: Expression
    arguments: list[Expression]


@dataclass(slots=True, kw_only=True)
class ArrayAccess(ASTNode):
    array: Expression
    index: Expression


Expression: TypeAlias = Assignment | BinaryExpression | UnaryExpression | UpdateExpression | Identifier | Literal | FunctionCall | ArrayAccess

Statement: TypeAlias = Block | VariableDeclaration | ArrayDeclaration | ExpressionStatement | IfStatement | WhileStatement | ForStatement | BreakStatement | ContinueStatement | ReturnStatement


def pretty_ast(node: ASTNode) -> str:
    """Render an AST as a compact, terminal-portable ASCII tree."""

    lines: list[str] = []

    def label(value: ASTNode) -> str:
        details: str | None = None
        if isinstance(value, FunctionDefinition):
            details = f"{value.name}: {value.return_type}"
        elif isinstance(value, Parameter):
            details = f"{value.name}: {value.type_name}"
        elif isinstance(value, (VariableDeclaration, ArrayDeclaration)):
            details = f"{value.name}: {value.type_name}"
        elif isinstance(value, Identifier):
            details = value.name
        elif isinstance(value, Literal):
            details = repr(value.value)
        elif isinstance(value, (Assignment, BinaryExpression, UnaryExpression, UpdateExpression)):
            details = value.operator
            if isinstance(value, UpdateExpression):
                details += ", prefix" if value.prefix else ", postfix"
        return type(value).__name__ + (f"({details})" if details is not None else "")

    def children(value: ASTNode) -> list[ASTNode]:
        result: list[ASTNode] = []
        for item in fields(value):
            if item.name == "span":
                continue
            field_value = getattr(value, item.name)
            if isinstance(field_value, ASTNode):
                result.append(field_value)
            elif isinstance(field_value, list):
                result.extend(child for child in field_value if isinstance(child, ASTNode))
        return result

    def visit(value: ASTNode, prefix: str, last: bool, root: bool = False) -> None:
        connector = "" if root else ("`-- " if last else "|-- ")
        lines.append(prefix + connector + label(value))
        descendants = children(value)
        next_prefix = prefix if root else prefix + ("    " if last else "|   ")
        for index, child in enumerate(descendants):
            visit(child, next_prefix, index == len(descendants) - 1)

    visit(node, "", True, root=True)
    return "\n".join(lines)
