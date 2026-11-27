import uuid
from copy import deepcopy
from datetime import datetime, timezone

import matplotlib.pyplot as plt
import reacton.ipyvuetify as v
import solara

from experiment.model.project import objectives_for, results_for
from experiment.model.table_order import next_table_order, ordered_table_rows
from experiment.services.optimization import generate_candidates
from experiment.services.persistence import MAX_CSV_BYTES, parse_csv
from experiment.services.runs import add_run, delete_run
from experiment.services.values import validate_parameters
from gui.alert_message import AlertMessage
from gui.result_row import ResultRow


@solara.component
def RunsView(state):
    project = state["project"].value
    objectives = objectives_for(project)
    batch_size = solara.use_reactive(5)
    waiting = solara.use_reactive(False)
    candidate_keys = solara.use_ref([])
    for batch_index, batch in enumerate(project["recommendation_batches"]):
        if batch_index == len(candidate_keys.current):
            candidate_keys.current.append([])
        keys = candidate_keys.current[batch_index]
        while len(keys) < len(batch["candidates"]):
            keys.append(str(uuid.uuid4()))

    def add():
        updated = deepcopy(state["project"].value)
        order = next_table_order(updated)
        updated.setdefault("draft_runs", []).append({
            "id": str(uuid.uuid4()), "parameters": {}, "table_order": order,
        })
        state["project"].value = updated
        state["message_kind"].value = "success"
        state["message"].value = "Blank run added. Enter parameters and save the row."

    def remove_recommendation(batch_index, candidate_index):
        updated = deepcopy(state["project"].value)
        candidates = updated["recommendation_batches"][batch_index]["candidates"]
        candidate = candidates.pop(candidate_index)
        if "run_id" in candidate:
            delete_run(updated, candidate["run_id"])
        candidate_keys.current[batch_index].pop(candidate_index)
        state["project"].value = updated
        state["message_kind"].value = "success"
        state["message"].value = "Recommendation and any linked run deleted."

    def load_csv(file):
        try:
            data = file["data"]
            if len(data) > MAX_CSV_BYTES:
                raise ValueError("CSV upload exceeds the 5 MB size limit.")
            updated = deepcopy(state["project"].value)
            imported = parse_csv(updated, data)
            order = next_table_order(updated)
            for row in imported:
                run = add_run(updated, row)
                run["table_order"] = order
                order += 1
            state["project"].value = updated
            state["message_kind"].value = "success"
            state["message"].value = f"Imported {len(imported)} runs."
        except ValueError as exc:
            state["message_kind"].value = "error"
            state["message"].value = str(exc)

    def generate():
        waiting.value = True
        try:
            updated = deepcopy(state["project"].value)
            candidates = generate_candidates(updated, batch_size.value)
            if not candidates:
                raise RuntimeError("No recommendations were generated. Try a different batch size.")
            order = next_table_order(updated)
            for candidate in candidates:
                candidate["table_order"] = order
                order += 1
            updated["recommendation_batches"].append({
                "id": str(uuid.uuid4()),
                "batch_size": len(candidates),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "candidates": candidates,
            })
            state["project"].value = updated
            state["message_kind"].value = "success"
            state["message"].value = f"Generated {len(candidates)} recommendations."
            if any(candidate.get("prediction_status") == "model_unavailable" for candidate in candidates):
                state["message_kind"].value = "warning"
                state["message"].value += " Predictions are unavailable until Ax fits a predictive model; add observations and generate again."
        except (ValueError, RuntimeError) as exc:
            state["message_kind"].value = "error"
            state["message"].value = str(exc)
        finally:
            waiting.value = False

    runs_by_id = {run["id"]: run for run in project["runs"]}
    observed_results = [results_for(project, run) for run in project["runs"]]
    best_results = {}
    for objective in objectives:
        name = objective["name"]
        values = [results[name] for results in observed_results if name in results]
        if values:
            best_results[name] = (max if objective["direction"] == "maximize" else min)(values)
    rows = ordered_table_rows(project)
    if rows:
        with v.Html(tag="div", style_="overflow-x: auto"):
            with v.Html(tag="table", style_="width: 100%; border-collapse: collapse"):
                with v.Html(tag="thead"):
                    with v.Html(tag="tr"):
                        for heading in ["Run / recommendation", *[p["name"] for p in project["parameters"]],
                                        *[heading for o in objectives for heading in (
                                            f"{o['name']} observed", f"{o['name']} predicted mean",
                                            f"{o['name']} predicted sigma",
                                        )], "Actions"]:
                            v.Html(tag="th", children=[heading], style_="text-align: left; padding: 8px")
                with v.Html(tag="tbody"):
                    for kind, row, batch_index, candidate_index in rows:
                        if kind == "run":
                            ResultRow(
                                state, row["parameters"], f"Run {row['id']}",
                                results_for(project, row), run_id=row["id"], best_results=best_results,
                            ).key(f"run-{row['id']}")
                        elif kind == "draft":
                            ResultRow(
                                state, row["parameters"], f"New run {row['id'][:8]}",
                                {}, draft_id=row["id"], best_results=best_results,
                            ).key(f"draft-{row['id']}")
                        else:
                            assert batch_index is not None and candidate_index is not None
                            run_id = row.get("run_id")
                            run = runs_by_id.get(run_id)
                            label = f"Batch {batch_index + 1}, recommendation {candidate_index + 1}"
                            ResultRow(
                                state, row["parameters"], label,
                                results_for(project, run) if run else {}, run_id=run_id,
                                batch_index=batch_index, candidate_index=candidate_index,
                                candidate=row, best_results=best_results,
                                on_delete_recommendation=lambda batch_index=batch_index, candidate_index=candidate_index: (
                                    remove_recommendation(batch_index, candidate_index)
                                ),
                            ).key(f"candidate-{candidate_keys.current[batch_index][candidate_index]}")
    else:
        solara.Markdown("_No runs or recommendations yet._")

    solara.Markdown("## Generate recommendations")
    solara.SliderInt("Batch size", value=batch_size, min=1, max=100)
    solara.Button("Generate batch", on_click=generate, color="primary", disabled=waiting.value)
    if waiting.value:
        solara.ProgressLinear()

    solara.Markdown("## Runs and recommendations")
    solara.Markdown(
        "Edit parameter values and results in the table, then select Save for each row. "
        "Available objective results are used without filling in missing results. Save edits before leaving this screen. "
        "Predicted means and sigmas are model estimates, not observed results. "
        "Sigma is the posterior standard deviation of the expected outcome. Predictions update as you edit "
        "recommendation parameters and when you save; previews use saved observations and are not saved until you save the row. "
        "Wait for updating to finish before downloading; interrupted saved refreshes resume when this tab is reopened. "
        "Predictions are unavailable without observations, for manual runs, or for objectives not modeled yet. "
        "Best observed values are highlighted for each objective, including ties; unsaved edits are not ranked. "
        "Deleting a recommendation also deletes its linked run, if any."
    )
    if not project["parameters"] or not objectives:
        solara.Warning("Configure at least one parameter and an objective first.")
    else:
        solara.Button("Add run", on_click=add, color="primary")
        for run in project["runs"]:
            if not any(o["name"] in results_for(project, run) for o in objectives):
                continue
            try:
                validate_parameters(project, run["parameters"])
            except ValueError as exc:
                solara.Warning(f"Run {run['id']} needs valid parameter values before generation: {exc}")
                break
    AlertMessage(state)

    solara.Markdown("### Import CSV")
    solara.Markdown(
        "The CSV header must contain every parameter and objective name. Objective values may be blank. "
        "Imported rows are added as separate runs."
    )
    solara.FileDrop("Upload runs CSV", lazy=False, on_file=load_csv)

    solara.Markdown("## Objective history")
    if project["runs"]:
        fig, ax = plt.subplots(figsize=(7, 3))
        for objective in objectives:
            name = objective["name"]
            points = [(index, results_for(project, run)[name]) for index, run in enumerate(project["runs"], 1) if name in results_for(project, run)]
            if points:
                ax.plot([point[0] for point in points], [point[1] for point in points], marker="o", label=name)
        ax.set_xlabel("Run order")
        ax.set_ylabel("Objective")
        if objectives and any(results_for(project, run) for run in project["runs"]):
            ax.legend()
        ax.grid(True, alpha=0.25)
        fig.tight_layout()
        solara.FigureMatplotlib(fig)
        plt.close(fig)
    else:
        solara.Markdown("_Objective history appears after the first run._")
