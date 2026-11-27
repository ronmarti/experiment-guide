from typing import Any

from experiment.model.project import objectives_for
from experiment.services.values import validate_parameters, validate_results, validate_run


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
