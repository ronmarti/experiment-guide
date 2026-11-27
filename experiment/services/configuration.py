import re
from copy import deepcopy
from typing import Any, Literal

from experiment.model.project import upgrade_project
from experiment.services.runs import invalidate_predictions
from experiment.services.constraints import validate_constraints
from experiment.services.validation import validate_project

ConfigurationKind = Literal["parameter", "objective", "constraint"]


def _rename_values(project: dict[str, Any], field: str, old: str, new: str) -> None:
    if old == new:
        return
    targets = [run[field] for run in project["runs"]]
    if field == "parameters":
        targets += [candidate["parameters"] for batch in project["recommendation_batches"] for candidate in batch["candidates"]]
        targets += [draft["parameters"] for draft in project.get("draft_runs", [])]
    elif field == "results":
        targets += [
            candidate["predictions"]
            for batch in project["recommendation_batches"]
            for candidate in batch["candidates"] if "predictions" in candidate
        ]
    for values in targets:
        if old in values:
            if new in values:
                raise ValueError(f"Cannot rename {old}: stored values for {new} already exist.")
            values[new] = values.pop(old)
    if field == "parameters":
        project["parameter_constraints"] = [
            re.sub(rf"\b{re.escape(old)}\b", lambda _: new, expression)
            for expression in project["parameter_constraints"]
        ]


def save_configuration(
    project: dict[str, Any], kind: ConfigurationKind, index: int | None, fields: dict[str, str],
) -> dict[str, Any]:
    updated = deepcopy(project)
    upgrade_project(updated)
    if kind == "parameter":
        parameter_type = fields["type"]
        parameter: dict[str, Any] = {"name": fields["name"].strip(), "type": parameter_type}
        if parameter_type == "categorical":
            parameter["choices"] = [choice.strip() for choice in fields["choices"].split(",") if choice.strip()]
        else:
            convert = int if parameter_type == "integer" else float
            parameter["bounds"] = [convert(fields["lower"]), convert(fields["upper"])]
        if index is None:
            updated["parameters"].append(parameter)
            invalidate_predictions(updated)
        else:
            previous = updated["parameters"][index]
            _rename_values(updated, "parameters", previous["name"], parameter["name"])
            updated["parameters"][index] = parameter
            if {**previous, "name": parameter["name"]} != parameter:
                invalidate_predictions(updated)
    elif kind == "objective":
        objective = {"name": fields["name"].strip(), "direction": fields["direction"]}
        if index is None:
            updated["objectives"].append(objective)
        else:
            old = updated["objectives"][index]["name"]
            _rename_values(updated, "results", old, objective["name"])
            updated["objectives"][index] = objective
    elif kind == "constraint":
        expression = fields["expression"].strip()
        if index is None:
            updated["parameter_constraints"].append(expression)
        else:
            updated["parameter_constraints"][index] = expression
        validate_constraints(updated)
    else:
        raise ValueError(f"Unknown configuration kind: {kind}")
    validate_project(updated)
    return updated


def delete_configuration(project: dict[str, Any], kind: ConfigurationKind, index: int) -> dict[str, Any]:
    updated = deepcopy(project)
    upgrade_project(updated)
    key = {"parameter": "parameters", "objective": "objectives", "constraint": "parameter_constraints"}[kind]
    removed = updated[key].pop(index)
    if kind == "parameter":
        invalidate_predictions(updated)
    elif kind == "objective":
        for batch in updated["recommendation_batches"]:
            for candidate in batch["candidates"]:
                candidate.get("predictions", {}).pop(removed["name"], None)
    return updated
