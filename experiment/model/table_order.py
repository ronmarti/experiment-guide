import math
from typing import Any

from experiment.model.project import iter_candidates


def ordered_table_rows(project: dict[str, Any]) -> list[tuple[str, dict[str, Any], int | None, int | None]]:
    # A linked run is displayed within its recommendation, not as a second row.
    linked_ids = {
        candidate["run_id"]
        for candidate in iter_candidates(project)
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
    # Stable sorting preserves the former grouping for legacy rows without order metadata.
    return sorted(rows, key=lambda row: row[1].get("table_order", math.inf))


def next_table_order(project: dict[str, Any]) -> int:
    rows = ordered_table_rows(project)
    # Materialize legacy ordering before appending, so it survives project export.
    for order, (_, row, _, _) in enumerate(rows):
        row["table_order"] = order
    return len(rows)
