from copy import deepcopy

import reacton.ipyvuetify as v
import solara
from solara.datatypes import ResultState

from experiment.model.project import objectives_for


@solara.component
def ResultRow(
    state, services, parameters, label, results, run_id=None,
    batch_index=None, candidate_index=None, draft_id=None, candidate=None,
    on_delete_recommendation=None, best_results=None, saved_notes=None, saved_row=None,
):
    objectives = objectives_for(state["project"].value)
    values = solara.use_reactive({name: str(value) for name, value in results.items()})
    parameter_values = solara.use_reactive({
        name: str(parameter_value) for name, parameter_value in parameters.items()
    })
    prediction_request = solara.use_reactive(None)
    edited_notes = solara.use_reactive(None)
    parameters_dirty = solara.use_reactive(False)

    def request_prediction(project, point, persist):
        prediction_request.value = services.predictions.request(project, point, persist)

    # A saved refresh may be interrupted when leaving the view; resume it on mount.
    def resume_prediction():
        if saved_row is not None and saved_row.get("prediction_status") == "refresh_required":
            request_prediction(state["project"].value, parameters, True)

    solara.use_effect(resume_prediction, dependencies=[])
    request = prediction_request.value

    def calculate_prediction(cancel):
        return services.predictions.calculate(request, cancel)

    task = solara.use_thread(calculate_prediction, dependencies=[prediction_request.value], intrusive_cancel=False)
    # A slower, older request must not replace the most recent preview.
    result = task.value if request and task.value and task.value["id"] == request["id"] else None

    def finish_prediction():
        if not request or not result or task.state != ResultState.FINISHED:
            return
        current = state["project"].value
        # Refit against newer observations or configuration before publishing results.
        if services.predictions.needs_retry(current, request):
            request_prediction(current, request["point"], request["persist"])
            return
        if not request["persist"]:
            return
        if result["error"]:
            if state["message"].value == f"{label} saved. Updating predictions...":
                state["message_kind"].value = "warning"
                state["message"].value = f"{label} saved. Prediction unavailable: {result['error']}"
            return
        updated = services.predictions.apply(
            current, request, result, batch_index, candidate_index, run_id=run_id, draft_id=draft_id,
        )
        if updated is None:
            return
        if state["message"].value == f"{label} saved. Updating predictions...":
            if result["predictions"] is None:
                state["message_kind"].value = "warning"
                state["message"].value = f"{label} saved. Predictions need at least one observed result."
            else:
                state["message_kind"].value = "success"
                state["message"].value = f"{label} saved and predictions updated."
        state["project"].value = updated

    solara.use_effect(finish_prediction, dependencies=[request, task.state, result])

    def update_parameter(name, value):
        updated_values = {**parameter_values.value, name: value or ""}
        parameter_values.value = updated_values
        parameters_dirty.value = True
        if candidate is not None:
            request_prediction(state["project"].value, updated_values, False)

    def save():
        try:
            project = deepcopy(state["project"].value)
            saved = services.runs.save(
                project, values.value if "objectives" in project else values.value.get(objectives[0]["name"], ""),
                run_id=run_id,
                batch_index=batch_index, candidate_index=candidate_index,
                draft_id=draft_id, parameters=parameter_values.value, notes=edited_notes.value,
            )
            # Persist the pending refresh so a later visit can finish it.
            saved.pop("predictions", None)
            saved["prediction_status"] = "refresh_required"
            converted_draft = draft_id is not None and saved["id"] != draft_id
            parameters_dirty.value = False
            state["message_kind"].value = "success"
            status_label = f"Run {saved['id']}" if converted_draft else label
            state["message"].value = f"{status_label} saved. Updating predictions..."
            state["project"].value = project
            if not converted_draft:
                request_prediction(project, saved["parameters"], True)
        except ValueError as exc:
            state["message_kind"].value = "error"
            state["message"].value = str(exc)

    def remove():
        project = deepcopy(state["project"].value)
        if draft_id is not None:
            project["draft_runs"] = [draft for draft in project["draft_runs"] if draft["id"] != draft_id]
        else:
            services.runs.delete(project, run_id)
        state["project"].value = project
        state["message_kind"].value = "success"
        state["message"].value = "Run deleted."

    with v.Html(tag="tr"):
        with v.Html(tag="td", style_="min-width: 220px"):
            solara.InputText(
                "Run and notes",
                value=edited_notes.value if edited_notes.value is not None else (
                    saved_notes if saved_notes is not None else label
                ),
                on_value=lambda value: edited_notes.set(value or ""),
                continuous_update=True,
                dense=True,
            )
        for parameter in state["project"].value["parameters"]:
            name = parameter["name"]
            with v.Html(tag="td"):
                solara.InputText(
                    name,
                    value=parameter_values.value.get(name, ""),
                    on_value=lambda value, name=name: update_parameter(name, value),
                    continuous_update=True,
                    dense=True,
                )
        for objective_index, objective in enumerate(objectives):
            name = objective["name"]
            # Highlight only saved best observations, not edited-but-unsaved values.
            is_best = (
                name in results and best_results is not None
                and name in best_results and results[name] == best_results[name]
            )
            if is_best:
                try:
                    is_best = float(values.value.get(name, "")) == results[name]
                except (TypeError, ValueError, OverflowError):
                    is_best = False
            cell_style = "padding: 4px"
            if objective_index == 0:
                cell_style += "; border-left: 3px solid #546e7a"
            if is_best:
                cell_style += "; background-color: #e8f5e9"
                if objective_index != 0:
                    cell_style += "; border-left: 3px solid #2e7d32"
            with v.Html(tag="td", style_=cell_style):
                solara.InputText(
                    name,
                    value=values.value.get(name, ""),
                    on_value=lambda value, name=name: values.set({**values.value, name: value or ""}),
                    continuous_update=True,
                    dense=True,
                )
                if is_best:
                    v.Html(tag="span", style_="color: #1b5e20; font-weight: bold", children=["Best observed"])
            parameters_changed = candidate is None and parameters_dirty.value
            if parameters_changed:
                prediction = None
            elif request is None:
                prediction = saved_row.get("predictions", {}).get(name) if saved_row is not None else None
            else:
                predictions = result["predictions"] if result and task.state == ResultState.FINISHED else None
                prediction = predictions.get(name) if predictions is not None else None
            if parameters_changed:
                display = "Save to update"
            elif prediction is not None:
                display = f"{prediction['mean']:.6g} ± {prediction['sigma']:.6g}"
            elif request and task.state not in (ResultState.FINISHED, ResultState.ERROR):
                display = "Updating..."
            else:
                display = "Unavailable"
            v.Html(tag="td", children=[display], style_="white-space: nowrap")
        with v.Html(tag="td"):
            solara.Button("Save", on_click=save, color="primary")
            solara.Button("Delete", on_click=on_delete_recommendation or remove, text=True)
            if request and result and result["error"]:
                v.Html(tag="div", children=[f"Prediction unavailable: {result['error']}"])
            elif request and result and result["predictions"] is None:
                v.Html(tag="div", children=["Prediction unavailable: no observed results."])
            elif request and task.state == ResultState.ERROR:
                v.Html(tag="div", children=["Prediction failed. Check the project and try again."])
