"""Bounded expression language: interpret an allowlist, never eval/exec model code."""

import ast
import operator


class PolicyError(ValueError):
    pass


BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
NODES = (
    ast.Expression,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.And,
    ast.Or,
    ast.Not,
    ast.USub,
    ast.UAdd,
    *BIN,
    *CMP,
)


def parse(expression, names):
    if (
        not isinstance(expression, str)
        or len(expression) > 240
        or "\n" in expression
        or "\r" in expression
    ):
        raise PolicyError("A patch must be one expression of at most 240 characters.")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise PolicyError("Invalid expression syntax") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 80:
        raise PolicyError("Expression is too complex")
    for node in nodes:
        if not isinstance(node, NODES):
            raise PolicyError(f"Blocked syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in {*names, "min", "max"}:
            raise PolicyError(f"Name not allowed: {node.id}")
        if isinstance(node, ast.Constant) and (
            type(node.value) not in (int, bool) or abs(node.value) > 1000000
        ):
            raise PolicyError("Only bounded integer and boolean constants are allowed")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name)
            or node.func.id not in ("min", "max")
            or node.keywords
            or not 2 <= len(node.args) <= 4
        ):
            raise PolicyError(
                "Only min/max with two to four positional arguments are allowed"
            )
    return tree


def evaluate(expression, values):
    tree = parse(expression, values)

    def bound(v):
        if type(v) not in (int, float, bool) or abs(v) > 10**12:
            raise PolicyError("Result exceeds numeric bounds")
        return v

    def visit(n, depth=0):
        if depth > 24:
            raise PolicyError("Expression depth limit exceeded")
        go = lambda child: visit(child, depth + 1)
        if isinstance(n, ast.Expression):
            return go(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in values:
                raise PolicyError("Function names cannot be used as values")
            return bound(values[n.id])
        if isinstance(n, ast.BinOp):
            a, b = go(n.left), go(n.right)
            if isinstance(n.op, ast.Pow) and (
                type(b) is not int or not 0 <= b <= 8 or abs(a) > 100
            ):
                raise PolicyError("Power operation exceeds bounds")
            return bound(BIN[type(n.op)](a, b))
        if isinstance(n, ast.UnaryOp):
            v = go(n.operand)
            return (
                not v
                if isinstance(n.op, ast.Not)
                else bound(-v if isinstance(n.op, ast.USub) else +v)
            )
        if isinstance(n, ast.BoolOp):
            result = go(n.values[0])
            for next_value in n.values[1:]:
                if isinstance(n.op, ast.And) and not result:
                    return result
                if isinstance(n.op, ast.Or) and result:
                    return result
                result = go(next_value)
            return result
        if isinstance(n, ast.Compare):
            left = go(n.left)
            for op, right_node in zip(n.ops, n.comparators):
                right = go(right_node)
                if not CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.IfExp):
            return go(n.body) if go(n.test) else go(n.orelse)
        if isinstance(n, ast.Call):
            return bound((min if n.func.id == "min" else max)(go(x) for x in n.args))
        raise PolicyError("Unsupported syntax")

    return visit(tree)


def check_cases(expression, task, split):
    rows = []
    for args, expected in task[split]:
        try:
            actual = evaluate(expression, dict(zip(task["args"], args)))
            ok = actual == expected and (
                type(actual) is bool if type(expected) is bool else type(actual) is int
            )
            rows.append(
                {
                    "inputs": dict(zip(task["args"], args)),
                    "expected": expected,
                    "actual": actual,
                    "passed": ok,
                }
            )
        except (ValueError, ArithmeticError, RecursionError) as exc:
            rows.append(
                {
                    "inputs": dict(zip(task["args"], args)),
                    "expected": expected,
                    "error": str(exc)[:200],
                    "passed": False,
                }
            )
    return {"passed": sum(r["passed"] for r in rows), "total": len(rows), "cases": rows}
