"""Trusted worker reads a fixed fixture artifact and tests its bounded expression."""

import ast
import json
import sys
from pathlib import Path

from catalog import get_task
from policy import check_cases, parse


def verify(path, task_id, split):
    task = get_task(task_id)
    text = Path(path).read_text(encoding="utf-8")
    if len(text) > 2000:
        raise ValueError("Artifact too large")
    tree = ast.parse(text)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Expected one function")
    fn = tree.body[0]
    if (
        fn.name != task["function"]
        or [a.arg for a in fn.args.args] != task["args"]
        or fn.decorator_list
        or len(fn.body) != 1
        or not isinstance(fn.body[0], ast.Return)
    ):
        raise ValueError("Patch changed the function contract")
    expression = ast.unparse(fn.body[0].value)
    parse(expression, task["args"])
    return check_cases(expression, task, split)


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1], sys.argv[2], sys.argv[3])))
