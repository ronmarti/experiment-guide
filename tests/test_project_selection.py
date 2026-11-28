import json
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

import ipyvuetify as v
import solara

from experiment.model.project import blank_project, upgrade_project
from gui.services import AppServices
from gui.app import Page
from test_results_table import row_label, widgets


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
             patch("gui.startup.ACCESS_KEY", "test-key"):
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

    def test_page_content_has_spacing_through_project_selection(self):
        with patch("gui.app.session_state", return_value=self.state):
            root, context = solara.render(Page(), handle_error=False)
            try:
                def section():
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "section")

                self.assertIn("padding:", section().style_)
                self.assertIn("box-sizing: border-box", section().style_)
                self.assertIn("overflow-x: auto", section().style_)
                self.assertTrue(any(
                    ".v-application .v-application { min-width: 0; }" in getattr(w, "template", "")
                    for w in widgets(section())
                ))
                self.state["authorized"].value = True
                self.assertIn("padding:", section().style_)
                self.state["project"].value = blank_project()
                self.assertIn("padding:", section().style_)
                self.assertTrue(any("Add parameter" in b.children for b in context.find(v.Btn).widgets))
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
             patch("gui.startup.ACCESS_KEY", "test-key"), \
             patch("solara.FileDrop", file_drop):
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
                self.assertTrue(any("Load project JSON" in b.children for b in context.find(v.Btn).widgets))
            finally:
                context.close()

    def test_replacement_upload_preserves_current_project_on_error_and_resets_edits(self):
        project = blank_project("First")
        project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 10]}]
        project["objective"] = {"name": "score", "direction": "maximize"}
        project["runs"] = [{"id": 1, "parameters": {"x": 1}, "objective": 2}]
        replacement = blank_project("Second")
        replacement["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 20]}]
        replacement["objective"] = {"name": "score", "direction": "maximize"}
        replacement["runs"] = [{"id": 1, "parameters": {"x": 9}, "objective": 8}]
        self.state["authorized"].value = True
        self.state["project"].value = project
        upload = {"data": b"not JSON"}

        @solara.component
        def file_drop(label, lazy, on_file):
            solara.Button(label, on_click=lambda: on_file(upload))

        with patch("gui.app.session_state", return_value=self.state), patch("solara.FileDrop", file_drop):
            root, context = solara.render(Page(), handle_error=False)
            try:
                def click(label):
                    next(b for b in context.find(v.Btn).widgets if label in b.children).fire_event("click", {})

                field = next(w for w in context.find(v.TextField).widgets if w.label == "lower for parameter 1")
                field.v_model = "4"
                click("Add parameter")
                click("Load project JSON")
                self.assertEqual(self.state["project"].value, project)
                self.assertEqual(next(w for w in context.find(v.TextField).widgets if w.label == "lower for parameter 1").v_model, "4")
                self.assertTrue(any("Invalid project JSON:" in str(a.children) for a in context.find(v.Alert).widgets))

                upload["data"] = json.dumps(replacement).encode()
                click("Load project JSON")
                self.assertEqual(self.state["project"].value, replacement)
                self.assertEqual(next(w for w in context.find(v.TextField).widgets if w.label == "lower for parameter 1").v_model, "0")
                self.assertFalse(any(w.label.startswith("name for new parameter") for w in context.find(v.TextField).widgets))
                self.assertTrue(any("Load project JSON" in b.children for b in context.find(v.Btn).widgets))

                context.find(v.Tabs).widget.v_model = 1
                row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                           and w.children and row_label(w) == "Run 1")
                next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x").v_model = "3"
                upload["data"] = json.dumps(project).encode()
                click("Load project JSON")
                self.assertEqual(self.state["project"].value, project)
                self.assertEqual(context.find(v.Tabs).widget.v_model, 1)
                row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                           and w.children and row_label(w) == "Run 1")
                self.assertEqual(next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x").v_model, "1")
            finally:
                context.close()

    def test_login_then_create_blank_project(self):
        @solara.component
        def file_drop(label, lazy, on_file):
            solara.Button(label)

        with patch("gui.app.session_state", return_value=self.state), \
             patch("gui.startup.ACCESS_KEY", "test-key"), \
             patch("solara.FileDrop", file_drop):
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
                self.assertEqual(AppServices().files.load_json(json.dumps(expected).encode()), expected)
                self.assertTrue(any("Load project JSON" in b.children for b in context.find(v.Btn).widgets))
            finally:
                context.close()

    def test_replacement_cancels_old_project_prediction(self):
        project = blank_project("Test")
        project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 10]}]
        project["objective"] = {"name": "score", "direction": "maximize"}
        project["runs"] = [{"id": 1, "parameters": {"x": 1}, "objective": 2}]
        project["recommendation_batches"] = [{"candidates": [{"parameters": {"x": 3}}]}]
        replacement = deepcopy(project)
        replacement["recommendation_batches"][0]["candidates"][0]["notes"] = "Replacement"
        self.state["authorized"].value = True
        self.state["project"].value = project
        services = AppServices()
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()

        def predict(current, point):
            started.set()
            release.wait(5)
            completed.set()
            return {"score": {"mean": 4, "sigma": 0.5}}

        @solara.component
        def file_drop(label, lazy, on_file):
            solara.Button(label, on_click=lambda: on_file({"data": json.dumps(replacement).encode()}))

        with patch("gui.app.session_state", return_value=self.state), \
             patch("gui.app.AppServices", new=lambda: services), \
             patch("solara.FileDrop", file_drop), \
             patch.object(services.optimizer, "predict", side_effect=predict):
            root, context = solara.render(Page(), handle_error=False)
            try:
                context.find(v.Tabs).widget.v_model = 1
                row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                           and w.children and row_label(w) == "Batch 1, recommendation 1")
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                self.assertTrue(started.wait(5))
                next(b for b in context.find(v.Btn).widgets if "Load project JSON" in b.children).fire_event("click", {})
                release.set()
                self.assertTrue(completed.wait(5))
                time.sleep(0.1)
                self.assertEqual(self.state["project"].value, replacement)
            finally:
                release.set()
                context.close()


if __name__ == "__main__":
    unittest.main()
