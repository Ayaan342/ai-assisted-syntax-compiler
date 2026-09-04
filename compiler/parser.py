"""PLY Yacc grammar and AST construction for the Mini-C subset."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Any

import ply.yacc as yacc

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
    Parameter,
    Program,
    ReturnStatement,
    UnaryExpression,
    UpdateExpression,
    VariableDeclaration,
    WhileStatement,
)
from .errors import LexicalError, SyntaxDiagnostic
from .error_recovery import CandidateGenerator, DelimiterTracker, RecoveryAction, TOKEN_TEXT, infer_context
from .lexer import MiniCLexer, TokenInfo
from .source_location import SourceLocation, SourceSpan


@dataclass(frozen=True, slots=True)
class ParseResult:
    ast: Program | None
    tokens: list[TokenInfo]
    lexical_errors: list[LexicalError]
    syntax_errors: list[SyntaxDiagnostic]

    @property
    def valid(self) -> bool:
        return self.ast is not None and not self.lexical_errors and not self.syntax_errors


@dataclass(frozen=True, slots=True)
class _TypeRef:
    name: str
    span: SourceSpan


class _TokenStream:
    def __init__(self, tokens: list[TokenInfo]) -> None:
        self._queue = deque(_YaccToken(token) for token in tokens)

    def token(self) -> _YaccToken | None:
        return self._queue.popleft() if self._queue else None

    def push_front(self, token: _YaccToken) -> None:
        self._queue.appendleft(token)


class _YaccToken:
    """Mutable PLY adapter that preserves the immutable public TokenInfo object."""

    def __init__(self, token: TokenInfo) -> None:
        self.type = token.type
        self.value = token.value
        self.lineno = token.line
        self.lexpos = token.offset
        self.offset = token.offset
        self.line = token.line
        self.column = token.column
        self.lexeme = token.lexeme
        self.span = token.span

    @classmethod
    def synthetic(cls, token_type: str, lexeme: str, location: SourceLocation) -> _YaccToken:
        instance = cls.__new__(cls)
        instance.type = token_type
        instance.value = lexeme
        instance.lineno = location.line
        instance.lexpos = location.offset
        instance.offset = location.offset
        instance.line = location.line
        instance.column = location.column
        instance.lexeme = lexeme
        instance.span = SourceSpan(location, location)
        return instance


class _ParseAbort(Exception):
    pass


class MiniCParser:
    """A syntax-only Mini-C parser; recovery is intentionally deferred to Phase 3."""

    tokens = MiniCLexer.tokens
    start = "program"

    # Explicit C-like precedence, from lowest to highest. The layered grammar also
    # encodes these levels; the declarations document intent and resolve dangling else.
    precedence = (
        ("nonassoc", "IFX"),
        ("nonassoc", "ELSE"),
        ("right", "ASSIGN", "PLUS_ASSIGN", "MINUS_ASSIGN", "TIMES_ASSIGN", "DIVIDE_ASSIGN", "MODULO_ASSIGN"),
        ("left", "OR"),
        ("left", "AND"),
        ("left", "EQ", "NE"),
        ("left", "LT", "LE", "GT", "GE"),
        ("left", "PLUS", "MINUS"),
        ("left", "TIMES", "DIVIDE", "MODULO"),
        ("right", "NOT", "UPLUS", "UMINUS", "PREINC", "PREDEC"),
        ("left", "POSTFIX"),
    )

    def __init__(self) -> None:
        self.source = ""
        self._tokens: list[TokenInfo] = []
        self.syntax_errors: list[SyntaxDiagnostic] = []
        self._stream = _TokenStream([])
        self._delimiter_tracker = DelimiterTracker([])
        self._candidate_generator = CandidateGenerator()
        self._diagnostic_keys: set[tuple[int, int]] = set()
        self._max_errors = 25
        self._recovery_attempts = 0
        self._parser = yacc.yacc(module=self, start=self.start, debug=False, write_tables=False)

    def parse(self, source: str) -> ParseResult:
        lexer = MiniCLexer()
        tokens, lexical_errors = lexer.scan(source)
        self.source = source
        self._tokens = tokens
        self.syntax_errors = []
        self._stream = _TokenStream(tokens)
        self._delimiter_tracker = DelimiterTracker(tokens)
        self._diagnostic_keys = set()
        self._recovery_attempts = 0
        try:
            tree = self._parser.parse(lexer=self._stream, tracking=False)
        except _ParseAbort:
            tree = None
        updated: list[SyntaxDiagnostic] = []
        for index, diagnostic in enumerate(self.syntax_errors):
            continued = tree is not None or index < len(self.syntax_errors) - 1
            action = diagnostic.recovery_action
            if action is not None:
                action = replace(action, continued=continued)
            updated.append(replace(diagnostic, parsing_continued=continued, recovery_action=action))
        self.syntax_errors = updated
        public_tree = tree if not self.syntax_errors else None
        return ParseResult(public_tree, tokens, lexical_errors, list(self.syntax_errors))

    @staticmethod
    def _span_of(value: Any) -> SourceSpan:
        if isinstance(value, (ASTNode, TokenInfo, _YaccToken, _TypeRef)):
            return value.span
        raise TypeError(f"Cannot obtain source span for {type(value).__name__}")

    @classmethod
    def _merge(cls, first: Any, last: Any) -> SourceSpan:
        return SourceSpan(cls._span_of(first).start, cls._span_of(last).end)

    def p_program(self, p):
        """program : function_list"""
        p[0] = Program(functions=p[1], span=self._merge(p[1][0], p[1][-1]))

    def p_function_list(self, p):
        """function_list : function_list function_definition
                         | function_definition"""
        p[0] = p[1] + [p[2]] if len(p) == 3 else [p[1]]

    def p_function_definition(self, p):
        """function_definition : type_specifier IDENTIFIER LPAREN parameter_list_opt RPAREN block"""
        p[0] = FunctionDefinition(
            return_type=p[1].name,
            name=p[2],
            parameters=p[4],
            body=p[6],
            span=self._merge(p[1], p[6]),
        )

    def p_function_definition_parameter_error(self, p):
        """function_definition : type_specifier IDENTIFIER LPAREN error RPAREN block"""
        p[0] = FunctionDefinition(
            return_type=p[1].name,
            name=p[2],
            parameters=[],
            body=p[6],
            span=self._merge(p[1], p[6]),
        )

    def p_type_specifier(self, p):
        """type_specifier : INT
                          | FLOAT
                          | CHAR
                          | BOOL
                          | VOID"""
        p[0] = _TypeRef(p.slice[1].lexeme, p.slice[1].span)

    def p_parameter_list_opt(self, p):
        """parameter_list_opt : parameter_list
                              | empty"""
        p[0] = [] if p[1] is None else p[1]

    def p_parameter_list(self, p):
        """parameter_list : parameter_list COMMA parameter
                          | parameter"""
        p[0] = p[1] + [p[3]] if len(p) == 4 else [p[1]]

    def p_parameter(self, p):
        """parameter : type_specifier IDENTIFIER"""
        p[0] = Parameter(
            type_name=p[1].name,
            name=p[2],
            span=self._merge(p[1], p.slice[2]),
        )

    def p_block(self, p):
        """block : LBRACE statement_list_opt RBRACE"""
        p[0] = Block(statements=p[2], span=self._merge(p.slice[1], p.slice[3]))

    def p_statement_list_opt(self, p):
        """statement_list_opt : statement_list
                              | empty"""
        p[0] = [] if p[1] is None else p[1]

    def p_statement_list(self, p):
        """statement_list : statement_list statement
                          | statement"""
        p[0] = p[1] + [p[2]] if len(p) == 3 else [p[1]]

    def p_statement(self, p):
        """statement : block
                     | declaration_statement
                     | expression_statement
                     | if_statement
                     | while_statement
                     | for_statement
                     | break_statement
                     | continue_statement
                     | return_statement"""
        p[0] = p[1]

    def p_statement_error(self, p):
        """statement : error SEMICOLON"""
        p[0] = ExpressionStatement(expression=None, span=p.slice[2].span)

    def p_block_error(self, p):
        """block : LBRACE error RBRACE"""
        p[0] = Block(statements=[], span=self._merge(p.slice[1], p.slice[3]))

    def p_declaration_statement(self, p):
        """declaration_statement : declaration_core SEMICOLON"""
        p[1].span = self._merge(p[1], p.slice[2])
        p[0] = p[1]

    def p_declaration_core_variable(self, p):
        """declaration_core : type_specifier IDENTIFIER"""
        p[0] = VariableDeclaration(
            type_name=p[1].name,
            name=p[2],
            initializer=None,
            span=self._merge(p[1], p.slice[2]),
        )

    def p_declaration_core_initialized(self, p):
        """declaration_core : type_specifier IDENTIFIER ASSIGN expression"""
        p[0] = VariableDeclaration(
            type_name=p[1].name,
            name=p[2],
            initializer=p[4],
            span=self._merge(p[1], p[4]),
        )

    def p_declaration_core_array(self, p):
        """declaration_core : type_specifier IDENTIFIER LBRACKET expression RBRACKET"""
        p[0] = ArrayDeclaration(
            type_name=p[1].name,
            name=p[2],
            size=p[4],
            span=self._merge(p[1], p.slice[5]),
        )

    def p_expression_statement(self, p):
        """expression_statement : expression SEMICOLON
                                | SEMICOLON"""
        if len(p) == 3:
            p[0] = ExpressionStatement(expression=p[1], span=self._merge(p[1], p.slice[2]))
        else:
            p[0] = ExpressionStatement(expression=None, span=p.slice[1].span)

    def p_if_statement(self, p):
        """if_statement : IF LPAREN expression RPAREN statement %prec IFX
                        | IF LPAREN expression RPAREN statement ELSE statement"""
        else_branch = p[7] if len(p) == 8 else None
        last = else_branch if else_branch is not None else p[5]
        p[0] = IfStatement(
            condition=p[3],
            then_branch=p[5],
            else_branch=else_branch,
            span=self._merge(p.slice[1], last),
        )

    def p_if_statement_error(self, p):
        """if_statement : IF LPAREN error RPAREN statement %prec IFX
                        | IF LPAREN error RPAREN statement ELSE statement"""
        condition = Literal(value=None, literal_type="error", span=self._merge(p.slice[2], p.slice[4]))
        else_branch = p[7] if len(p) == 8 else None
        last = else_branch if else_branch is not None else p[5]
        p[0] = IfStatement(
            condition=condition,
            then_branch=p[5],
            else_branch=else_branch,
            span=self._merge(p.slice[1], last),
        )

    def p_while_statement(self, p):
        """while_statement : WHILE LPAREN expression RPAREN statement"""
        p[0] = WhileStatement(condition=p[3], body=p[5], span=self._merge(p.slice[1], p[5]))

    def p_while_statement_error(self, p):
        """while_statement : WHILE LPAREN error RPAREN statement"""
        condition = Literal(value=None, literal_type="error", span=self._merge(p.slice[2], p.slice[4]))
        p[0] = WhileStatement(condition=condition, body=p[5], span=self._merge(p.slice[1], p[5]))

    def p_for_statement(self, p):
        """for_statement : FOR LPAREN for_initializer SEMICOLON optional_expression SEMICOLON optional_expression RPAREN statement"""
        p[0] = ForStatement(
            initializer=p[3],
            condition=p[5],
            update=p[7],
            body=p[9],
            span=self._merge(p.slice[1], p[9]),
        )

    def p_for_statement_error(self, p):
        """for_statement : FOR LPAREN error RPAREN statement"""
        p[0] = ForStatement(
            initializer=None,
            condition=None,
            update=None,
            body=p[5],
            span=self._merge(p.slice[1], p[5]),
        )

    def p_for_initializer(self, p):
        """for_initializer : declaration_core
                           | expression
                           | empty"""
        p[0] = p[1]

    def p_optional_expression(self, p):
        """optional_expression : expression
                               | empty"""
        p[0] = p[1]

    def p_break_statement(self, p):
        """break_statement : BREAK SEMICOLON"""
        p[0] = BreakStatement(span=self._merge(p.slice[1], p.slice[2]))

    def p_continue_statement(self, p):
        """continue_statement : CONTINUE SEMICOLON"""
        p[0] = ContinueStatement(span=self._merge(p.slice[1], p.slice[2]))

    def p_return_statement(self, p):
        """return_statement : RETURN optional_expression SEMICOLON"""
        p[0] = ReturnStatement(value=p[2], span=self._merge(p.slice[1], p.slice[3]))

    def p_return_statement_error(self, p):
        """return_statement : RETURN error SEMICOLON"""
        p[0] = ReturnStatement(value=None, span=self._merge(p.slice[1], p.slice[3]))

    def p_expression(self, p):
        """expression : assignment_expression"""
        p[0] = p[1]

    def p_assignment_expression_value(self, p):
        """assignment_expression : logical_or_expression"""
        p[0] = p[1]

    def p_assignment_expression_assign(self, p):
        """assignment_expression : unary_expression assignment_operator assignment_expression"""
        p[0] = Assignment(
            target=p[1], operator=p[2], value=p[3], span=self._merge(p[1], p[3])
        )

    def p_assignment_operator(self, p):
        """assignment_operator : ASSIGN
                               | PLUS_ASSIGN
                               | MINUS_ASSIGN
                               | TIMES_ASSIGN
                               | DIVIDE_ASSIGN
                               | MODULO_ASSIGN"""
        p[0] = p.slice[1].lexeme

    def p_logical_or_expression(self, p):
        """logical_or_expression : logical_or_expression OR logical_and_expression
                                 | logical_and_expression"""
        p[0] = self._binary_or_pass(p)

    def p_logical_and_expression(self, p):
        """logical_and_expression : logical_and_expression AND equality_expression
                                  | equality_expression"""
        p[0] = self._binary_or_pass(p)

    def p_equality_expression(self, p):
        """equality_expression : equality_expression EQ relational_expression
                               | equality_expression NE relational_expression
                               | relational_expression"""
        p[0] = self._binary_or_pass(p)

    def p_relational_expression(self, p):
        """relational_expression : relational_expression LT additive_expression
                                 | relational_expression LE additive_expression
                                 | relational_expression GT additive_expression
                                 | relational_expression GE additive_expression
                                 | additive_expression"""
        p[0] = self._binary_or_pass(p)

    def p_additive_expression(self, p):
        """additive_expression : additive_expression PLUS multiplicative_expression
                               | additive_expression MINUS multiplicative_expression
                               | multiplicative_expression"""
        p[0] = self._binary_or_pass(p)

    def p_multiplicative_expression(self, p):
        """multiplicative_expression : multiplicative_expression TIMES unary_expression
                                     | multiplicative_expression DIVIDE unary_expression
                                     | multiplicative_expression MODULO unary_expression
                                     | unary_expression"""
        p[0] = self._binary_or_pass(p)

    def _binary_or_pass(self, p):
        if len(p) == 2:
            return p[1]
        return BinaryExpression(
            operator=p.slice[2].lexeme,
            left=p[1],
            right=p[3],
            span=self._merge(p[1], p[3]),
        )

    def p_unary_expression_postfix(self, p):
        """unary_expression : postfix_expression"""
        p[0] = p[1]

    def p_unary_expression_prefix(self, p):
        """unary_expression : NOT unary_expression
                            | PLUS unary_expression %prec UPLUS
                            | MINUS unary_expression %prec UMINUS"""
        p[0] = UnaryExpression(
            operator=p.slice[1].lexeme,
            operand=p[2],
            span=self._merge(p.slice[1], p[2]),
        )

    def p_unary_expression_update(self, p):
        """unary_expression : INCREMENT unary_expression %prec PREINC
                            | DECREMENT unary_expression %prec PREDEC"""
        p[0] = UpdateExpression(
            operator=p.slice[1].lexeme,
            operand=p[2],
            prefix=True,
            span=self._merge(p.slice[1], p[2]),
        )

    def p_postfix_expression_primary(self, p):
        """postfix_expression : primary_expression"""
        p[0] = p[1]

    def p_postfix_expression_array(self, p):
        """postfix_expression : postfix_expression LBRACKET expression RBRACKET %prec POSTFIX"""
        p[0] = ArrayAccess(
            array=p[1], index=p[3], span=self._merge(p[1], p.slice[4])
        )

    def p_postfix_expression_array_error(self, p):
        """postfix_expression : postfix_expression LBRACKET error RBRACKET %prec POSTFIX"""
        index = Literal(value=None, literal_type="error", span=self._merge(p.slice[2], p.slice[4]))
        p[0] = ArrayAccess(array=p[1], index=index, span=self._merge(p[1], p.slice[4]))

    def p_postfix_expression_call(self, p):
        """postfix_expression : postfix_expression LPAREN argument_list_opt RPAREN %prec POSTFIX"""
        p[0] = FunctionCall(
            callee=p[1], arguments=p[3], span=self._merge(p[1], p.slice[4])
        )

    def p_postfix_expression_call_error(self, p):
        """postfix_expression : postfix_expression LPAREN error RPAREN %prec POSTFIX"""
        p[0] = FunctionCall(callee=p[1], arguments=[], span=self._merge(p[1], p.slice[4]))

    def p_postfix_expression_update(self, p):
        """postfix_expression : postfix_expression INCREMENT %prec POSTFIX
                              | postfix_expression DECREMENT %prec POSTFIX"""
        p[0] = UpdateExpression(
            operator=p.slice[2].lexeme,
            operand=p[1],
            prefix=False,
            span=self._merge(p[1], p.slice[2]),
        )

    def p_argument_list_opt(self, p):
        """argument_list_opt : argument_list
                             | empty"""
        p[0] = [] if p[1] is None else p[1]

    def p_argument_list(self, p):
        """argument_list : argument_list COMMA assignment_expression
                         | assignment_expression"""
        p[0] = p[1] + [p[3]] if len(p) == 4 else [p[1]]

    def p_primary_expression_identifier(self, p):
        """primary_expression : IDENTIFIER"""
        p[0] = Identifier(name=p[1], span=p.slice[1].span)

    def p_primary_expression_literal(self, p):
        """primary_expression : INTEGER_LITERAL
                              | FLOAT_LITERAL
                              | CHAR_LITERAL
                              | STRING_LITERAL
                              | TRUE
                              | FALSE"""
        literal_types = {
            "INTEGER_LITERAL": "int",
            "FLOAT_LITERAL": "float",
            "CHAR_LITERAL": "char",
            "STRING_LITERAL": "string",
            "TRUE": "bool",
            "FALSE": "bool",
        }
        p[0] = Literal(value=p[1], literal_type=literal_types[p.slice[1].type], span=p.slice[1].span)

    def p_primary_expression_grouped(self, p):
        """primary_expression : LPAREN expression RPAREN"""
        p[2].span = self._merge(p.slice[1], p.slice[3])
        p[0] = p[2]

    def p_empty(self, p):
        """empty :"""
        p[0] = None

    def p_error(self, token):
        self._recovery_attempts += 1
        if len(self.syntax_errors) >= self._max_errors or self._recovery_attempts > self._max_errors * 3:
            raise _ParseAbort

        state = getattr(self._parser, "state", None)
        if token is None:
            location = self._eof_location()
            span = SourceSpan(location, location)
            unexpected_type = None
            unexpected_lexeme = None
            message = "Unexpected end of input"
            code = "UNEXPECTED_EOF"
            nearby = self._nearby(None)
            token_index = len(self._tokens)
        else:
            span = token.span
            unexpected_type = token.type
            unexpected_lexeme = token.lexeme
            message = f"Unexpected token {token.type} ({token.lexeme!r})"
            code = "UNEXPECTED_TOKEN"
            nearby = self._nearby(token)
            token_index = next(
                (i for i, item in enumerate(self._tokens) if item.offset == token.offset),
                len(self._tokens),
            )

        expected = self._expected_tokens()
        grammar_context, enclosing = infer_context(self._tokens, token_index)
        diagnostic_id = f"SYN-{len(self.syntax_errors) + 1:04d}"
        unexpected_info = self._tokens[token_index] if token_index < len(self._tokens) else None
        candidates = self._candidate_generator.generate(
            diagnostic_id=diagnostic_id,
            tokens=self._tokens,
            index=token_index,
            unexpected=unexpected_info,
            expected=expected,
            grammar_context=grammar_context,
            eof_location=self._eof_location(),
        )
        if expected:
            message += "; expected one of: " + ", ".join(expected)

        key = (
            span.start.offset,
            -1 if token is None else (state if isinstance(state, int) else -1),
        )
        duplicate = key in self._diagnostic_keys
        self._diagnostic_keys.add(key)

        recovery, returned_token = self._choose_recovery(token, expected, candidates, grammar_context)
        if duplicate:
            return returned_token
        self.syntax_errors.append(
            SyntaxDiagnostic(
                phase="syntax",
                code=code,
                message=message,
                unexpected_token=unexpected_type,
                unexpected_lexeme=unexpected_lexeme,
                span=span,
                nearby_tokens=nearby,
                expected_tokens=expected,
                diagnostic_id=diagnostic_id,
                grammar_context=grammar_context,
                enclosing_construct=enclosing,
                parser_state=state if isinstance(state, int) else None,
                recovery_status=recovery.status,
                recovery_action=recovery,
                correction_candidates=candidates,
            )
        )
        return returned_token

    def _choose_recovery(self, token, expected, candidates, grammar_context):
        """Choose only a safe parser action; candidates remain unranked source edits."""

        replacement = next(
            (
                candidate
                for candidate in candidates
                if candidate.action.value == "REPLACE"
                and token is not None
                and token.type in {"LBRACKET", "RBRACKET"}
            ),
            None,
        )
        if replacement is not None and replacement.token_type:
            self._parser.errok()
            synthetic = _YaccToken.synthetic(
                replacement.token_type, replacement.text, token.span.start
            )
            return RecoveryAction(
                strategy="token_replacement",
                status="recovered",
                inserted_token=replacement.token_type,
            ), synthetic

        deletion = next(
            (candidate for candidate in candidates if candidate.action.value == "DELETE"), None
        )
        if deletion is not None and token is not None and deletion.span == token.span:
            self._parser.errok()
            return RecoveryAction(
                strategy="token_deletion",
                status="recovered",
                skipped_token_types=(token.type,),
            ), self._stream.token()

        insertion = next(
            (candidate for candidate in candidates if candidate.action.value == "INSERT"), None
        )
        safe_insertions = {"SEMICOLON", "RPAREN", "LPAREN", "RBRACKET", "RBRACE"}
        if insertion is not None and insertion.token_type in safe_insertions:
            if token is not None:
                self._stream.push_front(token)
                location = token.span.start
            else:
                location = self._eof_location()
            self._parser.errok()
            synthetic = _YaccToken.synthetic(
                insertion.token_type, TOKEN_TEXT[insertion.token_type], location
            )
            return RecoveryAction(
                strategy="token_insertion",
                status="recovered",
                inserted_token=insertion.token_type,
            ), synthetic

        # Returning no token activates PLY's error-token mechanism. Targeted error
        # productions then synchronize at a semicolon or closing brace.
        if token is not None and token.type in {"SEMICOLON", "RBRACE", "RPAREN", "RBRACKET"}:
            synchronization_token = token.type
        else:
            synchronization_token = {
                "if_condition": "RPAREN",
                "while_condition": "RPAREN",
                "for_header": "RPAREN",
                "function_parameter_list": "RPAREN",
                "function_call": "RPAREN",
                "array_access": "RBRACKET",
                "block": "RBRACE",
            }.get(grammar_context, "SEMICOLON")
        return RecoveryAction(
            strategy="yacc_error_production",
            status="recovering",
            synchronization_token=synchronization_token,
        ), None

    def _expected_tokens(self) -> tuple[str, ...]:
        try:
            state = self._parser.state
            names = self._parser.action[state].keys()
            return tuple(sorted(name for name in names if name not in {"error", "$end"}))
        except (AttributeError, KeyError, TypeError):
            return ()

    def _nearby(self, token: _YaccToken | None, radius: int = 3) -> tuple[dict[str, Any], ...]:
        if not self._tokens:
            return ()
        if token is None:
            start = max(0, len(self._tokens) - radius)
            selected = self._tokens[start:]
        else:
            index = next(
                (i for i, candidate in enumerate(self._tokens) if candidate.offset == token.offset),
                len(self._tokens) - 1,
            )
            selected = self._tokens[max(0, index - radius) : index + radius + 1]
        return tuple(
            {
                "type": item.type,
                "lexeme": item.lexeme,
                "line": item.line,
                "column": item.column,
                "offset": item.offset,
            }
            for item in selected
        )

    def _eof_location(self) -> SourceLocation:
        offset = len(self.source)
        line = self.source.count("\n") + 1
        last_newline = self.source.rfind("\n")
        column = offset + 1 if last_newline < 0 else offset - last_newline
        return SourceLocation(line, column, offset)


def parse(source: str) -> ParseResult:
    """Convenience function for one-shot Mini-C parsing."""

    return MiniCParser().parse(source)
