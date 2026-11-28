import os

import reacton.ipyvue as vue
import solara

from gui.alert_message import AlertMessage
from gui.app_description import AppDescription

ACCESS_KEY = os.environ.get("APP_ACCESS_KEY", "change-me")


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
        AppDescription()
        key_field = solara.InputText(
            "Access key",
            value=key,
            password=True,
            on_value=lambda value: key.set(value or ""),
        )
        vue.use_event(key_field, "keyup.enter", lambda widget, event, data: authorize(widget.v_model))
        solara.Button("Authorize", on_click=lambda: authorize(key.value), color="primary")
        AlertMessage(state)
