from typing import Any

from experiment.model.project import iter_candidates, objectives_for
from experiment.services.values import validate_parameters, validate_results, validate_run


def set_candidate_parameters(candidate: dict[str, Any], parameters: dict[str, Any]) -> None:
    if candidate["parameters"] != parameters and "predictions" in candidate:
        del candidate["predictions"]
        candidate["prediction_status"] = "parameters_changed"
    candidate["parameters"] = parameters


def invalidate_predictions(project: dict[str, Any]) -> None:
    for candidate in iter_candidates(project):
        if "predictions" not in candidate:
            continue
        del candidate["predictions"]
        candidate["prediction_status"] = "configuration_changed"


class RunService:
    """Manage runs and synchronize their linked recommendation data in place."""

    def add(self, project: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        """Validate and append an observed run using the project's schema."""
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

    def save(
        self, project: dict[str, Any], value: str | dict[str, Any], *, run_id: int | None = None,
        batch_index: int | None = None, candidate_index: int | None = None,
        draft_id: str | None = None, parameters: dict[str, Any] | None = None,
    ) -> None:
        """Save edited parameters and results to a run, draft, or recommendation."""
        candidate, draft, run = self._find_row(project, run_id, batch_index, candidate_index, draft_id)
        current = candidate or draft or run
        assert current is not None
        current_parameters = current["parameters"]
        multi = "objectives" in project
        if multi and not isinstance(value, dict):
            raise ValueError("Provide results by objective name.")
        if not multi and not isinstance(value, str):
            raise ValueError("Provide a single objective result.")
        validated_parameters = validate_parameters(
            project, current_parameters if parameters is None else parameters, allow_partial=multi,
        )
        if multi:
            # Keep values for removed definitions so configuration changes do not erase measurements.
            active = {p["name"] for p in project["parameters"]}
            saved_parameters = {k: v for k, v in current_parameters.items() if k not in active}
            saved_parameters.update(validated_parameters)
            assert isinstance(value, dict)
            results = validate_results(project, value)
        else:
            saved_parameters = validated_parameters
            assert isinstance(value, str)
            results = validate_results(project, {project["objective"]["name"]: value})

        # A row without observations remains a draft or pending recommendation.
        if run is None and not results:
            if candidate is not None:
                set_candidate_parameters(candidate, saved_parameters)
                return
            assert draft is not None
            draft["parameters"] = saved_parameters
            return

        if run is None:
            run = self._create_run(project, saved_parameters, results, value)
            if candidate is None:
                assert draft is not None
                # Replacing a draft with a run must not move its table row.
                if "table_order" in draft:
                    run["table_order"] = draft["table_order"]
                project["draft_runs"] = [item for item in project["draft_runs"] if item["id"] != draft_id]
            else:
                candidate["run_id"] = run["id"]
        else:
            self._update_run(project, run, saved_parameters, results)

        if candidate is not None:
            set_candidate_parameters(candidate, saved_parameters)
            return
        # Editing a linked run must also update its recommendation's parameter snapshot.
        for linked in iter_candidates(project):
            if linked.get("run_id") == run["id"]:
                set_candidate_parameters(linked, dict(saved_parameters))

    def _create_run(
        self, project: dict[str, Any], parameters: dict[str, Any],
        results: dict[str, float], value: str | dict[str, Any],
    ) -> dict[str, Any]:
        """Append an observed run in the appropriate project schema."""
        if "objectives" not in project:
            return self.add(project, {**parameters, project["objective"]["name"]: value})
        run_id = 1
        existing_ids = {item["id"] for item in project["runs"]}
        while run_id in existing_ids:
            run_id += 1
        run = {"id": run_id, "parameters": parameters, "results": results}
        project["runs"].append(run)
        return run

    def _update_run(
        self, project: dict[str, Any], run: dict[str, Any],
        parameters: dict[str, Any], results: dict[str, float],
    ) -> None:
        """Replace active measurements while preserving results for removed objectives."""
        if "objectives" in project:
            # Preserve results for objectives that were removed from the current configuration.
            active_objectives = {o["name"] for o in objectives_for(project)}
            retained = {k: v for k, v in run["results"].items() if k not in active_objectives}
            retained.update(results)
            run["results"] = retained
        else:
            if not results:
                raise ValueError("Enter at least one objective result.")
            run["objective"] = results[project["objective"]["name"]]
        run["parameters"] = parameters

    def _find_row(
        self, project: dict[str, Any], run_id: int | None, batch_index: int | None,
        candidate_index: int | None, draft_id: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
        """Resolve the editable row and any run linked to its recommendation."""
        candidate = draft = run = None
        if batch_index is not None and candidate_index is not None:
            candidate = project["recommendation_batches"][batch_index]["candidates"][candidate_index]
            run_id = candidate.get("run_id")
        elif draft_id is not None:
            draft = next(item for item in project["draft_runs"] if item["id"] == draft_id)
        elif run_id is None:
            raise ValueError("A run, draft, or recommendation is required.")
        if run_id is not None:
            run = next(item for item in project["runs"] if item["id"] == run_id)
        return candidate, draft, run

    def delete(self, project: dict[str, Any], run_id: int) -> None:
        """Delete a run and unlink any recommendation that refers to it."""
        project["runs"] = [run for run in project["runs"] if run["id"] != run_id]
        for candidate in iter_candidates(project):
            if candidate.get("run_id") == run_id:
                del candidate["run_id"]
