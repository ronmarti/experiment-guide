import uuid

import reacton.ipyvuetify as v
import solara

from experiment.model.project import objectives_for
from experiment.services.configuration import delete_configuration, save_configuration
from experiment.services.constraints import validate_constraints
from gui.alert_message import AlertMessage
from gui.configuration_row import ConfigurationRow


@solara.component
def ParameterConfiguration(state):
    project = state["project"].value
    parameter_drafts = solara.use_reactive([])
    objective_drafts = solara.use_reactive([])
    constraint_drafts = solara.use_reactive([])

    def report_error(exc):
        state["message_kind"].value = "error"
        state["message"].value = str(exc)

    def save(kind, index, draft_id, fields):
        try:
            state["project"].value = save_configuration(state["project"].value, kind, index, fields)
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
        state["project"].value = delete_configuration(state["project"].value, kind, index)
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
