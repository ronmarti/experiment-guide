import unittest

import ipyvuetify as v
import solara

from experiment.model.project import blank_project
from gui.project_view import ProjectView
from gui.services import AppServices


class ProjectTabsTests(unittest.TestCase):
    def test_tab_navigation_and_project_update(self):
        state = {
            "authorized": solara.reactive(True),
            "project": solara.reactive(blank_project()),
            "message": solara.reactive(""),
            "message_kind": solara.reactive("info"),
        }
        _, context = solara.render(ProjectView(state, AppServices()), handle_error=False)
        try:
            context.find(v.Tabs).widget.v_model = 1
            self.assertEqual(context.find(v.Tabs).widget.v_model, 1)
            self.assertTrue(any(
                "Configure at least one parameter and an objective first." in alert.children
                for alert in context.find(v.Alert).widgets
            ))

            state["project"].value = {**state["project"].value, "name": "Renamed"}
            self.assertEqual(context.find(v.Tabs).widget.v_model, 1)

            self.assertTrue(any(
                "Generate batch" in button.children
                for button in context.find(v.Btn).widgets
            ))

            context.find(v.Tabs).widget.v_model = 0
            self.assertEqual(context.find(v.Tabs).widget.v_model, 0)
            self.assertTrue(any(
                "Add parameter" in button.children
                for button in context.find(v.Btn).widgets
            ))
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
