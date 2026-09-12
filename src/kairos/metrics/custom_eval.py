from __future__ import annotations

import ast

from simpleeval import InvalidExpression as _SimpleEvalInvalid
from simpleeval import SimpleEval


class InvalidExpression(Exception):
    pass


def extract_metric_refs(expression: str) -> set[str]:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise InvalidExpression(str(exc)) from exc
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def evaluate_expression(expression: str, values: dict[str, float]) -> float:
    # names=values is the only source of identifiers; functions={} disables every
    # function call (including simpleeval's own defaults like int()/str()) -- this
    # expression is arithmetic over existing metric values, nothing else, ever
    evaluator = SimpleEval(names=values)
    evaluator.functions = {}
    try:
        result = evaluator.eval(expression)
    except _SimpleEvalInvalid as exc:
        raise InvalidExpression(str(exc)) from exc
    if not isinstance(result, int | float) or isinstance(result, bool):
        raise InvalidExpression("expression did not evaluate to a number")
    return float(result)
