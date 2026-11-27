import ast
import csv
import io
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from ax import Client
from ax.adapter.registry import Generators
from ax.api.configs import ChoiceParameterConfig, RangeParameterConfig
from ax.core.observation import ObservationFeatures
from ax.core.parameter_constraint import ParameterConstraint
from ax.exceptions.core import UnsupportedError, UserInputError


SCHEMA_VERSION = 1
MULTI_SCHEMA_VERSION = 2
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_PROJECT_BYTES = 10 * 1024 * 1024
PARAMETER_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def blank_project(name: str = "Untitled experiment") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "parameters": [],
        "objective": {"name": "", "direction": "maximize"},
        "parameter_constraints": [],
        "runs": [],
        "recommendation_batches": [],
    }


def objectives_for(project: dict[str, Any]) -> list[dict[str, str]]:
    if "objectives" in project:
        return project["objectives"]
    objective = project.get("objective", {})
    return [objective] if objective.get("name") else []


def results_for(project: dict[str, Any], run: dict[str, Any]) -> dict[str, float]:
    if "results" in run:
        return run["results"]
    objectives = objectives_for(project)
    if objectives and "objective" in run:
        return {objectives[0]["name"]: run["objective"]}
    return {}


def ordered_table_rows(project: dict[str, Any]) -> list[tuple[str, dict[str, Any], int | None, int | None]]:
    linked_ids = {
        candidate["run_id"]
        for batch in project["recommendation_batches"]
        for candidate in batch["candidates"]
        if "run_id" in candidate
    }
    rows: list[tuple[str, dict[str, Any], int | None, int | None]] = [
        ("run", run, None, None) for run in project["runs"] if run["id"] not in linked_ids
    ]
    rows.extend(("draft", draft, None, None) for draft in project.get("draft_runs", []))
    rows.extend(
        ("candidate", candidate, batch_index, candidate_index)
        for batch_index, batch in enumerate(project["recommendation_batches"])
        for candidate_index, candidate in enumerate(batch["candidates"])
    )
    return sorted(rows, key=lambda row: row[1].get("table_order", math.inf))


def next_table_order(project: dict[str, Any]) -> int:
    rows = ordered_table_rows(project)
    for order, (_, row, _, _) in enumerate(rows):
        row["table_order"] = order
    return len(rows)


def upgrade_project(project: dict[str, Any]) -> None:
    if "objectives" in project:
        return
    objectives = objectives_for(project)
    for run in project["runs"]:
        run["results"] = results_for(project, run)
        run.pop("objective", None)
    project["objectives"] = objectives
    project.pop("objective", None)
    project["schema_version"] = MULTI_SCHEMA_VERSION


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
    


def validate_stored_parameters(values: dict[str, Any]) -> None:
    for name, value in values.items():
        if (
            not isinstance(name, str)
            or not PARAMETER_NAME_RE.fullmatch(name)
            or not (isinstance(value, str) or is_finite_number(value))
        ):
            raise ValueError("Stored parameter values must be finite numbers or strings.")


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


def parse_csv(project: dict[str, Any], data: bytes) -> list[dict[str, Any]]:
    if len(data) > MAX_CSV_BYTES:
        raise ValueError("CSV upload exceeds the 5 MB size limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV must be UTF-8 encoded.")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    fieldnames = set(reader.fieldnames)
    required = {p["name"] for p in project["parameters"]} | {o["name"] for o in objectives_for(project)}
    missing = sorted(required - fieldnames)
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(missing))

    parsed: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        values = {name: row[name] for name in required}
        try:
            parsed.append(validate_run(project, values))
        except ValueError as exc:
            raise ValueError(f"CSV row {row_number}: {exc}") from exc
    if not parsed:
        raise ValueError("CSV contains no data rows.")
    return parsed


def load_project_json(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_PROJECT_BYTES:
        raise ValueError("Project JSON exceeds the 10 MB size limit.")
    try:
        project = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise ValueError("Project file must be UTF-8 encoded.")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid project JSON: {exc.msg}") from exc
    return validate_project(project)


def ax_parameter_configs(project: dict[str, Any]) -> list[Any]:
    configs: list[Any] = []
    for parameter in project["parameters"]:
        name = parameter["name"]
        if parameter["type"] in ("continuous", "float"):
            configs.append(
                RangeParameterConfig(
                    name=name,
                    bounds=(float(parameter["bounds"][0]), float(parameter["bounds"][1])),
                    parameter_type="float",
                    scaling="linear",
                )
            )
        elif parameter["type"] in ("integer", "int"):
            configs.append(
                RangeParameterConfig(
                    name=name,
                    bounds=(int(parameter["bounds"][0]), int(parameter["bounds"][1])),
                    parameter_type="int",
                )
            )
        else:
            configs.append(
                ChoiceParameterConfig(
                    name=name,
                    values=parameter["choices"],
                    parameter_type="str",
                    is_ordered=False,
                )
            )
    return configs


def configured_client(project: dict[str, Any]) -> tuple[Client, list[tuple[dict[str, Any], dict[str, float]]]]:
    if not project["parameters"]:
        raise ValueError("Add at least one parameter before generating recommendations.")
    objectives = objectives_for(project)
    if not objectives:
        raise ValueError("Define an objective before generating recommendations.")

    validate_constraints(project)
    objective_names = {objective["name"] for objective in objectives}
    observations = []
    for run in project["runs"]:
        results = {
            name: value for name, value in results_for(project, run).items()
            if name in objective_names
        }
        if results:
            try:
                parameters = validate_parameters(project, run["parameters"])
            except ValueError as exc:
                raise ValueError(f"Run {run['id']} needs valid parameter values: {exc}") from exc
            observations.append((parameters, results))
    try:
        client = Client(random_seed=None)
        client.configure_experiment(
            name=project["name"],
            parameters=ax_parameter_configs(project),
            parameter_constraints=project["parameter_constraints"] or None,
        )
        objective_expression = ", ".join(
            f"-{objective['name']}" if objective["direction"] == "minimize" else objective["name"]
            for objective in objectives
        )
        client.configure_optimization(objective=objective_expression)

        for parameters, results in observations:
            trial_index = client.attach_trial(parameters=parameters)
            client.complete_trial(
                trial_index=trial_index,
                raw_data=results,
            )
    except Exception as exc:
        raise RuntimeError("Model setup failed. Check the project and try again.") from exc
    return client, observations


def generate_candidates(project: dict[str, Any], batch_size: int) -> list[dict[str, Any]]:
    if not 1 <= batch_size <= 100:
        raise ValueError("Batch size must be between 1 and 100.")
    client, observations = configured_client(project)
    objectives = objectives_for(project)
    objective_names = {objective["name"] for objective in objectives}
    try:
        if observations:
            # Reconstruction starts at the first node; skip the already-satisfied center node.
            client.configure_generation_strategy(
                initialize_with_center=False,
                allow_exceeding_initialization_budget=any(
                    len(results) < len(objectives) for _, results in observations
                ),
            )
        generated = client.get_next_trials(max_trials=batch_size)
    except Exception as exc:
        raise RuntimeError("Candidate generation failed. Check the project and try again.") from exc
    points = [dict(parameters) for parameters in generated.values()]
    if not points:
        return []
    try:
        predictions = client.predict(points)
    except UnsupportedError as exc:
        # Ax's initialization generators have no fitted predictive adapter.
        adapter = client._generation_strategy.adapter
        if adapter is not None and adapter.can_predict:
            raise RuntimeError("Prediction failed. Check the project and try again.") from exc
        return [{"parameters": point, "prediction_status": "model_unavailable"} for point in points]
    except Exception as exc:
        raise RuntimeError("Prediction failed. Check the project and try again.") from exc
    try:
        if len(predictions) != len(points):
            raise ValueError("Prediction count does not match candidate count.")
        candidates = []
        for point, predicted in zip(points, predictions):
            if not isinstance(predicted, dict):
                raise ValueError("Invalid prediction.")
            snapshot = {}
            for name in objective_names:
                if name in predicted:
                    mean, sigma = predicted[name]
                    if isinstance(mean, bool) or isinstance(sigma, bool):
                        raise ValueError("Invalid prediction.")
                    mean, sigma = float(mean), float(sigma)
                    if not is_finite_number(mean) or not is_finite_number(sigma) or sigma < 0:
                        raise ValueError("Invalid prediction.")
                    snapshot[name] = {"mean": mean, "sigma": sigma}
            candidates.append({"parameters": point, "predictions": snapshot})
        return candidates
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        raise RuntimeError("Ax returned invalid predictions. Check the project and try again.") from exc


def predict_candidate(project: dict[str, Any], parameters: dict[str, Any]) -> dict[str, dict[str, float]] | None:
    point = validate_parameters(project, parameters)
    client, observations = configured_client(project)
    if not observations:
        return None
    try:
        experiment = client._experiment
        adapter = Generators.BOTORCH_MODULAR(experiment=experiment, data=experiment.lookup_data())
        means, covariance = adapter.predict([ObservationFeatures(parameters=point)])
        predictions = {}
        for objective in objectives_for(project):
            name = objective["name"]
            if name in means:
                mean = float(means[name][0])
                variance = float(covariance[name][name][0])
                if not is_finite_number(mean) or not is_finite_number(variance) or variance < 0:
                    raise ValueError("Invalid prediction.")
                predictions[name] = {"mean": mean, "sigma": math.sqrt(variance)}
        return predictions
    except Exception as exc:
        raise RuntimeError("Prediction failed. Check the project and try again.") from exc


def set_candidate_parameters(candidate: dict[str, Any], parameters: dict[str, Any]) -> None:
    if candidate["parameters"] != parameters and "predictions" in candidate:
        del candidate["predictions"]
        candidate["prediction_status"] = "parameters_changed"
    candidate["parameters"] = parameters


def invalidate_predictions(project: dict[str, Any]) -> None:
    for batch in project["recommendation_batches"]:
        for candidate in batch["candidates"]:
            if "predictions" in candidate:
                del candidate["predictions"]
                candidate["prediction_status"] = "configuration_changed"


def add_run(project: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    validated = validate_run(project, values)
    run = {
        "id": len(project["runs"]) + 1,
        "parameters": {p["name"]: validated[p["name"]] for p in project["parameters"]},
    }
    results = {o["name"]: validated[o["name"]] for o in objectives_for(project) if o["name"] in validated}
    if "objectives" in project:
        run["results"] = results
    else:
        run["objective"] = results[objectives_for(project)[0]["name"]]
    while any(existing["id"] == run["id"] for existing in project["runs"]):
        run["id"] += 1
    project["runs"].append(run)
    return run


def save_multi_result(
    project: dict[str, Any], values: dict[str, Any], *, run_id: int | None,
    batch_index: int | None, candidate_index: int | None, draft_id: str | None,
    parameters: dict[str, Any] | None,
) -> None:
    candidate = None
    draft = None
    run = None
    if batch_index is not None and candidate_index is not None:
        candidate = project["recommendation_batches"][batch_index]["candidates"][candidate_index]
        run_id = candidate.get("run_id")
        current_parameters = candidate["parameters"]
    elif draft_id is not None:
        draft = next(d for d in project["draft_runs"] if d["id"] == draft_id)
        current_parameters = draft["parameters"]
    elif run_id is not None:
        run = next(r for r in project["runs"] if r["id"] == run_id)
        current_parameters = run["parameters"]
    else:
        raise ValueError("A run, draft, or recommendation is required.")
    if run_id is not None:
        run = next(r for r in project["runs"] if r["id"] == run_id)

    active_parameters = {p["name"] for p in project["parameters"]}
    validated_parameters = validate_parameters(
        project, current_parameters if parameters is None else parameters, allow_partial=True,
    )
    saved_parameters = {k: v for k, v in current_parameters.items() if k not in active_parameters}
    saved_parameters.update(validated_parameters)
    validated_results = validate_results(project, values)

    if run is None and not validated_results:
        target = candidate if candidate is not None else draft
        if candidate is not None:
            set_candidate_parameters(candidate, saved_parameters)
        else:
            target["parameters"] = saved_parameters
        return
    if run is None:
        run_id = 1
        existing_ids = {r["id"] for r in project["runs"]}
        while run_id in existing_ids:
            run_id += 1
        run = {"id": run_id, "parameters": saved_parameters, "results": validated_results}
        project["runs"].append(run)
        if candidate is not None:
            candidate["run_id"] = run_id
        else:
            if "table_order" in draft:
                run["table_order"] = draft["table_order"]
            project["draft_runs"] = [d for d in project["draft_runs"] if d["id"] != draft_id]
    else:
        active_objectives = {o["name"] for o in objectives_for(project)}
        retained_results = {k: v for k, v in run["results"].items() if k not in active_objectives}
        retained_results.update(validated_results)
        run["results"] = retained_results
        run["parameters"] = saved_parameters
    if candidate is not None:
        set_candidate_parameters(candidate, saved_parameters)
    elif run_id is not None:
        for batch in project["recommendation_batches"]:
            for linked in batch["candidates"]:
                if linked.get("run_id") == run_id:
                    set_candidate_parameters(linked, dict(saved_parameters))


def save_result(
    project: dict[str, Any], value: str | dict[str, Any], *, run_id: int | None = None,
    batch_index: int | None = None, candidate_index: int | None = None,
    draft_id: str | None = None, parameters: dict[str, Any] | None = None,
) -> None:
    if "objectives" in project:
        if not isinstance(value, dict):
            raise ValueError("Provide results by objective name.")
        save_multi_result(
            project, value, run_id=run_id, batch_index=batch_index,
            candidate_index=candidate_index, draft_id=draft_id, parameters=parameters,
        )
        return
    candidate = None
    draft = None
    if batch_index is not None and candidate_index is not None:
        candidate = project["recommendation_batches"][batch_index]["candidates"][candidate_index]
        run_id = candidate.get("run_id")
        current_parameters = candidate["parameters"]
    elif draft_id is not None:
        draft = next(draft for draft in project["draft_runs"] if draft["id"] == draft_id)
        current_parameters = draft["parameters"]
    elif run_id is not None:
        run = next(run for run in project["runs"] if run["id"] == run_id)
        current_parameters = run["parameters"]
    else:
        raise ValueError("A run, draft, or recommendation is required.")

    validated_parameters = validate_parameters(
        project, current_parameters if parameters is None else parameters,
    )
    if not value.strip() and run_id is None:
        if candidate is not None:
            set_candidate_parameters(candidate, validated_parameters)
        else:
            draft["parameters"] = validated_parameters
        return

    values = {**validated_parameters, project["objective"]["name"]: value}
    validated = validate_run(project, values)
    if run_id is None:
        run = add_run(project, values)
        if candidate is not None:
            set_candidate_parameters(candidate, validated_parameters)
            candidate["run_id"] = run["id"]
        else:
            if "table_order" in draft:
                run["table_order"] = draft["table_order"]
            project["draft_runs"] = [item for item in project["draft_runs"] if item["id"] != draft_id]
    else:
        run = next(run for run in project["runs"] if run["id"] == run_id)
        run["parameters"] = validated_parameters
        run["objective"] = validated[project["objective"]["name"]]
        if candidate is not None:
            set_candidate_parameters(candidate, validated_parameters)
        else:
            for batch in project["recommendation_batches"]:
                for linked in batch["candidates"]:
                    if linked.get("run_id") == run_id:
                        set_candidate_parameters(linked, dict(validated_parameters))


def delete_run(project: dict[str, Any], run_id: int) -> None:
    project["runs"] = [run for run in project["runs"] if run["id"] != run_id]
    for batch in project["recommendation_batches"]:
        for candidate in batch["candidates"]:
            if candidate.get("run_id") == run_id:
                del candidate["run_id"]
