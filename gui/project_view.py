import json

import solara
from solara import lab

from gui.configuration import ParameterConfiguration
from gui.runs_view import RunsView


@solara.component
def ProjectView(state, services):
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
        ParameterConfiguration(state, services.configuration)
    elif tab.value == 1:
        RunsView(state, services)
