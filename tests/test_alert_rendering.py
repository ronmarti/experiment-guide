import unittest

import ipyvuetify as v
import solara

from experiment.model.project import blank_project
from gui.alert_message import AlertMessage
from gui.project_selection import ProjectSelection
from gui.project_view import ProjectView
from gui.runs_view import RunsView


class AlertRenderingTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "authorized": solara.reactive(False),
            "project": solara.reactive(blank_project()),
            "message": solara.reactive(""),
            "message_kind": solara.reactive("info"),
        }

    def assert_alerts(self, element, expected):
        _, context = solara.render(element, handle_error=False)
        try:
            self.assertEqual(
                [(alert.type, alert.children[0]) for alert in context.find(v.Alert).widgets],
                expected,
            )
        finally:
            context.close()

    def test_warning_screens_render(self):
        self.assert_alerts(
            ProjectSelection(self.state),
            [("warning", "Changes are held only in this browser session. Download project JSON to save your work.")],
        )
        self.assert_alerts(
            ProjectView(self.state),
            [("warning", "No automatic save: download this JSON before closing or losing the session.")],
        )
        self.assert_alerts(
            RunsView(self.state),
            [("warning", "Configure at least one parameter and an objective first.")],
        )

    def test_feedback_severity_and_message(self):
        for kind in ("error", "success", "info"):
            with self.subTest(kind=kind):
                self.state["message_kind"].value = kind
                self.state["message"].value = "Feedback"
                self.assert_alerts(AlertMessage(self.state), [(kind, "Feedback")])


if __name__ == "__main__":
    unittest.main()
