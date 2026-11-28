import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reacton.ipyvuetify as v
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
    with v.Html(
        tag="section",
        style_="width: 100%; max-width: 1600px; margin: 0 auto; padding: 24px clamp(16px, 3vw, 40px); box-sizing: border-box; min-width: 0; overflow-x: auto",
    ):
        # Vuetify nests flex applications; the inner one must shrink for table scrollbars to work.
        solara.Style(".v-application .v-application { min-width: 0; }")
        solara.Markdown("# Adaptive Experimentation")
        if not state["authorized"].value:
            Startup(state)
        elif state["project"].value is None:
            ProjectSelection(state, services)
        else:
            ProjectView(state, services)
        with v.Html(tag="footer", style_="margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd"):
            v.Html(tag="span", children=["By Martin Ron | "])
            v.Html(
                tag="a",
                attributes={"href": "https://github.com/ronmarti/experiment-guide"},
                children=["GitHub"],
            )
