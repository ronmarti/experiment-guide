import uuid
from copy import deepcopy

import reacton.ipyvuetify as v
import solara
from solara.datatypes import ResultState

from experiment.model.project import objectives_for
from experiment.services.optimization import predict_candidate
from experiment.services.runs import delete_run, save_result


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
