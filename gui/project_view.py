import json

import solara
from solara import lab

from gui.configuration import ParameterConfiguration
from gui.project_upload import ProjectUpload
from gui.runs_view import RunsView
from gui.session import set_project


@solara.component
def ProjectView(state, services):
    project = state["project"].value
    tab = solara.use_reactive(0)
    switching = solara.use_reactive(False)

    def replace_project(replacement):
        # Unmount editable rows and prediction tasks before installing the new project.
        switching.value = True
        try:
            set_project(state, replacement)
        finally:
            switching.value = False

    def name_project(value):
        project["name"] = value or "Untitled experiment"
        state["project"].value = dict(project)

    def download_json():
        return json.dumps(project, indent=2, ensure_ascii=False).encode("utf-8")

    solara.FileDownload(
        download_json,
        filename=f"{project['name'].replace(' ', '_')}.json",
        label="Download project JSON",
        mime_type="application/json",
    )
    solara.Warning(
        "No automatic save: download this JSON before closing or losing the session.",
    )
    if not switching.value:
        lab.Tabs(
            value=tab,
            children=[
                lab.Tab("Configuration"),
                lab.Tab("Runs and recommendations"),
            ],
        )
        if tab.value == 0:
            with solara.Card("Project JSON"):
                solara.InputText(
                    "Project name",
                    value=project["name"],
                    on_value=name_project,
                )
                solara.Markdown(
                    "Upload another project JSON to replace the current project. "
                    "Download the current project first to keep its changes."
                )
                ProjectUpload(state, services, on_load=replace_project)
            ParameterConfiguration(state, services.configuration)
        elif tab.value == 1:
            RunsView(state, services)
