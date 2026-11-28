import solara


def session_state():
    session_id = solara.get_session_id()
    # Reuse state within a session without sharing an active project across sessions.
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
