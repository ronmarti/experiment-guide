import solara


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
