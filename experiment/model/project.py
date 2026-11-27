from collections.abc import Iterator
from typing import Any

SCHEMA_VERSION = 1
MULTI_SCHEMA_VERSION = 2


def iter_candidates(project: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for batch in project["recommendation_batches"]:
        yield from batch["candidates"]


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


def upgrade_project(project: dict[str, Any]) -> None:
    if "objectives" in project:
        return
    # Convert legacy single-objective measurements before removing their old representation.
    objectives = objectives_for(project)
    for run in project["runs"]:
        run["results"] = results_for(project, run)
        run.pop("objective", None)
    project["objectives"] = objectives
    project.pop("objective", None)
    project["schema_version"] = MULTI_SCHEMA_VERSION
