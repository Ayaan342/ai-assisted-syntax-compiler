from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai.semantic_context import build_semantic_contexts
from compiler.ast_nodes import BinaryExpression, ExpressionStatement
from compiler.parser import parse
from compiler.semantic_analyzer import analyze_semantics, analyze_source_semantics
from compiler.symbol_table import (
    BaseType,
    ScopeKind,
    SymbolKind,
    TypeKind,
    pretty_symbol_table,
)


def analyze(source: str):
    result = analyze_source_semantics(source)
    assert result.parse_result.valid, result.parse_result.syntax_errors
    assert result.semantic_result is not None
    return result.semantic_result


def codes(source: str) -> list[str]:
    return [item.code for item in analyze(source).diagnostics]


def test_global_variable_registration() -> None:
    result = analyze("int total=1; int main(){return total;}")
    symbol = result.symbol_table.root.lookup_local("total")
    assert symbol is not None
    assert symbol.kind is SymbolKind.VARIABLE and symbol.type.base is BaseType.INT


def test_global_array_registration() -> None:
    result = analyze("float values[5]; int main(){return 0;}")
    symbol = result.symbol_table.root.lookup_local("values")
    assert symbol is not None and symbol.kind is SymbolKind.ARRAY
    assert symbol.type.kind is TypeKind.ARRAY and symbol.array_size == 5


def test_function_registration() -> None:
    result = analyze("int add(int a,int b){return a+b;}")
    symbol = result.symbol_table.root.lookup_local("add")
    assert symbol is not None and symbol.kind is SymbolKind.FUNCTION
    assert symbol.type.display() == "function(int, int) -> int"


def test_parameter_registration() -> None:
    result = analyze("int add(int a,float b){return a;}")
    scope = result.symbol_table.root.children[0]
    assert scope.symbols["a"].kind is SymbolKind.PARAMETER
    assert scope.symbols["b"].type.base is BaseType.FLOAT


def test_local_variable_registration() -> None:
    result = analyze("int main(){int x=1; return x;}")
    function_scope = result.symbol_table.root.children[0]
    assert function_scope.symbols["x"].kind is SymbolKind.VARIABLE


def test_nested_block_scope() -> None:
    result = analyze("int main(){int x=1; {float y=2.0;} return x;}")
    function_scope = result.symbol_table.root.children[0]
    block = function_scope.children[0]
    assert block.kind is ScopeKind.BLOCK
    assert "y" in block.symbols and "y" not in function_scope.symbols


def test_valid_shadowing() -> None:
    result = analyze("int x=1; int main(){float x=2.0; {bool x=true;} return 0;}")
    assert result.success
    global_x = result.symbol_table.root.symbols["x"]
    local_x = result.symbol_table.root.children[0].symbols["x"]
    inner_x = result.symbol_table.root.children[0].children[0].symbols["x"]
    assert [global_x.type.base, local_x.type.base, inner_x.type.base] == [
        BaseType.INT, BaseType.FLOAT, BaseType.BOOL
    ]


def test_duplicate_declaration_same_scope() -> None:
    assert "SEM-DUPLICATE-DECLARATION" in codes("int main(){int x; float x; return 0;}")


def test_duplicate_parameter() -> None:
    assert "SEM-DUPLICATE-DECLARATION" in codes("int f(int x,float x){return 0;}")


def test_global_variable_function_collision() -> None:
    assert "SEM-DUPLICATE-DECLARATION" in codes("int x; int x(int a){return a;}")


def test_undeclared_identifier() -> None:
    diagnostics = analyze("int main(){x=10; return 0;}").diagnostics
    error = next(item for item in diagnostics if item.code == "SEM-UNDECLARED-IDENTIFIER")
    assert error.identifier == "x"
    assert error.phase == "semantic"


def test_use_of_outer_scope_variable() -> None:
    assert analyze("int main(){int x=1; {x=2;} return x;}").success


def test_inner_scope_variable_not_visible_outside() -> None:
    assert "SEM-UNDECLARED-IDENTIFIER" in codes("int main(){{int x=1;} return x;}")


def test_use_before_declaration_is_undeclared() -> None:
    assert "SEM-UNDECLARED-IDENTIFIER" in codes("int main(){x=1; int x; return 0;}")


def test_valid_int_assignment() -> None:
    assert analyze("int main(){int x; x=10; return x;}").success


def test_valid_int_to_float_widening() -> None:
    assert analyze("float f(){int x=1; float y=x; y=2; return y;}").success


def test_invalid_float_to_int_assignment() -> None:
    assert "SEM-TYPE-MISMATCH" in codes("int main(){int x; x=3.14; return x;}")


def test_invalid_bool_assignment() -> None:
    assert "SEM-TYPE-MISMATCH" in codes("int main(){bool active; active=10; return 0;}")


def test_invalid_string_initializer() -> None:
    assert "SEM-TYPE-MISMATCH" in codes('int main(){int x="hello"; return 0;}')


def test_arithmetic_type_inference() -> None:
    parsed = parse("float main(){int a=1; float b=2.0; a+b; return a+b;}")
    assert parsed.ast is not None
    result = analyze_semantics(parsed.ast)
    expression_statement = parsed.ast.functions[0].body.statements[2]
    assert isinstance(expression_statement, ExpressionStatement)
    assert result.expression_types[id(expression_statement.expression)].base is BaseType.FLOAT


@pytest.mark.parametrize(
    "expression",
    ["true + 5", "false * 2", "'A' - 1"],
)
def test_invalid_arithmetic_operands(expression: str) -> None:
    assert "SEM-TYPE-MISMATCH" in codes(f"int main(){{{expression}; return 0;}}")


def test_relational_expression_returns_bool() -> None:
    parsed = parse("int main(){1 < 2.0; return 0;}")
    assert parsed.ast is not None
    result = analyze_semantics(parsed.ast)
    node = parsed.ast.functions[0].body.statements[0].expression
    assert isinstance(node, BinaryExpression)
    assert result.expression_types[id(node)].base is BaseType.BOOL


def test_invalid_relational_operands() -> None:
    assert "SEM-TYPE-MISMATCH" in codes("int main(){true < false; return 0;}")


def test_valid_equality_with_numeric_promotion() -> None:
    assert analyze("int main(){bool same=1==2.0; return 0;}").success


def test_invalid_equality_types() -> None:
    assert "SEM-TYPE-MISMATCH" in codes("int main(){bool same=true==1; return 0;}")


def test_valid_logical_expression() -> None:
    assert analyze("int main(){bool a=true; bool b=false; bool c=a&&b||!a; return 0;}").success


def test_invalid_logical_expression() -> None:
    assert "SEM-TYPE-MISMATCH" in codes("int main(){int x=1; bool y=x&&true; return 0;}")


def test_unary_not_type_checking() -> None:
    assert "SEM-TYPE-MISMATCH" in codes("int main(){int x=1; bool y=!x; return 0;}")


@pytest.mark.parametrize("expression", ["++x", "x--"])
def test_valid_update_expression(expression: str) -> None:
    assert analyze(f"int main(){{int x=1; {expression}; return x;}}").success


@pytest.mark.parametrize("expression", ["true++", "(5+2)++"])
def test_invalid_update_operand(expression: str) -> None:
    assert "SEM-INVALID-ASSIGNMENT" in codes(f"int main(){{{expression}; return 0;}}")


def test_invalid_bool_compound_assignment() -> None:
    assert "SEM-INVALID-ASSIGNMENT" in codes("int main(){bool x=true; x+=1; return 0;}")


def test_compound_assignment_rejects_narrowing() -> None:
    assert "SEM-TYPE-MISMATCH" in codes("int main(){int x=1; x+=2.5; return x;}")


def test_valid_function_call() -> None:
    assert analyze("int add(int a,int b){return a+b;} int main(){return add(1,2);}").success


def test_wrong_function_argument_count() -> None:
    assert "SEM-FUNCTION-ARG-COUNT" in codes(
        "int add(int a,int b){return a+b;} int main(){return add(1);}"
    )


def test_wrong_function_argument_type() -> None:
    assert "SEM-FUNCTION-ARG-TYPE" in codes(
        "int add(int a,int b){return a+b;} int main(){return add(true,2);}"
    )


def test_int_argument_widens_to_float_parameter() -> None:
    assert analyze("float f(float x){return x;} int main(){f(1); return 0;}").success


def test_forward_function_call() -> None:
    assert analyze("int main(){return add(1,2);} int add(int a,int b){return a+b;}").success


def test_calling_variable_is_invalid() -> None:
    assert "SEM-NOT-CALLABLE" in codes("int main(){int x=1; x(); return 0;}")


def test_undeclared_function() -> None:
    assert "SEM-UNDECLARED-IDENTIFIER" in codes("int main(){missing(1); return 0;}")


def test_valid_return() -> None:
    assert analyze("int main(){return 0;} void work(){return;}").success


def test_missing_return_value_non_void() -> None:
    assert "SEM-INVALID-RETURN" in codes("int main(){return;}")


def test_value_returned_from_void_function() -> None:
    assert "SEM-INVALID-RETURN" in codes("void work(){return 5;}")


def test_wrong_return_type() -> None:
    assert "SEM-INVALID-RETURN" in codes("int main(){return 3.14;}")


def test_int_return_widens_to_float() -> None:
    assert analyze("float value(){return 1;}").success


def test_void_function_value_use() -> None:
    assert "SEM-VOID-VALUE-USE" in codes("void work(){return;} int main(){int x=work(); return 0;}")


def test_valid_array_access_and_assignment() -> None:
    assert analyze("int main(){int arr[10]; arr[0]=5; int x=arr[2]; return x;}").success


def test_indexing_scalar_as_array() -> None:
    assert "SEM-INVALID-ARRAY-USE" in codes("int main(){int x=0; x[0]=5; return x;}")


def test_non_int_array_index() -> None:
    assert "SEM-INVALID-ARRAY-INDEX" in codes("int main(){int arr[10]; arr[2.5]=5; return 0;}")


def test_array_cannot_be_scalar_value() -> None:
    assert "SEM-INVALID-ARRAY-USE" in codes("int main(){int arr[10]; int x=arr; return 0;}")


def test_array_size_must_be_int() -> None:
    assert "SEM-INVALID-ARRAY-INDEX" in codes("int main(){int arr[2.5]; return 0;}")


def test_break_inside_loop() -> None:
    assert analyze("int main(){while(true){break;} return 0;}").success


def test_break_outside_loop() -> None:
    assert "SEM-BREAK-OUTSIDE-LOOP" in codes("int main(){break; return 0;}")


def test_continue_inside_loop() -> None:
    assert analyze("int main(){for(;;){continue;} return 0;}").success


def test_continue_outside_loop() -> None:
    assert "SEM-CONTINUE-OUTSIDE-LOOP" in codes("int main(){continue; return 0;}")


@pytest.mark.parametrize(
    "statement",
    ["if(true){}", "while(false){}", "for(;true;){}"],
)
def test_valid_boolean_conditions(statement: str) -> None:
    assert analyze(f"int main(){{{statement} return 0;}}").success


@pytest.mark.parametrize(
    "statement",
    ["if(1){}", "while(2.0){}", "for(;3;){}"],
)
def test_invalid_condition_types(statement: str) -> None:
    assert "SEM-TYPE-MISMATCH" in codes(f"int main(){{{statement} return 0;}}")


def test_for_initializer_scope_does_not_leak() -> None:
    assert "SEM-UNDECLARED-IDENTIFIER" in codes(
        "int main(){for(int i=0;i<1;i++){} return i;}"
    )


def test_symbol_table_serialization() -> None:
    table = analyze("int g=1; int main(){int x=2; {bool y=true;} return x;}").symbol_table
    payload = table.to_dict()
    json.dumps(payload)
    assert payload["root"]["kind"] == "global"
    assert payload["root"]["children"][0]["children"][0]["symbols"][0]["name"] == "y"


def test_symbol_table_pretty_printer() -> None:
    table = analyze("int main(){int x=2; return x;}").symbol_table
    rendered = pretty_symbol_table(table)
    assert "GLOBAL [global]" in rendered
    assert "FUNCTION main [function]" in rendered
    assert "x : int [variable]" in rendered


def test_semantic_diagnostic_serialization() -> None:
    error = analyze("int main(){x=1; return 0;}").diagnostics[0]
    payload = error.to_dict()
    json.dumps(payload)
    assert payload["phase"] == "semantic"
    assert payload["code"] == "SEM-UNDECLARED-IDENTIFIER"
    assert payload["scope_id"] is not None


def test_ai_ready_semantic_context() -> None:
    result = analyze("int main(){int x=1; bool y=x; return 0;}")
    context = build_semantic_contexts(result)[0]
    payload = context.to_dict()
    json.dumps(payload)
    assert payload["expected_type"] == "bool"
    assert any(item["name"] == "x" for item in payload["visible_identifiers"])


def test_valid_existing_demo_has_no_semantic_errors() -> None:
    source = (Path(__file__).parents[1] / "examples" / "valid" / "demo.mc").read_text(encoding="utf-8")
    result = analyze(source)
    assert result.success


def test_existing_ast_output_remains_structurally_compatible() -> None:
    parsed = parse("int main(){int x=1; return x;}")
    assert parsed.ast is not None
    assert parsed.ast.functions[0].body.statements[0].name == "x"
    assert parsed.ast.globals == []


def test_existing_recovery_still_reports_multiple_errors() -> None:
    source = (Path(__file__).parents[1] / "examples" / "invalid" / "multiple_errors.mc").read_text(encoding="utf-8")
    result = analyze_source_semantics(source)
    assert len(result.parse_result.syntax_errors) == 4
    assert result.semantic_result is None


def test_malformed_syntax_skips_semantic_analysis() -> None:
    result = analyze_source_semantics("int main(){int x=; y=1;}")
    assert result.parse_result.syntax_errors
    assert result.semantic_result is None


def test_multiple_semantic_errors_do_not_stop_analysis() -> None:
    source = (Path(__file__).parents[1] / "examples" / "invalid" / "semantic_errors.mc").read_text(encoding="utf-8")
    result = analyze(source)
    assert len(result.diagnostics) == 6
    assert {item.code for item in result.diagnostics} >= {
        "SEM-DUPLICATE-DECLARATION",
        "SEM-UNDECLARED-IDENTIFIER",
        "SEM-FUNCTION-ARG-COUNT",
        "SEM-BREAK-OUTSIDE-LOOP",
        "SEM-INVALID-RETURN",
    }

