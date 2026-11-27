import json
import unittest
from unittest.mock import patch

import ipyvuetify as v
import solara

from experiment_core import blank_project, load_project_json, upgrade_project
from gui.app import Page


class ProjectSelectionTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "authorized": solara.reactive(False),
            "project": solara.reactive(None),
            "message": solara.reactive(""),
            "message_kind": solara.reactive("info"),
        }

    def test_enter_submits_key_without_leaving_input(self):
        with patch("gui.app.session_state", return_value=self.state), \
             patch("gui.app.ACCESS_KEY", "test-key"):
            _, context = solara.render(Page(), handle_error=False)
            try:
                field = context.find(v.TextField).widget
                field.v_model = "wrong"
                field.fire_event("keyup.enter", {})
                self.assertFalse(self.state["authorized"].value)
                self.assertIsNone(self.state["project"].value)
                self.assertTrue(any("Invalid access key." in a.children for a in context.find(v.Alert).widgets))

                field = context.find(v.TextField).widget
                field.v_model = "test-key"
                field.fire_event("keyup.enter", {})
                self.assertTrue(self.state["authorized"].value)
                self.assertIsNone(self.state["project"].value)
                self.assertTrue(any("Create blank project" in b.children for b in context.find(v.Btn).widgets))
            finally:
                context.close()

    def test_login_then_load_project(self):
        project = blank_project("Imported")
        project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 1]}]
        project["objective"] = {"name": "score", "direction": "maximize"}
        project["runs"] = [{"id": 1, "parameters": {"x": 0.5}, "objective": 3.0}]
        upload = {"data": b"not JSON"}

        @solara.component
        def file_drop(label, lazy, on_file):
            solara.Button(label, on_click=lambda: on_file(upload))

        with patch("gui.app.session_state", return_value=self.state), \
             patch("gui.app.ACCESS_KEY", "test-key"), \
             patch("gui.app.solara.FileDrop", file_drop):
            _, context = solara.render(Page(), handle_error=False)
            try:
                def click(label):
                    button = next(b for b in context.find(v.Btn).widgets if label in b.children)
                    button.fire_event("click", {})

                def enter_key(value):
                    field = next(w for w in context.find(v.TextField).widgets if w.label == "Access key")
                    field.v_model = value
                    field.fire_event("focusout", {})

                self.assertFalse(any("Load project JSON" in b.children for b in context.find(v.Btn).widgets))
                enter_key("wrong")
                click("Authorize")
                self.assertFalse(self.state["authorized"].value)
                self.assertIsNone(self.state["project"].value)
                self.assertTrue(any("Invalid access key." in a.children for a in context.find(v.Alert).widgets))
                self.assertFalse(any("Load project JSON" in b.children for b in context.find(v.Btn).widgets))

                enter_key("test-key")
                click("Authorize")
                self.assertTrue(self.state["authorized"].value)
                self.assertIsNone(self.state["project"].value)
                self.assertFalse(any(w.label == "Access key" for w in context.find(v.TextField).widgets))

                click("Load project JSON")
                self.assertIsNone(self.state["project"].value)
                self.assertTrue(any("Invalid project JSON:" in str(a.children) for a in context.find(v.Alert).widgets))
                upload["data"] = json.dumps(project).encode()
                click("Load project JSON")
                self.assertEqual(self.state["project"].value, project)
                self.assertTrue(any("Add parameter" in b.children for b in context.find(v.Btn).widgets))
            finally:
                context.close()

    def test_login_then_create_blank_project(self):
        with patch("gui.app.session_state", return_value=self.state), \
             patch("gui.app.ACCESS_KEY", "test-key"):
            _, context = solara.render(Page(), handle_error=False)
            try:
                field = context.find(v.TextField).widget
                field.v_model = "test-key"
                field.fire_event("focusout", {})
                context.find(v.Btn).widget.fire_event("click", {})
                name = next(w for w in context.find(v.TextField).widgets if w.label == "Project name")
                name.v_model = "New project"
                name.fire_event("focusout", {})
                button = next(b for b in context.find(v.Btn).widgets if "Create blank project" in b.children)
                button.fire_event("click", {})
                expected = blank_project("New project")
                upgrade_project(expected)
                self.assertEqual(self.state["project"].value, expected)
                self.assertEqual(load_project_json(json.dumps(expected).encode()), expected)
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
