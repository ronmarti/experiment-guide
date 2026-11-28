import uuid
from copy import deepcopy
from threading import Event
from typing import Any, Callable

from experiment.services.optimization import AxOptimizer



class PredictionController:
    """Coordinate prediction snapshots and prevent stale results from being saved."""

    def __init__(
        self, predictor: AxOptimizer,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        """Use the supplied predictor and request identifier generator."""
        self._predictor = predictor
        self._new_id = new_id

    def request(self, project: dict[str, Any], point: dict[str, Any], persist: bool) -> dict[str, Any]:
        """Capture the model inputs for a preview or a persisted refresh."""
        # Background work must use a consistent snapshot, not mutable session state.
        return {
            "id": self._new_id(), "project": deepcopy(project),
            "point": dict(point), "persist": persist,
        }

    def calculate(self, request: dict[str, Any] | None, cancel: Event) -> dict[str, Any] | None:
        """Debounce previews and return a prediction or an explicit error."""
        # Debounce previews; saved refreshes start immediately and can resume after reopening.
        if request is None or (not request["persist"] and cancel.wait(0.35)):
            return None
        try:
            predictions = self._predictor.predict(request["project"], request["point"])
            return {"id": request["id"], "predictions": predictions, "error": None}
        except (ValueError, RuntimeError) as exc:
            return {"id": request["id"], "predictions": None, "error": str(exc)}

    def needs_retry(self, current: dict[str, Any], request: dict[str, Any]) -> bool:
        """Check whether model inputs have changed since the request snapshot."""
        fields = ("name", "parameters", "objective", "objectives", "parameter_constraints")
        previous = request["project"]
        if any(current.get(key) != previous.get(key) for key in fields):
            return True
        # Prediction metadata on other rows must not cause competing refreshes to refit forever.
        def observations(project):
            return [
                {key: run[key] for key in ("id", "parameters", "objective", "results") if key in run}
                for run in project["runs"]
            ]
        return observations(current) != observations(previous)

    def apply(
        self, project: dict[str, Any], request: dict[str, Any], result: dict[str, Any],
        batch_index: int | None = None, candidate_index: int | None = None,
        *, run_id: int | None = None, draft_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Apply a current saved refresh to a project copy, or ignore a stale result."""
        if result["error"] is not None:
            raise ValueError(result["error"])
        if not request["persist"] or result["id"] != request["id"]:
            return None
        updated = deepcopy(project)
        if batch_index is not None and candidate_index is not None:
            batches = updated["recommendation_batches"]
            if batch_index >= len(batches) or candidate_index >= len(batches[batch_index]["candidates"]):
                return None
            row = batches[batch_index]["candidates"][candidate_index]
        elif draft_id is not None:
            row = next((draft for draft in updated.get("draft_runs", []) if draft["id"] == draft_id), None)
        elif run_id is not None:
            row = next((run for run in updated["runs"] if run["id"] == run_id), None)
        else:
            raise ValueError("A prediction target is required.")
        # Ignore results for parameter values that have since been changed.
        if row is None or row["parameters"] != request["point"]:
            return None
        if result["predictions"] is None:
            row.pop("predictions", None)
            row["prediction_status"] = "model_unavailable"
        else:
            row["predictions"] = result["predictions"]
            row.pop("prediction_status", None)
        return updated
