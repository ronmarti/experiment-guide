import solara

from experiment.model.project import blank_project, upgrade_project
from gui.alert_message import AlertMessage
from gui.project_upload import ProjectUpload
from gui.session import set_project


@solara.component
def ProjectSelection(state, services):
    project_name = solara.use_reactive("Untitled experiment")

    def create_project():
        project = blank_project(project_name.value or "Untitled experiment")
        upgrade_project(project)
        set_project(state, project)
        state["message_kind"].value = "success"
        state["message"].value = "Blank project created."

    with solara.Card("Start a project"):
        solara.Warning(
            "Changes are held only in this browser session. Download project JSON to save your work.",
        )
        solara.InputText("Project name", value=project_name)
        solara.Button("Create blank project", on_click=create_project)
        ProjectUpload(state, services, on_load=lambda project: set_project(state, project))
        AlertMessage(state)
