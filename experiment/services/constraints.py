import ast
import math
from typing import Any

from ax.core.parameter_constraint import ParameterConstraint
from ax.exceptions.core import UserInputError


def validate_constraints(project: dict[str, Any]) -> list[ParameterConstraint]:
    numeric_names = {
        parameter["name"] for parameter in project["parameters"]
        if parameter["type"] in ("continuous", "float", "integer", "int")
    }
    constraints = []
    for expression in project.get("parameter_constraints", []):
        try:
            tree = ast.parse(expression, mode="eval")
            comparison = tree.body
            if (
                not isinstance(comparison, ast.Compare)
                or len(comparison.ops) != 1
                or not isinstance(comparison.ops[0], (ast.LtE, ast.GtE))
            ):
                raise ValueError("Expected a linear inequality using <= or >=.")
            allowed = (
                ast.Expression, ast.Compare, ast.LtE, ast.GtE, ast.BinOp, ast.UnaryOp,
                ast.Add, ast.Sub, ast.Mult, ast.Div, ast.UAdd, ast.USub,
                ast.Name, ast.Load, ast.Constant,
            )
            for node in ast.walk(tree):
                if not isinstance(node, allowed):
                    raise ValueError("Only numeric linear expressions are supported.")
                if isinstance(node, ast.Name) and node.id not in numeric_names:
                    raise ValueError("Constraints must refer to numeric parameters in the project.")
                if isinstance(node, ast.Constant) and (
                    type(node.value) not in (int, float) or not math.isfinite(node.value)
                ):
                    raise ValueError("Constraints must contain finite numeric values.")
            constraints.append(ParameterConstraint(inequality=expression))
        except (SyntaxError, UserInputError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid parameter constraint: {expression}") from exc
    return constraints
