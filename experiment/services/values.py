import math
import re
from typing import Any

from experiment.model.project import objectives_for
from experiment.services.constraints import validate_constraints

PARAMETER_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_stored_parameters(values: dict[str, Any]) -> None:
    for name, value in values.items():
        if (
            not isinstance(name, str)
            or not PARAMETER_NAME_RE.fullmatch(name)
            or not (isinstance(value, str) or is_finite_number(value))
        ):
            raise ValueError("Stored parameter values must be finite numbers or strings.")


def validate_parameters(
    project: dict[str, Any], values: dict[str, Any], *, allow_partial: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for parameter in project["parameters"]:
        name = parameter["name"]
        if name not in values or values[name] is None or values[name] == "":
            if allow_partial:
                continue
            raise ValueError(f"Missing parameter: {name}")
        raw = values[name]
        kind = parameter["type"]
        if kind in ("continuous", "float"):
            if isinstance(raw, bool):
                raise ValueError(f"{name} must be numeric.")
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"{name} must be numeric.")
            low, high = parameter["bounds"]
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}.")
        elif kind in ("integer", "int"):
            if isinstance(raw, bool):
                raise ValueError(f"{name} must be an integer.")
            try:
                value = int(raw)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"{name} must be an integer.")
            if str(raw).strip() not in (str(value), f"+{value}") and not isinstance(raw, int):
                raise ValueError(f"{name} must be an integer.")
            low, high = parameter["bounds"]
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}.")
        else:
            value = str(raw)
            if value not in parameter["choices"]:
                raise ValueError(f"{name} must be one of: {', '.join(parameter['choices'])}")
        result[name] = value

    numeric = {name: value for name, value in result.items() if isinstance(value, (int, float))}
    for expression, constraint in zip(project.get("parameter_constraints", []), validate_constraints(project)):
        # An incomplete draft cannot yet be checked against constraints involving missing values.
        if allow_partial and not set(constraint.constraint_dict).issubset(numeric):
            continue
        if not constraint.check(numeric):
            raise ValueError(f"Parameter values do not satisfy constraint: {expression}")
    return result


def validate_run(project: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    result = validate_parameters(project, values)
    result.update(validate_results(project, values))
    if not any(objective["name"] in result for objective in objectives_for(project)):
        raise ValueError("Enter at least one objective result.")
    return result


def validate_results(project: dict[str, Any], values: dict[str, Any]) -> dict[str, float]:
    result = {}
    for objective in objectives_for(project):
        name = objective["name"]
        raw = values.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{name} must be numeric.")
        if isinstance(raw, bool) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite numeric value.")
        result[name] = value
    return result
