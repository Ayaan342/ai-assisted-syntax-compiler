from __future__ import annotations

from pathlib import Path

import pytest

from compiler.ast_nodes import (
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
    Identifier,
    IfStatement,
    Literal,
    ReturnStatement,
    UnaryExpression,
    UpdateExpression,
    VariableDeclaration,
    WhileStatement,
    pretty_ast,
)
from compiler.parser import MiniCParser, parse


def valid(source: str):
    result = parse(source)
    assert result.lexical_errors == []
    assert result.syntax_errors == []
    assert result.ast is not None
    return result.ast


def body(source: str) -> list:
    return valid(source).functions[0].body.statements


def expression(source: str):
    statement = body(f"int main() {{ {source}; }}")[0]
    assert isinstance(statement, ExpressionStatement)
    return statement.expression


def test_simple_function() -> None:
    tree = valid("int main() { return 0; }")
    assert tree.functions[0].name == "main"
    assert tree.functions[0].return_type == "int"
    assert tree.span.start.line == 1


def test_multiple_functions() -> None:
    tree = valid("int one(){return 1;} int two(){return 2;}")
    assert [function.name for function in tree.functions] == ["one", "two"]


def test_function_parameters() -> None:
    tree = valid("float average(float a, float b) { return (a + b) / 2; }")
    function = tree.functions[0]
    assert [(parameter.type_name, parameter.name) for parameter in function.parameters] == [
        ("float", "a"), ("float", "b")
    ]


def test_variable_declaration() -> None:
    statement = body("int main(){ int x; }")[0]
    assert isinstance(statement, VariableDeclaration)
    assert (statement.type_name, statement.name, statement.initializer) == ("int", "x", None)


def test_initialized_declaration() -> None:
    statement = body("int main(){ float value = 3.14; }")[0]
    assert isinstance(statement, VariableDeclaration)
    assert isinstance(statement.initializer, Literal)
    assert statement.initializer.value == 3.14


def test_array_declaration() -> None:
    statement = body("int main(){ int values[5]; }")[0]
    assert isinstance(statement, ArrayDeclaration)
    assert statement.name == "values"
    assert isinstance(statement.size, Literal) and statement.size.value == 5


def test_array_access() -> None:
    node = expression("x = values[i]")
    assert isinstance(node, Assignment)
    assert isinstance(node.value, ArrayAccess)
    assert isinstance(node.value.index, Identifier)


def test_assignment() -> None:
    node = expression("x = 20")
    assert isinstance(node, Assignment)
    assert node.operator == "="
    assert isinstance(node.target, Identifier)


@pytest.mark.parametrize("operator", ["+=", "-=", "*=", "/=", "%="])
def test_compound_assignments(operator: str) -> None:
    node = expression(f"x {operator} 2")
    assert isinstance(node, Assignment)
    assert node.operator == operator


def test_arithmetic_precedence() -> None:
    node = expression("a + b * c")
    assert isinstance(node, BinaryExpression) and node.operator == "+"
    assert isinstance(node.right, BinaryExpression) and node.right.operator == "*"


def test_parentheses_override_precedence() -> None:
    node = expression("(a + b) * c")
    assert isinstance(node, BinaryExpression) and node.operator == "*"
    assert isinstance(node.left, BinaryExpression) and node.left.operator == "+"


def test_relational_expression() -> None:
    node = expression("a + 1 <= b * 2")
    assert isinstance(node, BinaryExpression) and node.operator == "<="
    assert isinstance(node.left, BinaryExpression) and node.left.operator == "+"


def test_equality_expression() -> None:
    node = expression("a < b == c != d")
    assert isinstance(node, BinaryExpression) and node.operator == "!="
    assert isinstance(node.left, BinaryExpression) and node.left.operator == "=="


def test_logical_expression_precedence() -> None:
    node = expression("a < b || c != d && valid")
    assert isinstance(node, BinaryExpression) and node.operator == "||"
    assert isinstance(node.right, BinaryExpression) and node.right.operator == "&&"


@pytest.mark.parametrize("source,operator", [("!valid", "!"), ("-x", "-"), ("+x", "+")])
def test_unary_operators(source: str, operator: str) -> None:
    node = expression(source)
    assert isinstance(node, UnaryExpression)
    assert node.operator == operator


@pytest.mark.parametrize("source,operator", [("++i", "++"), ("--i", "--")])
def test_prefix_increment_decrement(source: str, operator: str) -> None:
    node = expression(source)
    assert isinstance(node, UpdateExpression)
    assert (node.operator, node.prefix) == (operator, True)


@pytest.mark.parametrize("source,operator", [("i++", "++"), ("i--", "--")])
def test_postfix_increment_decrement(source: str, operator: str) -> None:
    node = expression(source)
    assert isinstance(node, UpdateExpression)
    assert (node.operator, node.prefix) == (operator, False)


def test_assignment_is_right_associative() -> None:
    node = expression("x = y = 10")
    assert isinstance(node, Assignment)
    assert isinstance(node.value, Assignment)
    assert isinstance(node.value.target, Identifier) and node.value.target.name == "y"


def test_if_statement() -> None:
    statement = body("int main(){ if (x > 5) { x++; } }")[0]
    assert isinstance(statement, IfStatement)
    assert statement.else_branch is None
    assert isinstance(statement.then_branch, Block)


def test_if_else_statement() -> None:
    statement = body("int main(){ if (x) x++; else x--; }")[0]
    assert isinstance(statement, IfStatement)
    assert isinstance(statement.else_branch, ExpressionStatement)


def test_else_if_chain() -> None:
    statement = body("int main(){ if(x>1){x++;} else if(x==1){x=0;} else{x--;} }")[0]
    assert isinstance(statement, IfStatement)
    assert isinstance(statement.else_branch, IfStatement)
    assert isinstance(statement.else_branch.else_branch, Block)


def test_dangling_else_binds_to_nearest_if() -> None:
    outer = body("int main(){ if(a) if(b) x++; else x--; }")[0]
    assert isinstance(outer, IfStatement) and outer.else_branch is None
    assert isinstance(outer.then_branch, IfStatement)
    assert outer.then_branch.else_branch is not None


def test_nested_if() -> None:
    outer = body("int main(){ if(a){ if(b){ return 1; } } }")[0]
    assert isinstance(outer, IfStatement)
    assert isinstance(outer.then_branch.statements[0], IfStatement)


def test_while_loop() -> None:
    statement = body("int main(){ while (x < 10) { x++; } }")[0]
    assert isinstance(statement, WhileStatement)
    assert isinstance(statement.body, Block)


def test_for_with_declaration_initializer() -> None:
    statement = body("int main(){ for(int i=0; i<10; i++){ x += i; } }")[0]
    assert isinstance(statement, ForStatement)
    assert isinstance(statement.initializer, VariableDeclaration)
    assert isinstance(statement.condition, BinaryExpression)
    assert isinstance(statement.update, UpdateExpression)


def test_for_with_expression_initializer() -> None:
    statement = body("int main(){ int i; for(i=0; i<10; i++) x += i; }")[1]
    assert isinstance(statement, ForStatement)
    assert isinstance(statement.initializer, Assignment)


def test_for_allows_empty_clauses() -> None:
    statement = body("int main(){ for(;;) break; }")[0]
    assert isinstance(statement, ForStatement)
    assert statement.initializer is statement.condition is statement.update is None


def test_break_and_continue() -> None:
    loop = body("int main(){ while(true){ if(x) break; continue; } }")[0]
    assert isinstance(loop.body.statements[0].then_branch, BreakStatement)
    assert isinstance(loop.body.statements[1], ContinueStatement)


def test_return_with_expression() -> None:
    statement = body("int main(){ return x + 1; }")[0]
    assert isinstance(statement, ReturnStatement)
    assert isinstance(statement.value, BinaryExpression)


def test_empty_return() -> None:
    statement = body("void process(){ return; }")[0]
    assert isinstance(statement, ReturnStatement)
    assert statement.value is None


def test_function_call() -> None:
    node = expression("add(5, 10)")
    assert isinstance(node, FunctionCall)
    assert len(node.arguments) == 2


def test_nested_function_call_expression() -> None:
    node = expression("max(add(1, 2), values[getIndex()])")
    assert isinstance(node, FunctionCall)
    assert isinstance(node.arguments[0], FunctionCall)
    assert isinstance(node.arguments[1], ArrayAccess)
    assert isinstance(node.arguments[1].index, FunctionCall)


def test_nested_blocks_and_empty_statement() -> None:
    statements = body("int main(){ { int x; { x = 1; } } ; }")
    assert isinstance(statements[0], Block)
    assert isinstance(statements[0].statements[1], Block)
    assert isinstance(statements[1], ExpressionStatement) and statements[1].expression is None


def test_all_literal_kinds() -> None:
    statements = body("int main(){ 1; 2.5; 'A'; \"hi\"; true; false; }")
    assert [statement.expression.literal_type for statement in statements] == [
        "int", "float", "char", "string", "bool", "bool"
    ]


def test_existing_demo_program() -> None:
    source = (Path(__file__).parents[1] / "examples" / "valid" / "demo.mc").read_text(encoding="utf-8")
    result = parse(source)
    assert result.valid
    assert result.ast is not None
    assert [function.name for function in result.ast.functions] == ["max", "main"]


def test_ast_serialization_and_pretty_printing() -> None:
    tree = valid("int main(){ int x=1; return x; }")
    payload = tree.to_dict()
    rendered = pretty_ast(tree)
    assert payload["node"] == "Program"
    assert payload["functions"][0]["body"]["statements"][0]["node"] == "VariableDeclaration"
    assert "FunctionDefinition(main: int)" in rendered
    assert "ReturnStatement" in rendered


def test_malformed_syntax_produces_structured_diagnostic() -> None:
    result = parse("int main(){ int x = ; return 0; }")
    assert result.ast is None
    assert len(result.syntax_errors) == 1
    error = result.syntax_errors[0]
    assert error.phase == "syntax"
    assert error.code == "UNEXPECTED_TOKEN"
    assert error.unexpected_token == "SEMICOLON"
    assert error.unexpected_lexeme == ";"
    assert error.line == 1 and error.column > 1
    assert error.nearby_tokens
    assert error.to_dict()["span"]["start"]["offset"] == error.span.start.offset


def test_eof_syntax_error_does_not_crash() -> None:
    parser = MiniCParser()
    result = parser.parse("int main(){ if (true) { return 0;")
    assert result.ast is None
    assert len(result.syntax_errors) == 1
    error = result.syntax_errors[0]
    assert error.code == "UNEXPECTED_EOF"
    assert error.unexpected_token is None
    assert error.span.start.offset == len("int main(){ if (true) { return 0;")


def test_parser_instance_can_be_reused_after_an_error() -> None:
    parser = MiniCParser()
    assert parser.parse("int main( {").ast is None
    second = parser.parse("int main(){ return 0; }")
    assert second.valid

