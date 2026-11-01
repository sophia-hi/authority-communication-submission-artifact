"""Neutral private calculator for agent-supplied numeric expressions.

The calculator receives only expressions explicitly typed by the calling
agent.  It has no access to binders, messages, economic identities, truth
values, or policy rankings.  A wrong or incomplete expression is evaluated
exactly as written.
"""
from __future__ import annotations

import ast
import json
import operator


MAX_EXPR_LEN = 2000
MAX_BATCH = 24
MAX_ABS = 1e12
MAX_POW_EXP = 12

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
}
_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
}

CALCULATOR_TOOL = "calculate_batch"
CALCULATOR_DESCRIPTION = (
    "Privately evaluate only the numeric expressions you supply using numbers "
    "available to you from your records or messages received under the "
    "organization protocol. Supports +, -, *, /, //, **, parentheses, abs, "
    "min, and max. Percent notation and the % remainder operator are not "
    "supported. A call accepts at most 24 expressions of at most 2,000 "
    "characters each; absolute intermediate and final values may not exceed "
    "1e12, and an exponent's absolute value may not exceed 12. It cannot read "
    "binders, messages, or another agent's data; does not know company "
    "formulas or correct answers; and does not recommend or rank policies. "
    "The call is optional and does not communicate, submit, or end the "
    "current organizational turn."
)


class CalcError(ValueError):
    pass


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalcError("only_numeric_literals_allowed")
    out = float(value)
    if abs(out) > MAX_ABS:
        raise CalcError("result_out_of_range")
    return out


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        return _number(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _number(_UNARY[type(node.op)](_eval(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POW_EXP:
            raise CalcError("exponent_too_large")
        if isinstance(node.op, (ast.Div, ast.FloorDiv)) and right == 0:
            raise CalcError("division_by_zero")
        return _number(_BIN[type(node.op)](left, right))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalcError("unsupported_expression")
        fn = _FUNCS.get(node.func.id)
        if fn is None or node.keywords:
            raise CalcError("unsupported_expression")
        args = [_eval(arg) for arg in node.args]
        if node.func.id == "abs" and len(args) != 1:
            raise CalcError("unsupported_expression")
        if node.func.id in {"min", "max"} and len(args) < 2:
            raise CalcError("unsupported_expression")
        return _number(fn(*args))
    raise CalcError("unsupported_expression")


def evaluate_expression(expression: str) -> dict:
    """Return a value or a neutral error without supplying corrections."""
    expr = str(expression or "").strip()
    if not expr:
        return {"accepted": False, "error": "empty_expression"}
    if len(expr) > MAX_EXPR_LEN:
        return {"accepted": False, "error": "expression_too_long"}
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return {"accepted": False, "error": "invalid_expression"}
    except RecursionError:
        return {"accepted": False, "error": "expression_too_deep"}
    try:
        value = _eval(tree)
    except ZeroDivisionError:
        return {"accepted": False, "error": "division_by_zero"}
    except CalcError as exc:
        return {"accepted": False, "error": str(exc)}
    except RecursionError:
        return {"accepted": False, "error": "expression_too_deep"}
    except OverflowError:
        return {"accepted": False, "error": "result_out_of_range"}
    return {"accepted": True, "expression": expr, "value": value}


def coerce_expressions(raw: object) -> list[str] | dict:
    """Accept an expression list, a JSON list string, or one expression."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return [text]


def evaluate_batch(expressions: object) -> dict:
    """Evaluate independent expressions without reasoning across items."""
    items = coerce_expressions(expressions)
    if not items:
        return {"accepted": False, "error": "empty_batch", "results": []}
    if len(items) > MAX_BATCH:
        return {
            "accepted": False,
            "error": "batch_too_large",
            "max_batch": MAX_BATCH,
            "n": len(items),
            "results": [],
        }
    results = [evaluate_expression(expression) for expression in items]
    return {
        "accepted": any(row.get("accepted") for row in results),
        "n": len(results),
        "n_ok": sum(1 for row in results if row.get("accepted")),
        "results": results,
    }
