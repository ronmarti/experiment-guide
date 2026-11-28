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
            field = next(w for w in context.find(v.TextField).widgets if w.label == "Project name")
            field.v_model = "My project"
            field.fire_event("focusout", {})
            self.assertEqual(state["project"].value["name"], "My project")
            context.find(v.Tabs).widget.v_model = 1
            self.assertFalse(any(w.label == "Project name" for w in context.find(v.TextField).widgets))
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
            self.assertEqual(next(w for w in context.find(v.TextField).widgets if w.label == "Project name").v_model, "Renamed")
            self.assertTrue(any(
                "Add parameter" in button.children
                for button in context.find(v.Btn).widgets
            ))
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
