import solara


@solara.component
def ProjectUpload(state, services, on_load):
    def load_project(file):
        try:
            project = services.files.load_json(file["data"])
            on_load(project)
            state["message_kind"].value = "success"
            state["message"].value = "Project loaded."
        except ValueError as exc:
            state["message_kind"].value = "error"
            state["message"].value = str(exc)

    solara.FileDrop("Load project JSON", lazy=False, on_file=load_project)
