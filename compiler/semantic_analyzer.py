"""Two-pass scoped semantic analysis over a valid Mini-C AST."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ast_nodes import (
    ASTNode,
    ArrayAccess,
    ArrayDeclaration,
    Assignment,
    BinaryExpression,
    Block,
    BreakStatement,
    ContinueStatement,
    ExpressionStatement,
    ForStatement,
    FunctionCall,
    FunctionDefinition,
    Identifier,
    IfStatement,
    Literal,
    Program,
    ReturnStatement,
    UnaryExpression,
    UpdateExpression,
    VariableDeclaration,
    WhileStatement,
)
from .errors import SemanticDiagnostic
from .parser import ParseResult, parse
from .symbol_table import (
    BOOL_TYPE,
    ERROR_TYPE,
    FLOAT_TYPE,
    INT_TYPE,
    VOID_TYPE,
    BaseType,
    MiniCType,
    Scope,
    ScopeKind,
    Symbol,
    SymbolKind,
    SymbolTable,
    TypeKind,
)


@dataclass(frozen=True, slots=True)
class SemanticResult:
    symbol_table: SymbolTable
    diagnostics: list[SemanticDiagnostic]
    expression_types: dict[int, MiniCType]

    @property
    def success(self) -> bool:
        return not self.diagnostics

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "symbol_table": self.symbol_table.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SemanticPipelineResult:
    parse_result: ParseResult
    semantic_result: SemanticResult | None

    @property
    def success(self) -> bool:
        return self.parse_result.valid and self.semantic_result is not None and self.semantic_result.success


class SemanticAnalyzer:
    def __init__(self) -> None:
        self.table = SymbolTable()
        self.diagnostics: list[SemanticDiagnostic] = []
        self.expression_types: dict[int, MiniCType] = {}
        self._current_return_type = VOID_TYPE

    def analyze(self, program: Program) -> SemanticResult:
        self.table = SymbolTable(program.span)
        self.diagnostics = []
        self.expression_types = {}

        # Pass 1 registers every callable before any body is traversed.
        for function in program.functions:
            parameter_types = tuple(MiniCType.scalar(item.type_name) for item in function.parameters)
            function_type = MiniCType.function(function.return_type, parameter_types)
            self._declare(self.table.root, function.name, SymbolKind.FUNCTION, function_type, function)
        for declaration in program.globals:
            self._declare_declaration(declaration, self.table.root, register_only=True)

        # Pass 2 checks initializers, sizes, parameters, and bodies.
        for declaration in program.globals:
            self._check_declaration_value(declaration, self.table.root)
        for function in program.functions:
            self._analyze_function(function)

        return SemanticResult(self.table, list(self.diagnostics), dict(self.expression_types))

    def _analyze_function(self, function: FunctionDefinition) -> None:
        function_scope = self.table.new_scope(
            self.table.root, ScopeKind.FUNCTION, f"FUNCTION {function.name}", function.body.span
        )
        self._current_return_type = MiniCType.scalar(function.return_type)
        for parameter in function.parameters:
            parameter_type = MiniCType.scalar(parameter.type_name)
            if parameter_type.base is BaseType.VOID:
                self._report(
                    "SEM-VOID-VALUE-USE",
                    f"Parameter '{parameter.name}' cannot have type void",
                    parameter,
                    identifier=parameter.name,
                    actual=parameter_type,
                    scope=function_scope,
                )
            self._declare(
                function_scope,
                parameter.name,
                SymbolKind.PARAMETER,
                parameter_type,
                parameter,
            )
        self._block(function.body, function_scope, loop_depth=0, create_scope=False)

    def _block(self, block: Block, parent: Scope, loop_depth: int, *, create_scope: bool = True) -> None:
        scope = (
            self.table.new_scope(parent, ScopeKind.BLOCK, "BLOCK", block.span)
            if create_scope
            else parent
        )
        for statement in block.statements:
            self._statement(statement, scope, loop_depth)

    def _statement(self, node: ASTNode, scope: Scope, loop_depth: int) -> None:
        if isinstance(node, Block):
            self._block(node, scope, loop_depth)
        elif isinstance(node, (VariableDeclaration, ArrayDeclaration)):
            self._declare_declaration(node, scope)
        elif isinstance(node, ExpressionStatement):
            if node.expression is not None:
                self._expression(node.expression, scope)
        elif isinstance(node, IfStatement):
            self._check_condition(node.condition, scope, "if")
            self._statement(node.then_branch, scope, loop_depth)
            if node.else_branch is not None:
                self._statement(node.else_branch, scope, loop_depth)
        elif isinstance(node, WhileStatement):
            self._check_condition(node.condition, scope, "while")
            self._statement(node.body, scope, loop_depth + 1)
        elif isinstance(node, ForStatement):
            loop_scope = self.table.new_scope(scope, ScopeKind.LOOP, "FOR LOOP", node.span)
            if node.initializer is not None:
                if isinstance(node.initializer, (VariableDeclaration, ArrayDeclaration)):
                    self._declare_declaration(node.initializer, loop_scope)
                else:
                    self._expression(node.initializer, loop_scope)
            if node.condition is not None:
                self._check_condition(node.condition, loop_scope, "for")
            if node.update is not None:
                self._expression(node.update, loop_scope)
            self._statement(node.body, loop_scope, loop_depth + 1)
        elif isinstance(node, BreakStatement):
            if loop_depth == 0:
                self._report(
                    "SEM-BREAK-OUTSIDE-LOOP",
                    "'break' may only appear inside a loop",
                    node,
                    scope=scope,
                )
        elif isinstance(node, ContinueStatement):
            if loop_depth == 0:
                self._report(
                    "SEM-CONTINUE-OUTSIDE-LOOP",
                    "'continue' may only appear inside a loop",
                    node,
                    scope=scope,
                )
        elif isinstance(node, ReturnStatement):
            self._check_return(node, scope)

    def _declare_declaration(
        self,
        node: VariableDeclaration | ArrayDeclaration,
        scope: Scope,
        *,
        register_only: bool = False,
    ) -> None:
        base = BaseType(node.type_name)
        if isinstance(node, ArrayDeclaration):
            declared_type = MiniCType.array(base)
            kind = SymbolKind.ARRAY
            array_size = node.size.value if isinstance(node.size, Literal) and type(node.size.value) is int else None
        else:
            declared_type = MiniCType(base)
            kind = SymbolKind.VARIABLE
            array_size = None
        if base is BaseType.VOID:
            self._report(
                "SEM-VOID-VALUE-USE",
                f"{kind.value.title()} '{node.name}' cannot have type void",
                node,
                identifier=node.name,
                actual=declared_type,
                scope=scope,
            )
        self._declare(scope, node.name, kind, declared_type, node, array_size=array_size)
        if not register_only:
            self._check_declaration_value(node, scope)

    def _check_declaration_value(
        self, node: VariableDeclaration | ArrayDeclaration, scope: Scope
    ) -> None:
        if isinstance(node, ArrayDeclaration):
            size_type = self._expression(node.size, scope)
            if not size_type.is_error and size_type != INT_TYPE:
                self._report(
                    "SEM-INVALID-ARRAY-INDEX",
                    f"Array size for '{node.name}' must have type int",
                    node.size,
                    identifier=node.name,
                    expected=INT_TYPE,
                    actual=size_type,
                    scope=scope,
                )
        elif node.initializer is not None:
            value_type = self._expression(node.initializer, scope)
            target_type = MiniCType.scalar(node.type_name)
            self._check_assignment_compatibility(target_type, value_type, node, scope, node.name)

    def _declare(
        self,
        scope: Scope,
        name: str,
        kind: SymbolKind,
        type_: MiniCType,
        node: ASTNode,
        *,
        array_size: int | None = None,
    ) -> Symbol | None:
        previous = scope.lookup_local(name)
        if previous is not None:
            self._report(
                "SEM-DUPLICATE-DECLARATION",
                f"Identifier '{name}' is already declared in this scope",
                node,
                identifier=name,
                actual=type_,
                scope=scope,
            )
            return None
        symbol = self.table.new_symbol(scope, name, kind, type_, node.span, array_size=array_size)
        scope.declare(symbol)
        return symbol

    def _expression(self, node: ASTNode, scope: Scope) -> MiniCType:
        if isinstance(node, Literal):
            result = MiniCType.scalar(node.literal_type)
        elif isinstance(node, Identifier):
            symbol = self._resolve(node.name, node, scope)
            if symbol is None:
                result = ERROR_TYPE
            elif symbol.kind is SymbolKind.ARRAY:
                self._report(
                    "SEM-INVALID-ARRAY-USE",
                    f"Array '{node.name}' cannot be used as a scalar value",
                    node,
                    identifier=node.name,
                    actual=symbol.type,
                    scope=scope,
                )
                result = ERROR_TYPE
            elif symbol.kind is SymbolKind.FUNCTION:
                self._report(
                    "SEM-INVALID-ASSIGNMENT",
                    f"Function '{node.name}' cannot be used as a scalar value without a call",
                    node,
                    identifier=node.name,
                    actual=symbol.type,
                    scope=scope,
                )
                result = ERROR_TYPE
            else:
                result = symbol.type
        elif isinstance(node, ArrayAccess):
            result = self._array_access(node, scope)
        elif isinstance(node, FunctionCall):
            result = self._function_call(node, scope)
        elif isinstance(node, Assignment):
            target_type = self._lvalue(node.target, scope)
            value_type = self._expression(node.value, scope)
            if node.operator == "=":
                self._check_assignment_compatibility(target_type, value_type, node, scope)
            else:
                if not target_type.is_error and not target_type.is_numeric:
                    self._report(
                        "SEM-INVALID-ASSIGNMENT",
                        f"Compound assignment '{node.operator}' requires a numeric target",
                        node,
                        expected="numeric",
                        actual=target_type,
                        scope=scope,
                    )
                if not value_type.is_error and not value_type.is_numeric:
                    self._report(
                        "SEM-TYPE-MISMATCH",
                        f"Compound assignment '{node.operator}' requires a numeric value",
                        node.value,
                        expected="numeric",
                        actual=value_type,
                        scope=scope,
                    )
                if target_type.is_numeric and value_type.is_numeric:
                    operation_type = (
                        FLOAT_TYPE
                        if BaseType.FLOAT in {target_type.base, value_type.base}
                        else INT_TYPE
                    )
                    if not self._assignable(target_type, operation_type):
                        self._report(
                            "SEM-TYPE-MISMATCH",
                            f"Result of '{node.operator}' cannot be assigned to {target_type.display()}",
                            node,
                            expected=target_type,
                            actual=operation_type,
                            scope=scope,
                        )
            result = target_type
        elif isinstance(node, BinaryExpression):
            result = self._binary(node, scope)
        elif isinstance(node, UnaryExpression):
            operand = self._expression(node.operand, scope)
            if node.operator == "!":
                if not operand.is_error and operand != BOOL_TYPE:
                    self._report("SEM-TYPE-MISMATCH", "Logical '!' requires a bool operand", node,
                                 expected=BOOL_TYPE, actual=operand, scope=scope)
                result = BOOL_TYPE
            else:
                if not operand.is_error and not operand.is_numeric:
                    self._report("SEM-TYPE-MISMATCH", f"Unary '{node.operator}' requires a numeric operand",
                                 node, expected="numeric", actual=operand, scope=scope)
                    result = ERROR_TYPE
                else:
                    result = operand
        elif isinstance(node, UpdateExpression):
            operand = self._lvalue(node.operand, scope)
            if not operand.is_error and not operand.is_numeric:
                self._report(
                    "SEM-INVALID-ASSIGNMENT",
                    f"Update operator '{node.operator}' requires an assignable numeric operand",
                    node,
                    expected="assignable numeric",
                    actual=operand,
                    scope=scope,
                )
            result = operand
        else:
            result = ERROR_TYPE
        self.expression_types[id(node)] = result
        return result

    def _binary(self, node: BinaryExpression, scope: Scope) -> MiniCType:
        left = self._expression(node.left, scope)
        right = self._expression(node.right, scope)
        if left.is_error or right.is_error:
            return ERROR_TYPE
        if node.operator in {"+", "-", "*", "/", "%"}:
            if not left.is_numeric or not right.is_numeric:
                self._report("SEM-TYPE-MISMATCH", f"Operator '{node.operator}' requires numeric operands",
                             node, expected="numeric", actual=f"{left.display()}, {right.display()}", scope=scope)
                return ERROR_TYPE
            return FLOAT_TYPE if BaseType.FLOAT in {left.base, right.base} else INT_TYPE
        if node.operator in {"<", "<=", ">", ">="}:
            if not left.is_numeric or not right.is_numeric:
                self._report("SEM-TYPE-MISMATCH", f"Operator '{node.operator}' requires numeric operands",
                             node, expected="numeric", actual=f"{left.display()}, {right.display()}", scope=scope)
            return BOOL_TYPE
        if node.operator in {"==", "!="}:
            if not self._comparable(left, right):
                self._report("SEM-TYPE-MISMATCH", f"Operator '{node.operator}' requires compatible operands",
                             node, expected=left, actual=right, scope=scope)
            return BOOL_TYPE
        if node.operator in {"&&", "||"}:
            if left != BOOL_TYPE or right != BOOL_TYPE:
                self._report("SEM-TYPE-MISMATCH", f"Operator '{node.operator}' requires bool operands",
                             node, expected=BOOL_TYPE, actual=f"{left.display()}, {right.display()}", scope=scope)
            return BOOL_TYPE
        return ERROR_TYPE

    def _lvalue(self, node: ASTNode, scope: Scope) -> MiniCType:
        if isinstance(node, Identifier):
            symbol = self._resolve(node.name, node, scope)
            if symbol is None:
                return ERROR_TYPE
            if symbol.kind not in {SymbolKind.VARIABLE, SymbolKind.PARAMETER}:
                self._report("SEM-INVALID-ASSIGNMENT", f"'{node.name}' is not an assignable scalar",
                             node, identifier=node.name, actual=symbol.type, scope=scope)
                return ERROR_TYPE
            return symbol.type
        if isinstance(node, ArrayAccess):
            return self._array_access(node, scope)
        actual = self._expression(node, scope)
        self._report(
            "SEM-INVALID-ASSIGNMENT",
            "Assignment or update target is not assignable",
            node,
            expected="identifier or array element",
            actual=actual,
            scope=scope,
        )
        return ERROR_TYPE

    def _array_access(self, node: ArrayAccess, scope: Scope) -> MiniCType:
        array_type = ERROR_TYPE
        identifier = node.array.name if isinstance(node.array, Identifier) else None
        if identifier is not None:
            symbol = self._resolve(identifier, node.array, scope)
            if symbol is not None:
                if symbol.kind is not SymbolKind.ARRAY:
                    self._report(
                        "SEM-INVALID-ARRAY-USE",
                        f"Identifier '{identifier}' is not an array",
                        node.array,
                        identifier=identifier,
                        expected="array",
                        actual=symbol.type,
                        scope=scope,
                    )
                else:
                    array_type = symbol.type
        else:
            candidate = self._expression(node.array, scope)
            if candidate.kind is TypeKind.ARRAY:
                array_type = candidate
            elif not candidate.is_error:
                self._report("SEM-INVALID-ARRAY-USE", "Indexed expression is not an array", node.array,
                             expected="array", actual=candidate, scope=scope)
        index_type = self._expression(node.index, scope)
        if not index_type.is_error and index_type != INT_TYPE:
            self._report(
                "SEM-INVALID-ARRAY-INDEX",
                "Array index must have type int",
                node.index,
                expected=INT_TYPE,
                actual=index_type,
                scope=scope,
            )
        return MiniCType(array_type.base) if array_type.kind is TypeKind.ARRAY else ERROR_TYPE

    def _function_call(self, node: FunctionCall, scope: Scope) -> MiniCType:
        argument_types = [self._expression(argument, scope) for argument in node.arguments]
        if not isinstance(node.callee, Identifier):
            self._expression(node.callee, scope)
            self._report("SEM-NOT-CALLABLE", "Call target is not a function identifier", node.callee,
                         expected="function", scope=scope)
            return ERROR_TYPE
        symbol = self._resolve(node.callee.name, node.callee, scope)
        if symbol is None:
            return ERROR_TYPE
        if symbol.kind is not SymbolKind.FUNCTION:
            self._report("SEM-NOT-CALLABLE", f"Identifier '{node.callee.name}' is not callable", node.callee,
                         identifier=node.callee.name, expected="function", actual=symbol.type, scope=scope)
            return ERROR_TYPE
        expected_types = symbol.type.parameter_types
        if len(argument_types) != len(expected_types):
            self._report(
                "SEM-FUNCTION-ARG-COUNT",
                f"Function '{symbol.name}' expects {len(expected_types)} arguments but received {len(argument_types)}",
                node,
                identifier=symbol.name,
                expected=str(len(expected_types)),
                actual=str(len(argument_types)),
                scope=scope,
            )
        for index, (expected, actual) in enumerate(zip(expected_types, argument_types), start=1):
            if not actual.is_error and not self._assignable(expected, actual):
                self._report(
                    "SEM-FUNCTION-ARG-TYPE",
                    f"Argument {index} of '{symbol.name}' expects {expected.display()}, got {actual.display()}",
                    node.arguments[index - 1],
                    identifier=symbol.name,
                    expected=expected,
                    actual=actual,
                    scope=scope,
                )
        return MiniCType(symbol.type.base)

    def _check_condition(self, node: ASTNode, scope: Scope, construct: str) -> None:
        actual = self._expression(node, scope)
        if not actual.is_error and actual != BOOL_TYPE:
            self._report(
                "SEM-TYPE-MISMATCH",
                f"{construct} condition must have type bool",
                node,
                expected=BOOL_TYPE,
                actual=actual,
                scope=scope,
            )

    def _check_return(self, node: ReturnStatement, scope: Scope) -> None:
        if self._current_return_type == VOID_TYPE:
            if node.value is not None:
                actual = self._expression(node.value, scope)
                self._report("SEM-INVALID-RETURN", "Void function cannot return a value", node,
                             expected=VOID_TYPE, actual=actual, scope=scope)
            return
        if node.value is None:
            self._report("SEM-INVALID-RETURN", "Non-void function must return a value", node,
                         expected=self._current_return_type, actual=VOID_TYPE, scope=scope)
            return
        actual = self._expression(node.value, scope)
        if not actual.is_error and not self._assignable(self._current_return_type, actual):
            self._report("SEM-INVALID-RETURN", "Return value is incompatible with the function return type",
                         node, expected=self._current_return_type, actual=actual, scope=scope)

    def _check_assignment_compatibility(
        self,
        expected: MiniCType,
        actual: MiniCType,
        node: ASTNode,
        scope: Scope,
        identifier: str | None = None,
    ) -> None:
        if expected.is_error or actual.is_error:
            return
        if actual.base is BaseType.VOID:
            self._report("SEM-VOID-VALUE-USE", "A void expression cannot be used as a value", node,
                         identifier=identifier, expected=expected, actual=actual, scope=scope)
        elif not self._assignable(expected, actual):
            self._report("SEM-TYPE-MISMATCH", f"Cannot assign {actual.display()} to {expected.display()}", node,
                         identifier=identifier, expected=expected, actual=actual, scope=scope)

    @staticmethod
    def _assignable(expected: MiniCType, actual: MiniCType) -> bool:
        if expected.kind is not TypeKind.SCALAR or actual.kind is not TypeKind.SCALAR:
            return False
        return expected.base == actual.base or (
            expected.base is BaseType.FLOAT and actual.base is BaseType.INT
        )

    @staticmethod
    def _comparable(left: MiniCType, right: MiniCType) -> bool:
        return left == right or (left.is_numeric and right.is_numeric)

    def _resolve(self, name: str, node: ASTNode, scope: Scope) -> Symbol | None:
        symbol = scope.lookup(name)
        if symbol is None:
            self._report(
                "SEM-UNDECLARED-IDENTIFIER",
                f"Identifier '{name}' is not declared in the current or enclosing scope",
                node,
                identifier=name,
                scope=scope,
            )
        return symbol

    def _report(
        self,
        code: str,
        message: str,
        node: ASTNode,
        *,
        identifier: str | None = None,
        expected: MiniCType | str | None = None,
        actual: MiniCType | str | None = None,
        scope: Scope | None = None,
    ) -> None:
        def display(value: MiniCType | str | None) -> str | None:
            return value.display() if isinstance(value, MiniCType) else value

        self.diagnostics.append(
            SemanticDiagnostic(
                phase="semantic",
                code=code,
                message=message,
                span=node.span,
                identifier=identifier,
                expected_type=display(expected),
                actual_type=display(actual),
                scope_id=scope.id if scope else None,
            )
        )


def analyze_semantics(program: Program) -> SemanticResult:
    return SemanticAnalyzer().analyze(program)


def analyze_source_semantics(source: str) -> SemanticPipelineResult:
    """Parse first and never run semantics on a recovered/invalid AST."""

    parse_result = parse(source)
    semantic_result = analyze_semantics(parse_result.ast) if parse_result.valid and parse_result.ast else None
    return SemanticPipelineResult(parse_result, semantic_result)
