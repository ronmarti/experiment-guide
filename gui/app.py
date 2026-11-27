import json
import os
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import reacton.ipyvue as vue
import reacton.ipyvuetify as v
import solara
from solara import lab
from solara.datatypes import ResultState
from solara.util import IPYVUETIFY_V3

from experiment_core import (
    MAX_CSV_BYTES,
    add_run,
    blank_project,
    delete_run,
    generate_candidates,
    invalidate_predictions,
    load_project_json,
    next_table_order,
    objectives_for,
    ordered_table_rows,
    parse_csv,
    predict_candidate,
    results_for,
    save_result,
    upgrade_project,
    validate_constraints,
    validate_parameters,
    validate_project,
)


ACCESS_KEY = os.environ.get("APP_ACCESS_KEY", "change-me")


def session_state():
    session_id = solara.get_session_id()
    state = getattr(session_state, "_sessions", None)
    if state is None:
        state = {}
        setattr(session_state, "_sessions", state)
    if session_id not in state:
        state[session_id] = {
            "authorized": solara.reactive(False),
            "project": solara.reactive(None),
            "message": solara.reactive(""),
            "message_kind": solara.reactive("info"),
        }
    return state[session_id]


def set_project(state, project):
    state["project"].value = project
    state["message_kind"].value = "success"
    state["message"].value = "Project updated."


@solara.component
def AlertMessage(state):
    kind = state["message_kind"].value
    text = state["message"].value
    if text:
        if kind == "error":
            solara.Error(text)
        elif kind == "success":
            solara.Success(text)
        elif kind == "warning":
            solara.Warning(text)
        else:
            solara.Info(text)


@solara.component
def Startup(state):
    key = solara.use_reactive("")

    def authorize(value):
        if value == ACCESS_KEY:
            state["message"].value = ""
            state["authorized"].value = True
        else:
            state["message_kind"].value = "error"
            state["message"].value = "Invalid access key."

    with solara.Card("Welcome"):
        solara.Markdown("## Adaptive Experimentation")
        key_field = solara.InputText(
            "Access key",
            value=key,
            password=True,
            on_value=lambda value: key.set(value or ""),
        )
        vue.use_event(key_field, "keyup.enter", lambda widget, event, data: authorize(widget.v_model))
        solara.Button("Authorize", on_click=lambda: authorize(key.value), color="primary")
        AlertMessage(state)


@solara.component
def ProjectSelection(state):
    project_name = solara.use_reactive("Untitled experiment")

    def create_project():
        project = blank_project(project_name.value or "Untitled experiment")
        upgrade_project(project)
        set_project(state, project)
        state["message_kind"].value = "success"
        state["message"].value = "Blank project created."

    def load_project(file):
        try:
            data = file["data"]
            if len(data) > 10 * 1024 * 1024:
                raise ValueError("Project JSON exceeds the 10 MB size limit.")
            project = load_project_json(data)
            set_project(state, project)
            state["message_kind"].value = "success"
            state["message"].value = "Project loaded."
        except ValueError as exc:
            state["message_kind"].value = "error"
            state["message"].value = str(exc)

    with solara.Card("Start a project"):
        solara.Warning(
            "Changes are held only in this browser session. Download project JSON to save your work.",
        )
        solara.InputText("Project name", value=project_name)
        solara.Button("Create blank project", on_click=create_project)
        solara.FileDrop(
            "Load project JSON",
            lazy=False,
            on_file=load_project,
        )
        AlertMessage(state)


@solara.component
def ConfigurationRow(kind, item, label, on_save, on_delete):
    if kind == "parameter":
        bounds = item.get("bounds", ["", ""]) if item.get("type") not in ("categorical", "choice", "str") else ["", ""]
        initial = {
            "name": item.get("name", ""),
            "type": {"float": "continuous", "int": "integer", "choice": "categorical", "str": "categorical"}.get(item.get("type"), item.get("type", "continuous")),
            "lower": str(bounds[0]),
            "upper": str(bounds[1]),
            "choices": ", ".join(item.get("choices", [])),
        }
    elif kind == "objective":
        initial = {"name": item.get("name", ""), "direction": item.get("direction", "maximize")}
    else:
        initial = {"expression": item}
    fields = solara.use_reactive(initial)

    def update(name, value):
        fields.value = {**fields.value, name: value or ""}

    def text(name, disabled=False):
        with v.Html(tag="td", style_="padding: 0 8px; vertical-align: middle"):
            solara.InputText(
                f"{name} for {label}", value=fields.value[name],
                on_value=lambda value: update(name, value),
                continuous_update=True, dense=True, disabled=disabled, hide_details=True,
            )

    def select(name, options):
        with v.Html(tag="td", style_="padding: 0 8px; vertical-align: middle"):
            v.Select(
                label=f"{name} for {label}", items=options,
                v_model=fields.value[name], on_v_model=lambda value: update(name, value),
                hide_details=True, **({"density": "compact"} if IPYVUETIFY_V3 else {"dense": True}),
            )

    with v.Html(tag="tr"):
        if kind == "parameter":
            text("name")
            select("type", ["continuous", "integer", "categorical"])
            text("lower", disabled=fields.value["type"] == "categorical")
            text("upper", disabled=fields.value["type"] == "categorical")
            text("choices", disabled=fields.value["type"] != "categorical")
        elif kind == "objective":
            text("name")
            select("direction", ["maximize", "minimize"])
        else:
            text("expression")
        with v.Html(tag="td", style_="padding: 0 8px; vertical-align: middle; white-space: nowrap"):
            solara.Button("Save", on_click=lambda: on_save(fields.value), color="primary")
            solara.Button("Delete", on_click=on_delete, text=True)


@solara.component
def ParameterConfiguration(state):
    project = state["project"].value
    parameter_drafts = solara.use_reactive([])
    objective_drafts = solara.use_reactive([])
    constraint_drafts = solara.use_reactive([])

    def report_error(exc):
        state["message_kind"].value = "error"
        state["message"].value = str(exc)

    def rename_values(updated, field, old, new):
        if old == new:
            return
        targets = [run[field] for run in updated["runs"]]
        if field == "parameters":
            targets += [candidate["parameters"] for batch in updated["recommendation_batches"] for candidate in batch["candidates"]]
            targets += [draft["parameters"] for draft in updated.get("draft_runs", [])]
        elif field == "results":
            targets += [
                candidate["predictions"]
                for batch in updated["recommendation_batches"]
                for candidate in batch["candidates"] if "predictions" in candidate
            ]
        for values in targets:
            if old in values:
                if new in values:
                    raise ValueError(f"Cannot rename {old}: stored values for {new} already exist.")
                values[new] = values.pop(old)
        if field == "parameters":
            updated["parameter_constraints"] = [
                re.sub(rf"\b{re.escape(old)}\b", lambda _: new, expression)
                for expression in updated["parameter_constraints"]
            ]

    def save(kind, index, draft_id, fields):
        try:
            updated = deepcopy(state["project"].value)
            upgrade_project(updated)
            if kind == "parameter":
                parameter_type = fields["type"]
                parameter = {"name": fields["name"].strip(), "type": parameter_type}
                if parameter_type == "categorical":
                    parameter["choices"] = [choice.strip() for choice in fields["choices"].split(",") if choice.strip()]
                else:
                    convert = int if parameter_type == "integer" else float
                    parameter["bounds"] = [convert(fields["lower"]), convert(fields["upper"])]
                if index is None:
                    updated["parameters"].append(parameter)
                    invalidate_predictions(updated)
                else:
                    previous = updated["parameters"][index]
                    old = previous["name"]
                    rename_values(updated, "parameters", old, parameter["name"])
                    updated["parameters"][index] = parameter
                    if {**previous, "name": parameter["name"]} != parameter:
                        invalidate_predictions(updated)
            elif kind == "objective":
                objective = {"name": fields["name"].strip(), "direction": fields["direction"]}
                if index is None:
                    updated["objectives"].append(objective)
                else:
                    old = updated["objectives"][index]["name"]
                    rename_values(updated, "results", old, objective["name"])
                    updated["objectives"][index] = objective
            else:
                expression = fields["expression"].strip()
                if index is None:
                    updated["parameter_constraints"].append(expression)
                else:
                    updated["parameter_constraints"][index] = expression
                validate_constraints(updated)
            validate_project(updated)
            state["project"].value = updated
            if draft_id is not None:
                drafts = {"parameter": parameter_drafts, "objective": objective_drafts, "constraint": constraint_drafts}[kind]
                drafts.value = [entry for entry in drafts.value if entry != draft_id]
            state["message_kind"].value = "success"
            state["message"].value = f"{kind.capitalize()} saved."
        except ValueError as exc:
            report_error(exc)

    def remove(kind, index, draft_id):
        if draft_id is not None:
            drafts = {"parameter": parameter_drafts, "objective": objective_drafts, "constraint": constraint_drafts}[kind]
            drafts.value = [entry for entry in drafts.value if entry != draft_id]
            return
        updated = deepcopy(state["project"].value)
        upgrade_project(updated)
        key = {"parameter": "parameters", "objective": "objectives", "constraint": "parameter_constraints"}[kind]
        removed = updated[key].pop(index)
        if kind == "parameter":
            invalidate_predictions(updated)
        elif kind == "objective":
            for batch in updated["recommendation_batches"]:
                for candidate in batch["candidates"]:
                    candidate.get("predictions", {}).pop(removed["name"], None)
        state["project"].value = updated
        state["message_kind"].value = "success"
        state["message"].value = f"{kind.capitalize()} deleted. Existing measurements are retained."

    def table(kind, headings, items, drafts):
        with v.Html(tag="div", style_="overflow-x: auto"):
            min_width = "1020px" if kind == "parameter" else "480px"
            with v.Html(tag="table", style_=f"width: 100%; min-width: {min_width}; table-layout: fixed; border-collapse: collapse"):
                with v.Html(tag="thead"):
                    with v.Html(tag="tr"):
                        for heading in [*headings, "Actions"]:
                            v.Html(tag="th", children=[heading], style_="text-align: left; padding: 8px")
                with v.Html(tag="tbody"):
                    for index, item in enumerate(items):
                        label = f"{kind} {index + 1}"
                        identity = item if isinstance(item, str) else item.get("name", "")
                        ConfigurationRow(
                            kind, item, label,
                            lambda fields, index=index: save(kind, index, None, fields),
                            lambda index=index: remove(kind, index, None),
                        ).key(f"{kind}-{index}-{identity}")
                    for draft_id in drafts.value:
                        ConfigurationRow(
                            kind, "" if kind == "constraint" else {}, f"new {kind} {draft_id[:8]}",
                            lambda fields, draft_id=draft_id: save(kind, None, draft_id, fields),
                            lambda draft_id=draft_id: remove(kind, None, draft_id),
                        ).key(draft_id)

    AlertMessage(state)
    solara.Markdown(
        "Save each configuration row before leaving this screen. Existing measurements are retained "
        "when definitions change."
    )
    try:
        validate_constraints(project)
    except ValueError as exc:
        solara.Warning(f"Update the constraints before generating recommendations: {exc}")
    with solara.Card("Parameters"):
        solara.Markdown("Define bounds for numeric parameters, or comma-separated choices for categorical parameters.")
        solara.Button("Add parameter", on_click=lambda: parameter_drafts.set([*parameter_drafts.value, str(uuid.uuid4())]))
        table("parameter", ["Name", "Type", "Lower bound", "Upper bound", "Choices"], project["parameters"], parameter_drafts)
    with solara.Card("Objectives"):
        solara.Markdown("All objectives are optimized simultaneously. Each objective can be maximized or minimized.")
        solara.Button("Add objective", on_click=lambda: objective_drafts.set([*objective_drafts.value, str(uuid.uuid4())]))
        table("objective", ["Name", "Direction"], objectives_for(project), objective_drafts)
    with solara.Card("Linear constraints"):
        solara.Markdown("Use one linear inequality per row, for example `x + y <= 10`.")
        solara.Button("Add constraint", on_click=lambda: constraint_drafts.set([*constraint_drafts.value, str(uuid.uuid4())]))
        table("constraint", ["Expression"], project["parameter_constraints"], constraint_drafts)


@solara.component
def ResultRow(
    state, parameters, label, results, run_id=None,
    batch_index=None, candidate_index=None, draft_id=None, candidate=None,
    on_delete_recommendation=None, best_results=None,
):
    objectives = objectives_for(state["project"].value)
    values = solara.use_reactive({name: str(value) for name, value in results.items()})
    parameter_values = solara.use_reactive({
        name: str(parameter_value) for name, parameter_value in parameters.items()
    })
    prediction_request = solara.use_reactive(None)

    def request_prediction(project, point, persist):
        prediction_request.value = {
            "id": str(uuid.uuid4()), "project": deepcopy(project),
            "point": dict(point), "persist": persist,
        }

    def resume_prediction():
        if candidate is not None and candidate.get("prediction_status") == "refresh_required":
            request_prediction(state["project"].value, parameters, True)

    solara.use_effect(resume_prediction, dependencies=[])
    request = prediction_request.value

    def calculate_prediction(cancel):
        if request is None or (not request["persist"] and cancel.wait(0.35)):
            return None
        try:
            predictions = predict_candidate(request["project"], request["point"])
            return {"id": request["id"], "predictions": predictions, "error": None}
        except (ValueError, RuntimeError) as exc:
            return {"id": request["id"], "predictions": None, "error": str(exc)}

    task = solara.use_thread(calculate_prediction, dependencies=[prediction_request.value], intrusive_cancel=False)
    result = task.value if request and task.value and task.value["id"] == request["id"] else None

    def finish_prediction():
        if not request or not result or task.state != ResultState.FINISHED:
            return
        current = state["project"].value
        model_fields = ("name", "parameters", "objective", "objectives", "parameter_constraints", "runs")
        if any(current.get(key) != request["project"].get(key) for key in model_fields):
            request_prediction(current, request["point"], request["persist"])
            return
        if not request["persist"]:
            return
        if result["error"]:
            if state["message"].value == f"{label} saved. Updating predictions...":
                state["message_kind"].value = "warning"
                state["message"].value = f"{label} saved. Prediction unavailable: {result['error']}"
            return
        updated = deepcopy(current)
        saved = updated["recommendation_batches"][batch_index]["candidates"][candidate_index]
        if saved["parameters"] != request["point"]:
            return
        if result["predictions"] is None:
            saved.pop("predictions", None)
            saved["prediction_status"] = "model_unavailable"
            if state["message"].value == f"{label} saved. Updating predictions...":
                state["message_kind"].value = "warning"
                state["message"].value = f"{label} saved. Predictions need at least one observed result."
        else:
            saved["predictions"] = result["predictions"]
            saved.pop("prediction_status", None)
            if state["message"].value == f"{label} saved. Updating predictions...":
                state["message_kind"].value = "success"
                state["message"].value = f"{label} saved and predictions updated."
        state["project"].value = updated

    solara.use_effect(finish_prediction, dependencies=[request, task.state, result])

    def update_parameter(name, value):
        updated_values = {**parameter_values.value, name: value or ""}
        parameter_values.value = updated_values
        if candidate is not None:
            request_prediction(state["project"].value, updated_values, False)

    def save():
        try:
            project = deepcopy(state["project"].value)
            save_result(
                project, values.value if "objectives" in project else values.value.get(objectives[0]["name"], ""),
                run_id=run_id,
                batch_index=batch_index, candidate_index=candidate_index,
                draft_id=draft_id, parameters=parameter_values.value,
            )
            if candidate is not None:
                saved = project["recommendation_batches"][batch_index]["candidates"][candidate_index]
                saved.pop("predictions", None)
                saved["prediction_status"] = "refresh_required"
            state["project"].value = project
            state["message_kind"].value = "success"
            state["message"].value = f"{label} saved. Updating predictions..." if candidate is not None else "Row saved."
            if candidate is not None:
                request_prediction(project, saved["parameters"], True)
        except ValueError as exc:
            state["message_kind"].value = "error"
            state["message"].value = str(exc)

    def remove():
        project = deepcopy(state["project"].value)
        if draft_id is not None:
            project["draft_runs"] = [draft for draft in project["draft_runs"] if draft["id"] != draft_id]
        else:
            delete_run(project, run_id)
        state["project"].value = project
        state["message_kind"].value = "success"
        state["message"].value = "Run deleted."

    with v.Html(tag="tr"):
        v.Html(tag="td", children=[label])
        for parameter in state["project"].value["parameters"]:
            name = parameter["name"]
            with v.Html(tag="td"):
                solara.InputText(
                    f"{name} for {label}",
                    value=parameter_values.value.get(name, ""),
                    on_value=lambda value, name=name: update_parameter(name, value),
                    continuous_update=True,
                    dense=True,
                )
        for objective in objectives:
            name = objective["name"]
            is_best = (
                name in results and best_results is not None
                and name in best_results and results[name] == best_results[name]
            )
            if is_best:
                try:
                    is_best = float(values.value.get(name, "")) == results[name]
                except (TypeError, ValueError, OverflowError):
                    is_best = False
            cell_style = (
                "background-color: #e8f5e9; border-left: 3px solid #2e7d32; padding: 4px"
                if is_best else ""
            )
            with v.Html(tag="td", style_=cell_style):
                solara.InputText(
                    f"Result for {label}" if len(objectives) == 1 else f"{name} result for {label}",
                    value=values.value.get(name, ""),
                    on_value=lambda value, name=name: values.set({**values.value, name: value or ""}),
                    continuous_update=True,
                    dense=True,
                )
                if is_best:
                    v.Html(tag="span", style_="color: #1b5e20; font-weight: bold", children=["Best observed"])
            if request is None:
                prediction = candidate.get("predictions", {}).get(name) if candidate is not None else None
            else:
                predictions = result["predictions"] if result and task.state == ResultState.FINISHED else None
                prediction = predictions.get(name) if predictions is not None else None
            for key in ("mean", "sigma"):
                if prediction is not None:
                    display = f"{prediction[key]:.6g}"
                elif request and task.state not in (ResultState.FINISHED, ResultState.ERROR):
                    display = "Updating..."
                else:
                    display = "Unavailable"
                v.Html(tag="td", children=[display])
        with v.Html(tag="td"):
            solara.Button("Save", on_click=save, color="primary")
            solara.Button("Delete", on_click=on_delete_recommendation or remove, text=True)
            if request and result and result["error"]:
                v.Html(tag="div", children=[f"Prediction unavailable: {result['error']}"])
            elif request and result and result["predictions"] is None:
                v.Html(tag="div", children=["Prediction unavailable: no observed results."])
            elif request and task.state == ResultState.ERROR:
                v.Html(tag="div", children=["Prediction failed. Check the project and try again."])


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


@solara.component
def ProjectView(state):
    project = state["project"].value
    tab = solara.use_reactive(0)

    def name_project(value):
        project["name"] = value or "Untitled experiment"
        state["project"].value = dict(project)

    def download_json():
        return json.dumps(project, indent=2, ensure_ascii=False).encode("utf-8")

    solara.Markdown(f"# {project['name']}")
    solara.InputText(
        "Project name",
        value=project["name"],
        on_value=name_project,
    )
    solara.FileDownload(
        download_json,
        filename=f"{project['name'].replace(' ', '_')}.json",
        label="Download project JSON",
        mime_type="application/json",
    )
    solara.Warning(
        "No automatic save: download this JSON before closing or losing the session.",
    )

    lab.Tabs(
        value=tab,
        children=[
            lab.Tab("Configuration"),
            lab.Tab("Runs and recommendations"),
        ],
    )
    if tab.value == 0:
        ParameterConfiguration(state)
    elif tab.value == 1:
        RunsView(state)


@solara.component
def Page():
    state = session_state()
    if not state["authorized"].value:
        Startup(state)
    elif state["project"].value is None:
        ProjectSelection(state)
    else:
        ProjectView(state)
