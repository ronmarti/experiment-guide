import uuid

import reacton.ipyvuetify as v
import solara

from experiment.model.project import objectives_for, results_for
from experiment.model.table_order import ordered_table_rows
from experiment.services.values import validate_parameters
from gui.alert_message import AlertMessage
from gui.result_row import ResultRow
from gui.objective_visualization import ObjectiveVisualization


@solara.component
def RunsView(state, services):
    project = state["project"].value
    objectives = objectives_for(project)
    batch_size = solara.use_reactive(5)
    waiting = solara.use_reactive(False)
    # Stable keys keep unsaved row edits with the same candidate after a deletion shifts indices.
    candidate_keys = solara.use_ref([])
    for batch_index, batch in enumerate(project["recommendation_batches"]):
        if batch_index == len(candidate_keys.current):
            candidate_keys.current.append([])
        keys = candidate_keys.current[batch_index]
        while len(keys) < len(batch["candidates"]):
            keys.append(str(uuid.uuid4()))

    def add():
        state["project"].value = services.table.add_draft(state["project"].value)
        state["message_kind"].value = "success"
        state["message"].value = "Blank run added. Enter parameters and save the row."

    def remove_recommendation(batch_index, candidate_index):
        updated = services.table.delete_recommendation(state["project"].value, batch_index, candidate_index)
        candidate_keys.current[batch_index].pop(candidate_index)
        state["project"].value = updated
        state["message_kind"].value = "success"
        state["message"].value = "Recommendation and any linked run deleted."

    def load_csv(file):
        try:
            updated, count = services.table.import_csv(state["project"].value, file["data"])
            state["project"].value = updated
            state["message_kind"].value = "success"
            state["message"].value = f"Imported {count} runs."
        except ValueError as exc:
            state["message_kind"].value = "error"
            state["message"].value = str(exc)

    def generate():
        waiting.value = True
        try:
            updated, unavailable = services.table.generate(state["project"].value, batch_size.value)
            state["project"].value = updated
            state["message_kind"].value = "success"
            state["message"].value = f"Generated {updated['recommendation_batches'][-1]['batch_size']} recommendations."
            if unavailable:
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
    solara.Markdown("## Runs and recommendations")
    solara.Markdown(
        "Edit run notes, parameter values and results in the table, then select Save for each row. "
        "Available objective results are used without filling in missing results. Save edits before leaving this screen. "
        "Predicted means and sigmas are model estimates, not observed results. "
        "Sigma is the posterior standard deviation of the expected outcome. Predictions update as you edit "
        "recommendation parameters and when you save any row; previews use saved observations and are not saved until you save the row. "
        "Wait for updating to finish before downloading; interrupted saved refreshes resume when this tab is reopened. "
        "Predictions are unavailable without observations, for incomplete parameters, or for objectives not modeled yet. "
        "Best observed values are highlighted for each objective, including ties; unsaved edits are not ranked. "
        "Deleting a recommendation also deletes its linked run, if any."
    )
    
    if rows:
        with v.Html(
            tag="div",
            style_="width: 100%; max-width: 100%; min-width: 0; overflow-x: auto",
            attributes={"tabindex": "0", "role": "region", "aria-label": "Runs and recommendations table"},
        ):
            with v.Html(tag="table", style_="width: 100%; border-collapse: collapse"):
                with v.Html(tag="thead"):
                    with v.Html(tag="tr"):
                        headings = ["Run and notes", *[p["name"] for p in project["parameters"]]]
                        headings += [heading for o in objectives for heading in (
                            f"{o['name']} observed", f"{o['name']} predicted mean ± sigma",
                        )]
                        headings.append("Actions")
                        for index, heading in enumerate(headings):
                            style = "text-align: left; padding: 8px"
                            if index == 0:
                                style += "; min-width: 220px"
                            elif index == len(headings) - 1:
                                style += "; min-width: 160px"
                            else:
                                style += "; min-width: 140px"
                            if objectives and index == 1 + len(project["parameters"]):
                                style += "; border-left: 3px solid #546e7a"
                            v.Html(tag="th", children=[heading], style_=style)
                with v.Html(tag="tbody"):
                    for kind, row, batch_index, candidate_index in rows:
                        if kind == "run":
                            ResultRow(
                                state, services, row["parameters"], f"Run {row['id']}",
                                results_for(project, row), run_id=row["id"], best_results=best_results,
                                saved_notes=row.get("notes"), saved_row=row,
                            ).key(f"run-{row['id']}")
                        elif kind == "draft":
                            ResultRow(
                                state, services, row["parameters"], f"New run {row['id'][:8]}",
                                {}, draft_id=row["id"], best_results=best_results, saved_notes=row.get("notes"),
                                saved_row=row,
                            ).key(f"draft-{row['id']}")
                        else:
                            assert batch_index is not None and candidate_index is not None
                            run_id = row.get("run_id")
                            run = runs_by_id.get(run_id)
                            label = f"Batch {batch_index + 1}, recommendation {candidate_index + 1}"
                            ResultRow(
                                state, services, row["parameters"], label,
                                results_for(project, run) if run else {}, run_id=run_id,
                                batch_index=batch_index, candidate_index=candidate_index,
                                candidate=row, best_results=best_results, saved_notes=row.get("notes"), saved_row=row,
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

    ObjectiveVisualization(project, services.plots)
