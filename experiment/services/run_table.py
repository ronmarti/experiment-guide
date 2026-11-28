import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from experiment.model.table_order import next_table_order
from experiment.services.optimization import AxOptimizer
from experiment.services.persistence import ProjectFiles
from experiment.services.runs import RunService


class RunTableService:
    """Coordinate ordered table changes without mutating the active project."""

    def __init__(
        self, runs: RunService, files: ProjectFiles, optimizer: AxOptimizer,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """Receive run, file, and optimizer services plus injectable IDs and timestamps."""
        self._runs = runs
        self._files = files
        self._optimizer = optimizer
        self._new_id = new_id
        self._now = now

    def add_draft(self, project: dict[str, Any]) -> dict[str, Any]:
        """Append a blank editable run to a project copy."""
        updated = deepcopy(project)
        order = next_table_order(updated)
        updated.setdefault("draft_runs", []).append({
            "id": self._new_id(), "parameters": {}, "table_order": order,
        })
        return updated

    def delete_recommendation(self, project: dict[str, Any], batch_index: int, candidate_index: int) -> dict[str, Any]:
        """Remove a recommendation and its linked run, if present, from a copy."""
        updated = deepcopy(project)
        candidate = updated["recommendation_batches"][batch_index]["candidates"].pop(candidate_index)
        if "run_id" in candidate:
            self._runs.delete(updated, candidate["run_id"])
        return updated

    def import_csv(self, project: dict[str, Any], data: bytes) -> tuple[dict[str, Any], int]:
        """Append validated CSV observations atomically and return the imported count."""
        # Validate the whole import against a copy before returning any changes to the session.
        updated = deepcopy(project)
        imported = self._files.parse_csv(updated, data)
        order = next_table_order(updated)
        for row_order, row in enumerate(imported, start=order):
            run = self._runs.add(updated, row)
            run["table_order"] = row_order
        return updated, len(imported)

    def generate(self, project: dict[str, Any], batch_size: int) -> tuple[dict[str, Any], bool]:
        """Append a generated batch and report whether model predictions are unavailable."""
        updated = deepcopy(project)
        candidates = self._optimizer.generate(updated, batch_size)
        if not candidates:
            raise RuntimeError("No recommendations were generated. Try a different batch size.")
        order = next_table_order(updated)
        for row_order, candidate in enumerate(candidates, start=order):
            candidate["table_order"] = row_order
        updated["recommendation_batches"].append({
            "id": self._new_id(),
            "batch_size": len(candidates),
            "created_at": self._now().isoformat(),
            "candidates": candidates,
        })
        unavailable = any(candidate.get("prediction_status") == "model_unavailable" for candidate in candidates)
        return updated, unavailable
