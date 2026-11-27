import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import solara

from gui.project_selection import ProjectSelection
from gui.project_view import ProjectView
from gui.session import session_state
from gui.services import AppServices
from gui.startup import Startup


@solara.component
def Page():
    state = session_state()
    services = solara.use_memo(AppServices, dependencies=[])
    if not state["authorized"].value:
        Startup(state)
    elif state["project"].value is None:
        ProjectSelection(state, services)
    else:
        ProjectView(state, services)
