import math
from typing import Any


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
