from typing import Any

from experiment.model.project import MULTI_SCHEMA_VERSION, SCHEMA_VERSION
from experiment.model.table_order import ordered_table_rows
from experiment.services.constraints import validate_constraints
from experiment.services.values import (
    PARAMETER_NAME_RE, is_finite_number, validate_parameters, validate_run, validate_stored_parameters,
)


def validate_project(project: Any) -> dict[str, Any]:
    if not isinstance(project, dict):
        raise ValueError("Project JSON must contain an object.")
    if project.get("schema_version") not in (SCHEMA_VERSION, MULTI_SCHEMA_VERSION):
        raise ValueError(
            "Unsupported or missing project schema version."
        )
    if project["schema_version"] == SCHEMA_VERSION and "objectives" in project:
        raise ValueError("Version 1 projects must contain a single objective.")
    if project["schema_version"] == MULTI_SCHEMA_VERSION and "objective" in project:
        raise ValueError("Version 2 projects must use an objectives list.")
    if not isinstance(project.get("name"), str) or not project["name"].strip():
        raise ValueError("Project name must be a non-empty string.")

    parameters = project.get("parameters")
    if not isinstance(parameters, list):
        raise ValueError("Project parameters must be a list.")
    names: set[str] = set()
    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise ValueError("Each parameter must be an object.")
        name = parameter.get("name")
        kind = parameter.get("type")
        if not isinstance(name, str) or not PARAMETER_NAME_RE.fullmatch(name):
            raise ValueError(
                "Parameter names must start with a letter or underscore and contain only letters, digits, and underscores."
            )
        if name in names:
            raise ValueError(f"Duplicate parameter name: {name}")
        names.add(name)

        if kind in ("continuous", "float"):
            bounds = parameter.get("bounds")
            if (
                not isinstance(bounds, list)
                or len(bounds) != 2
                or not all(is_finite_number(v) for v in bounds)
                or bounds[0] >= bounds[1]
            ):
                raise ValueError(f"Continuous parameter {name} needs two increasing numeric bounds.")
        elif kind in ("integer", "int"):
            bounds = parameter.get("bounds")
            if (
                not isinstance(bounds, list)
                or len(bounds) != 2
                or not all(isinstance(v, int) and is_finite_number(v) for v in bounds)
                or bounds[0] >= bounds[1]
            ):
                raise ValueError(f"Integer parameter {name} needs two increasing integer bounds.")
        elif kind in ("categorical", "choice", "str"):
            choices = parameter.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError(f"Categorical parameter {name} needs at least one choice.")
            if any(not isinstance(choice, str) for choice in choices):
                raise ValueError(f"Categorical parameter {name} choices must be strings.")
            if len(set(choices)) != len(choices):
                raise ValueError(f"Categorical parameter {name} has duplicate choices.")
        else:
            raise ValueError(f"Unknown parameter type for {name}: {kind}")

    if project["schema_version"] == SCHEMA_VERSION:
        objective = project.get("objective")
        if not isinstance(objective, dict):
            raise ValueError("Objective must be an object.")
        objectives = [objective]
    else:
        objectives = project.get("objectives")
        if not isinstance(objectives, list):
            raise ValueError("Objectives must be a list.")
    for objective in objectives:
        if not isinstance(objective, dict):
            raise ValueError("Each objective must be an object.")
        objective_name = objective.get("name")
        if not isinstance(objective_name, str) or not PARAMETER_NAME_RE.fullmatch(objective_name):
            raise ValueError("Objective name must be a valid identifier.")
        if objective_name in names:
            raise ValueError("Parameter and objective names must be unique.")
        names.add(objective_name)
        if objective.get("direction") not in ("maximize", "minimize"):
            raise ValueError("Objective direction must be maximize or minimize.")

    constraints = project.get("parameter_constraints", [])
    if not isinstance(constraints, list) or any(not isinstance(c, str) for c in constraints):
        raise ValueError("Linear parameter constraints must be a list of strings.")
    if project["schema_version"] == SCHEMA_VERSION:
        validate_constraints(project)

    runs = project.get("runs")
    batches = project.get("recommendation_batches")
    if not isinstance(runs, list) or not isinstance(batches, list):
        raise ValueError("Runs and recommendation_batches must be lists.")
    runs_by_id = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("parameters"), dict):
            raise ValueError("Each run must contain parameter values.")
        if project["schema_version"] == MULTI_SCHEMA_VERSION:
            validate_stored_parameters(run["parameters"])
        run_id = run.get("id")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id in runs_by_id:
            raise ValueError("Each run must have a unique integer ID.")
        if project["schema_version"] == SCHEMA_VERSION:
            if "objective" not in run:
                raise ValueError("Each run must contain an objective result.")
            validate_run(project, {**run["parameters"], objectives[0]["name"]: run["objective"]})
        else:
            if not isinstance(run.get("results"), dict):
                raise ValueError("Each run must contain objective results.")
            for name, value in run["results"].items():
                if not isinstance(name, str) or not is_finite_number(value):
                    raise ValueError("Run results must be finite numeric values.")
        runs_by_id[run_id] = run
    linked_runs = set()
    for batch in batches:
        if not isinstance(batch, dict) or not isinstance(batch.get("candidates"), list):
            raise ValueError("Each recommendation batch must contain a candidate list.")
        for candidate in batch["candidates"]:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("parameters"), dict):
                raise ValueError("Each recommendation must contain parameter values.")
            if "predictions" in candidate:
                predictions = candidate["predictions"]
                if not isinstance(predictions, dict):
                    raise ValueError("Recommendation predictions must be an object.")
                for name, prediction in predictions.items():
                    if (
                        not isinstance(name, str)
                        or not PARAMETER_NAME_RE.fullmatch(name)
                        or not isinstance(prediction, dict)
                        or set(prediction) != {"mean", "sigma"}
                        or not is_finite_number(prediction["mean"])
                        or not is_finite_number(prediction["sigma"])
                        or prediction["sigma"] < 0
                    ):
                        raise ValueError("Recommendation predictions must have finite means and nonnegative finite sigmas.")
            if "prediction_status" in candidate and (
                candidate["prediction_status"] not in (
                    "model_unavailable", "parameters_changed", "configuration_changed", "refresh_required",
                )
                or "predictions" in candidate
            ):
                raise ValueError("Invalid recommendation prediction status.")
            if project["schema_version"] == MULTI_SCHEMA_VERSION:
                validate_stored_parameters(candidate["parameters"])
            if "run_id" in candidate:
                run_id = candidate["run_id"]
                if (
                    not isinstance(run_id, int)
                    or isinstance(run_id, bool)
                    or run_id not in runs_by_id
                    or run_id in linked_runs
                    or candidate["parameters"] != runs_by_id[run_id]["parameters"]
                ):
                    raise ValueError("A recommendation has an invalid linked run.")
                linked_runs.add(run_id)
    drafts = project.get("draft_runs", [])
    if not isinstance(drafts, list):
        raise ValueError("Draft runs must be a list.")
    draft_ids = set()
    for draft in drafts:
        if (
            not isinstance(draft, dict)
            or not isinstance(draft.get("id"), str)
            or not draft["id"]
            or draft["id"] in draft_ids
            or not isinstance(draft.get("parameters"), dict)
        ):
            raise ValueError("Each draft run must have a unique ID and parameter values.")
        if draft["parameters"] and project["schema_version"] == SCHEMA_VERSION:
            validate_parameters(project, draft["parameters"])
        elif project["schema_version"] == MULTI_SCHEMA_VERSION:
            validate_stored_parameters(draft["parameters"])
        draft_ids.add(draft["id"])
    all_rows = [
        *runs, *drafts, *(candidate for batch in batches for candidate in batch["candidates"]),
    ]
    for row in all_rows:
        if "table_order" in row and (
            not isinstance(row["table_order"], int)
            or isinstance(row["table_order"], bool)
            or row["table_order"] < 0
        ):
            raise ValueError("Table row order must be a nonnegative integer.")
    orders = [row["table_order"] for _, row, _, _ in ordered_table_rows(project) if "table_order" in row]
    if len(orders) != len(set(orders)):
        raise ValueError("Table row orders must be unique.")
    return project
