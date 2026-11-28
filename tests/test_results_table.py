import json
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

import ipyvuetify as v
import solara
from solara.util import IPYVUETIFY_V3

from experiment.model.project import blank_project, upgrade_project
from gui.runs_view import RunsView
from gui.services import AppServices


def widgets(root):
    yield root
    for child in getattr(root, "children", ()):
        if not isinstance(child, (str, int, float)):
            yield from widgets(child)


def row_label(row):
    return next(
        (field.v_model for field in widgets(row.children[0])
         if isinstance(field, v.TextField) and field.label == "Run and notes"),
        None,
    )


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for prediction refresh.")


class ResultsTableTests(unittest.TestCase):
    def setUp(self):
        self.services = AppServices()
        project = blank_project("Test")
        project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 10]}]
        project["objective"] = {"name": "score", "direction": "maximize"}
        project["runs"] = [{"id": 1, "parameters": {"x": 1}, "objective": 2}]
        project["recommendation_batches"] = [{
            "id": "batch",
            "candidates": [{"parameters": {"x": 3}}, {"parameters": {"x": 3}}],
        }]
        self.state = {
            "project": solara.reactive(project),
            "message": solara.reactive(""),
            "message_kind": solara.reactive("info"),
        }
        prediction_patch = patch.object(self.services.optimizer, "predict", return_value=None)
        prediction_patch.start()
        self.addCleanup(prediction_patch.stop)

    def test_heading_precedes_table_and_actions_follow_it(self):
        project = self.state["project"].value
        project["runs"] = []
        project["recommendation_batches"] = []
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            def ordered_widgets():
                all_widgets = list(widgets(root))
                content = next(
                    i for i, w in enumerate(all_widgets)
                    if getattr(w, "tag", None) == "table"
                    or "No runs or recommendations yet." in getattr(w, "template", "")
                )
                generation = next(i for i, w in enumerate(all_widgets) if 'id="generate-recommendations"' in getattr(w, "template", ""))
                generate_button = next(i for i, w in enumerate(all_widgets) if isinstance(w, v.Btn) and "Generate batch" in w.children)
                headings = [
                    i for i, w in enumerate(all_widgets)
                    if isinstance(getattr(w, "template", None), str)
                    and 'id="runs-and-recommendations"' in w.template
                ]
                self.assertEqual(len(headings), 1)
                add_button = next(i for i, w in enumerate(all_widgets) if isinstance(w, v.Btn) and "Add run" in w.children)
                return headings[0], content, generation, generate_button, add_button

            order = ordered_widgets()
            self.assertEqual(order, tuple(sorted(order)))
            next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
            order = ordered_widgets()
            self.assertEqual(order, tuple(sorted(order)))
            self.assertEqual(len(self.state["project"].value["draft_runs"]), 1)
        finally:
            context.close()

    def test_edit_notes_for_each_row_and_restore_after_draft_conversion(self):
        project = self.state["project"].value
        upgrade_project(project)
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            def row(label):
                return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                            and w.children and row_label(w) == label)

            def edit_notes(label, notes):
                current = row(label)
                next(w for w in widgets(current) if isinstance(w, v.TextField) and w.label == "Run and notes").v_model = notes
                next(w for w in widgets(current) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})

            edit_notes("Run 1", "Control run")
            edit_notes("Batch 1, recommendation 1", "Promising candidate")
            next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
            draft = self.state["project"].value["draft_runs"][0]
            edit_notes(f"New run {draft['id'][:8]}", "My draft")
            draft_row = row("My draft")
            next(w for w in widgets(draft_row) if isinstance(w, v.TextField) and w.label == "score").v_model = "5"
            next(w for w in widgets(draft_row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})

            project = self.state["project"].value
            self.assertEqual(project["runs"][0]["notes"], "Control run")
            self.assertEqual(project["runs"][-1]["notes"], "My draft")
            self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["notes"], "Promising candidate")
            restored = self.services.files.load_json(json.dumps(project).encode())
        finally:
            context.close()

        self.state["project"].value = restored
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            self.assertIsNotNone(row("Control run"))
            self.assertIsNotNone(row("Promising candidate"))
            self.assertIsNotNone(row("My draft"))
            candidate_row = row("Promising candidate")
            next(w for w in widgets(candidate_row) if isinstance(w, v.TextField) and w.label == "score").v_model = "7"
            next(w for w in widgets(candidate_row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            self.assertIsNotNone(row("Promising candidate"))
            edit_notes("Promising candidate", "")
            self.assertEqual(self.state["project"].value["recommendation_batches"][0]["candidates"][0]["notes"], "")
            self.assertEqual(
                self.services.files.load_json(json.dumps(self.state["project"].value).encode())
                ["recommendation_batches"][0]["candidates"][0]["notes"], "",
            )
        finally:
            context.close()

    def test_objectives_are_visibly_separated_and_inputs_use_names(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["parameters"].append({"name": "y", "type": "continuous", "bounds": [0, 10]})
        project["objectives"].append({"name": "cost", "direction": "minimize"})
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            table = next(w for w in widgets(root) if getattr(w, "tag", None) == "table")
            header, *rows = [w for w in widgets(table) if getattr(w, "tag", None) == "tr"]
            self.assertEqual(header.children[0].children, ["Run and notes"])
            self.assertEqual(
                [cell.children[0] for cell in header.children],
                ["Run and notes", "x", "y", "score observed", "score predicted mean ± sigma",
                 "cost observed", "cost predicted mean ± sigma", "Actions"],
            )
            self.assertIn("border-left: 3px", header.children[3].style_)
            for row in rows:
                fields = [w.label for w in widgets(row) if isinstance(w, v.TextField)]
                self.assertEqual(fields, ["Run and notes", "x", "y", "score", "cost"])
                self.assertEqual(len(row.children), len(header.children))
                self.assertIn("border-left: 3px", row.children[3].style_)
        finally:
            context.close()

    def test_runs_table_has_keyboard_accessible_horizontal_scroll(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["parameters"].append({"name": "y", "type": "continuous", "bounds": [0, 10]})
        project["objectives"].append({"name": "cost", "direction": "minimize"})
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            region = next(w for w in widgets(root) if getattr(w, "attributes", {}).get("aria-label") == "Runs and recommendations table")
            self.assertIn("overflow-x: auto", region.style_)
            self.assertIn("max-width: 100%", region.style_)
            self.assertEqual(region.attributes["tabindex"], "0")
            table = next(w for w in widgets(region) if getattr(w, "tag", None) == "table")
            header = next(w for w in widgets(table) if getattr(w, "tag", None) == "tr")
            self.assertTrue(all("min-width:" in cell.style_ for cell in header.children))
        finally:
            context.close()

    def test_categorical_choices_for_runs_recommendations_and_drafts(self):
        project = self.services.configuration.save(self.state["project"].value, "parameter", None, {
            "name": "color", "type": "categorical", "lower": "", "upper": "",
            "choices": "red, blue, warm green",
        })
        project["runs"][0]["parameters"]["color"] = "red"
        for candidate in project["recommendation_batches"][0]["candidates"]:
            candidate["parameters"]["color"] = "blue"
        self.state["project"].value = project

        def predict(current, point):
            return {"score": {"mean": 5 if point["color"] == "warm green" else 2, "sigma": 0.5}}

        with patch.object(self.services.optimizer, "predict", side_effect=predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                def row(label):
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                                and w.children and row_label(w) == label)

                def dropdown(label):
                    return next(w for w in widgets(row(label)) if isinstance(w, v.Select) and w.label == "color")

                def save(label):
                    next(w for w in widgets(row(label)) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})

                self.assertEqual(dropdown("Run 1").items, ["red", "blue", "warm green"])
                self.assertEqual(dropdown("Run 1").v_model, "red")
                self.assertTrue(any(isinstance(w, v.TextField) and w.label == "x" for w in widgets(row("Run 1"))))
                dropdown("Run 1").v_model = "blue"
                save("Run 1")
                self.assertEqual(self.state["project"].value["runs"][0]["parameters"]["color"], "blue")

                label = "Batch 1, recommendation 1"
                self.assertEqual(dropdown(label).v_model, "blue")
                dropdown(label).v_model = "warm green"
                wait_for(lambda: any(
                    getattr(c, "tag", None) == "td" and "5 ± 0.5" in c.children for c in row(label).children
                ))
                next(w for w in widgets(row(label)) if isinstance(w, v.TextField) and w.label == "score").v_model = "9"
                save(label)
                candidate = self.state["project"].value["recommendation_batches"][0]["candidates"][0]
                self.assertEqual(candidate["parameters"]["color"], "warm green")
                linked = next(run for run in self.state["project"].value["runs"] if run["id"] == candidate["run_id"])
                self.assertEqual(linked["parameters"]["color"], "warm green")
                dropdown(label).v_model = "red"
                save(label)
                self.assertEqual(self.state["project"].value["runs"][-1]["parameters"]["color"], "red")

                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                draft_id = self.state["project"].value["draft_runs"][0]["id"]
                label = f"New run {draft_id[:8]}"
                self.assertIsNone(dropdown(label).v_model)
                dropdown(label).v_model = "red"
                next(w for w in widgets(row(label)) if isinstance(w, v.TextField) and w.label == "x").v_model = "8"
                save(label)
                project = self.state["project"].value
                self.assertEqual(project["draft_runs"][0]["parameters"], {"x": 8, "color": "red"})
                restored = self.services.files.load_json(json.dumps(project).encode())
            finally:
                context.close()

            self.state["project"].value = restored
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                self.assertEqual(dropdown("Run 1").v_model, "blue")
                self.assertEqual(dropdown("Batch 1, recommendation 1").v_model, "red")
                self.assertEqual(dropdown(label).v_model, "red")
            finally:
                context.close()

    def test_obsolete_categorical_values_remain_visible_and_need_correction(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["parameters"].append({"name": "color", "type": "choice", "choices": ["red", "blue"]})
        project["runs"][0]["parameters"]["color"] = "retired"
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                       and w.children and row_label(w) == "Run 1")
            dropdown = next(w for w in widgets(row) if isinstance(w, v.Select) and w.label == "color")
            self.assertEqual(dropdown.items, ["red", "blue"])
            self.assertTrue(any("retired" in str(getattr(w, "children", ())) for w in widgets(row)))
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            self.assertEqual(self.state["project"].value["runs"][0]["parameters"]["color"], "retired")
            self.assertEqual(self.state["message_kind"].value, "error")
            dropdown.v_model = "red"
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            self.assertEqual(self.state["project"].value["runs"][0]["parameters"]["color"], "red")
        finally:
            context.close()

    def test_categorical_and_text_controls_share_row_spacing(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["parameters"].append({"name": "color", "type": "categorical", "choices": ["red", "blue"]})
        project["runs"][0]["parameters"]["color"] = "retired"
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            rows = [w for w in widgets(root) if getattr(w, "tag", None) == "tr"][1:]
            for row in rows:
                for cell in row.children:
                    controls = [w for w in widgets(cell) if isinstance(w, (v.TextField, v.Select))]
                    if not controls:
                        continue
                    self.assertIn("padding: 4px 8px", cell.style_)
                    self.assertIn("vertical-align: top", cell.style_)
                    for control in controls:
                        self.assertTrue(control.hide_details)
                        if IPYVUETIFY_V3:
                            self.assertEqual(control.density, "compact")
                        else:
                            self.assertTrue(control.dense)
        finally:
            context.close()

    def test_runs_and_recommendations_keep_insertion_order_after_save_and_reload(self):
        project = self.state["project"].value
        upgrade_project(project)
        uploaded = {}

        @solara.component
        def file_drop(label, lazy, on_file):
            uploaded["callback"] = on_file

        with patch("solara.FileDrop", file_drop):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                def rows():
                    table = next(w for w in widgets(root) if getattr(w, "tag", None) == "table")
                    return [w for w in widgets(table) if getattr(w, "tag", None) == "tr"][1:]

                def labels():
                    return [row_label(row) for row in rows()]

                initial = ["Run 1", "Batch 1, recommendation 1", "Batch 1, recommendation 2"]
                self.assertEqual(labels(), initial)
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                first_draft = self.state["project"].value["draft_runs"][0]
                first_label = f"New run {first_draft['id'][:8]}"
                self.assertEqual(labels(), [*initial, first_label])
                next(w for w in widgets(rows()[-1]) if isinstance(w, v.TextField) and w.label == "x").v_model = "8"

                with patch.object(self.services.optimizer, "generate", return_value=[{"parameters": {"x": 5}}]):
                    next(b for b in context.find(v.Btn).widgets if "Generate batch" in b.children).fire_event("click", {})
                new_candidate = "Batch 2, recommendation 1"
                self.assertEqual(labels(), [*initial, first_label, new_candidate])
                first_row = rows()[-2]
                self.assertEqual(next(w for w in widgets(first_row) if isinstance(w, v.TextField) and w.label == "x").v_model, "8")

                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                second_draft = self.state["project"].value["draft_runs"][1]
                second_label = f"New run {second_draft['id'][:8]}"
                self.assertEqual(labels(), [*initial, first_label, new_candidate, second_label])
                first_row = rows()[-3]
                next(w for w in widgets(first_row) if isinstance(w, v.TextField) and w.label == "score").v_model = "9"
                next(w for w in widgets(first_row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                expected = [*initial, "Run 2", new_candidate, second_label]
                self.assertEqual(labels(), expected)

                uploaded["callback"]({"data": b"x,score\n4,2\n5,3\n"})
                expected += ["Run 3", "Run 4"]
                self.assertEqual(labels(), expected)
                project = self.state["project"].value
                restored = self.services.files.load_json(json.dumps(project).encode())
            finally:
                context.close()

            self.state["project"].value = restored
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                self.assertEqual(labels(), expected)
                draft_row = next(row for row in rows() if row_label(row) == second_label)
                next(w for w in widgets(draft_row) if isinstance(w, v.TextField) and w.label == "x").v_model = "7"
                recommendation_row = rows()[1]
                next(w for w in widgets(recommendation_row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
                expected = ["Run 1", "Batch 1, recommendation 1", "Run 2", new_candidate, second_label, "Run 3", "Run 4"]
                self.assertEqual(labels(), expected)
                draft_row = next(row for row in rows() if row_label(row) == second_label)
                self.assertEqual(next(w for w in widgets(draft_row) if isinstance(w, v.TextField) and w.label == "x").v_model, "7")
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                last_draft = self.state["project"].value["draft_runs"][-1]
                self.assertEqual(labels(), [*expected, f"New run {last_draft['id'][:8]}"])
                self.services.files.load_json(json.dumps(self.state["project"].value).encode())
            finally:
                context.close()


    def test_edit_results_and_reload_without_duplicate_rows(self):
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            def rows():
                tables = [w for w in widgets(root) if getattr(w, "tag", None) == "table"]
                self.assertEqual(len(tables), 1)
                return [w for w in widgets(tables[0]) if getattr(w, "tag", None) == "tr"][1:]

            def row(label):
                return next(r for r in rows() if row_label(r) == label)

            def save(label, value):
                current = row(label)
                field = next(w for w in widgets(current) if isinstance(w, v.TextField) and w.label == "score")
                field.v_model = value
                current = row(label)
                next(w for w in widgets(current) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})

            candidate = "Batch 1, recommendation 1"
            self.assertEqual(len(rows()), 3)
            self.assertEqual(next(w for w in widgets(row(candidate)) if isinstance(w, v.TextField) and w.label == "score").v_model, "")
            save(candidate, "invalid")
            self.assertEqual(len(self.state["project"].value["runs"]), 1)
            self.assertEqual(self.state["message_kind"].value, "error")

            save(candidate, "4.5")
            project = self.state["project"].value
            self.assertEqual(len(project["runs"]), 2)
            self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["run_id"], 2)
            self.assertEqual(project["runs"][1]["objective"], 4.5)
            self.assertEqual(len(rows()), 3)

            save(candidate, "6")
            save("Run 1", "7")
            project = self.state["project"].value
            self.assertEqual(len(project["runs"]), 2)
            self.assertEqual([r["objective"] for r in project["runs"]], [7, 6])
            self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)

        finally:
            context.close()

    def test_best_observed_objectives_update_for_edits_deletes_and_direction(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["objectives"].extend([
            {"name": "cost", "direction": "minimize"},
            {"name": "unmeasured", "direction": "maximize"},
        ])
        project["runs"] = [
            {"id": 1, "parameters": {"x": 1}, "results": {"score": -3, "cost": 10}},
            {"id": 2, "parameters": {"x": 2}, "results": {"score": -1, "cost": 5}},
            {"id": 3, "parameters": {"x": 3}, "results": {"score": -1}},
            {"id": 4, "parameters": {"x": 4}, "results": {"cost": 0}},
        ]
        project["recommendation_batches"][0]["candidates"] = [
            {"parameters": {"x": 2}, "run_id": 2},
            {"parameters": {"x": 5}, "predictions": {"score": {"mean": 100, "sigma": 1}}},
        ]
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            def row(label):
                return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)

            def best(label):
                fields = {}
                for cell in row(label).children:
                    inputs = [w for w in widgets(cell) if isinstance(w, v.TextField)]
                    if inputs and any(getattr(w, "tag", None) == "span" and "Best observed" in w.children for w in widgets(cell)):
                        fields[inputs[0].label] = True
                return set(fields)

            linked = "Batch 1, recommendation 1"
            pending = "Batch 1, recommendation 2"
            self.assertEqual(best(linked), {"score"})
            self.assertEqual(best("Run 3"), {"score"})
            self.assertEqual(best("Run 4"), {"cost"})
            self.assertEqual(best("Run 1"), set())
            self.assertEqual(best(pending), set())

            field = next(w for w in widgets(row("Run 3")) if isinstance(w, v.TextField) and w.label == "score")
            field.v_model = "50"
            self.assertEqual(best("Run 3"), set())
            self.assertEqual(best(linked), {"score"})
            next(w for w in widgets(row("Run 3")) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            self.assertEqual(best("Run 3"), {"score"})
            self.assertEqual(best(linked), set())

            next(w for w in widgets(row("Run 3")) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            self.assertEqual(best(linked), {"score"})
            next(w for w in widgets(row("Run 4")) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            self.assertEqual(best(linked), {"score", "cost"})

            updated = deepcopy(self.state["project"].value)
            updated["objectives"][0]["direction"] = "minimize"
            self.state["project"].value = updated
            self.assertEqual(best("Run 1"), {"score"})
            self.assertEqual(best(linked), {"cost"})
        finally:
            context.close()

    def test_delete_pending_recommendation_preserves_other_row_edits(self):
        project = self.state["project"].value
        project["recommendation_batches"][0]["candidates"][1]["parameters"] = {"x": 7}
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            def row(label):
                return next(
                    w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                    and w.children and row_label(w) == label
                )

            first = "Batch 1, recommendation 1"
            second = "Batch 1, recommendation 2"
            next(w for w in widgets(row(second)) if isinstance(w, v.TextField) and w.label == "score").v_model = "9"
            next(w for w in widgets(row(first)) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["recommendation_batches"][0]["candidates"], [{"parameters": {"x": 7}}])
            self.assertEqual(project["runs"], [{"id": 1, "parameters": {"x": 1}, "objective": 2}])
            self.assertEqual(next(w for w in widgets(row(first)) if isinstance(w, v.TextField) and w.label == "x").v_model, "7")
            self.assertEqual(next(w for w in widgets(row(first)) if isinstance(w, v.TextField) and w.label == "score").v_model, "9")
            next(w for w in widgets(row(first)) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["runs"][-1]["parameters"], {"x": 7})
            self.assertEqual(project["runs"][-1]["objective"], 9)
            self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
            next(w for w in widgets(row(first)) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["recommendation_batches"][0]["candidates"], [])
            self.assertEqual(len(project["runs"]), 1)
            self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
            with patch.object(self.services.optimizer, "generate", return_value=[{"parameters": {"x": 5}}]):
                next(b for b in context.find(v.Btn).widgets if "Generate batch" in b.children).fire_event("click", {})
            self.assertEqual(
                next(w for w in widgets(row("Batch 2, recommendation 1")) if isinstance(w, v.TextField) and w.label == "x").v_model,
                "5",
            )
        finally:
            context.close()

    def test_delete_filled_recommendation_removes_only_its_linked_run(self):
        project = self.state["project"].value
        self.services.runs.save(project, "4", batch_index=0, candidate_index=0)
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            label = "Batch 1, recommendation 1"
            row = next(
                w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                and w.children and row_label(w) == label
            )
            self.assertEqual(
                [w.children for w in widgets(row) if isinstance(w, v.Btn) and any(str(c).startswith("Delete") for c in w.children)],
                [["Delete"]],
            )
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["runs"], [{"id": 1, "parameters": {"x": 1}, "objective": 2}])
            self.assertEqual(project["recommendation_batches"][0]["candidates"], [{"parameters": {"x": 3}}])
            self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
        finally:
            context.close()

    def test_delete_manual_run(self):
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            row = next(
                w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                and w.children and row_label(w) == "Run 1"
            )
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["runs"], [])
            self.assertEqual(len(project["recommendation_batches"][0]["candidates"]), 2)
        finally:
            context.close()

    def test_generation_adds_pending_rows_and_respects_batch_size(self):
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            context.find(v.Slider).widget.v_model = 2
            with patch.object(self.services.optimizer, "generate", return_value=[
                {"parameters": {"x": 4}, "predictions": {"score": {"mean": 2.5, "sigma": 0.3}}},
                {"parameters": {"x": 5}, "prediction_status": "model_unavailable"},
            ]) as generate:
                button = next(b for b in context.find(v.Btn).widgets if "Generate batch" in b.children)
                button.fire_event("click", {})
            self.assertEqual(generate.call_args.args[1], 2)
            project = self.state["project"].value
            self.assertEqual(len(project["runs"]), 1)
            self.assertEqual(len(project["recommendation_batches"]), 2)
            self.assertEqual(len([w for w in widgets(root) if getattr(w, "tag", None) == "table"]), 1)
            self.assertIn("Predictions are unavailable", self.state["message"].value)
            rows = [w for w in widgets(root) if getattr(w, "tag", None) == "tr"]
            row = next(r for r in rows if r.children and row_label(r) == "Batch 2, recommendation 1")
            self.assertEqual(next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "score").v_model, "")
            self.assertIn("2.5 ± 0.3", [str(c.children[0]) for c in row.children if getattr(c, "tag", None) == "td" and c.children and isinstance(c.children[0], str)])
            field = next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x")
            field.v_model = "4.0"
            row = next(r for r in widgets(root) if getattr(r, "tag", None) == "tr" and r.children and row_label(r) == "Batch 2, recommendation 1")
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            wait_for(lambda: self.state["project"].value["recommendation_batches"][1]["candidates"][0].get("prediction_status") == "model_unavailable")
        finally:
            context.close()

    def test_manual_run_and_atomic_csv_import(self):
        uploaded = {}

        @solara.component
        def file_drop(label, lazy, on_file):
            uploaded["callback"] = on_file

        with patch("solara.FileDrop", file_drop):
            _, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                draft_id = self.state["project"].value["draft_runs"][0]["id"]
                label = f"New run {draft_id[:8]}"
                row = next(w for w in widgets(context.container) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                for field_label, value in (("x", "8"), ("score", "9")):
                    field = next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == field_label)
                    field.v_model = value
                row = next(w for w in widgets(context.container) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                self.assertEqual(self.state["project"].value["runs"][-1]["objective"], 9)

                uploaded["callback"]({"data": b"x,score\n4,2\n11,3\n"})
                self.assertEqual(len(self.state["project"].value["runs"]), 2)
                self.assertIn("CSV row 3", self.state["message"].value)
                uploaded["callback"]({"data": b"x,score\n4,2\n5,3\n"})
                self.assertEqual(len(self.state["project"].value["runs"]), 4)
            finally:
                context.close()


    def test_predictions_refresh_on_edit_and_save(self):
        project = self.state["project"].value
        project["recommendation_batches"][0]["candidates"][0]["predictions"] = {"score": {"mean": 2, "sigma": 0.5}}

        def predict(current, point):
            return {"score": {"mean": float(point["x"]), "sigma": len(current["runs"]) / 10}}

        with patch.object(self.services.optimizer, "predict", side_effect=predict) as mock_predict:
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                def row():
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                def text_cells():
                    return [c.children[0] for c in row().children if getattr(c, "tag", None) == "td" and c.children and isinstance(c.children[0], str)]

                next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == "x").v_model = "6"
                wait_for(lambda: "6 ± 0.1" in text_cells())
                candidate = self.state["project"].value["recommendation_batches"][0]["candidates"][0]
                self.assertEqual(candidate["parameters"], {"x": 3})
                self.assertEqual(candidate["predictions"]["score"]["mean"], 2)

                next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == "score").v_model = "8"
                next(w for w in widgets(row()) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: self.state["project"].value["recommendation_batches"][0]["candidates"][0].get("predictions", {}).get("score", {}).get("sigma") == 0.2)
                project = self.state["project"].value
                self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["predictions"]["score"]["mean"], 6)
                self.assertEqual(project["runs"][-1]["objective"], 8)
                self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
                self.assertEqual(mock_predict.call_args.args[0]["runs"][-1]["objective"], 8)

                next(w for w in widgets(row()) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: mock_predict.call_count >= 3)
            finally:
                context.close()

    def test_manual_draft_prediction_is_saved_refreshed_and_restored(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["objectives"].append({"name": "cost", "direction": "minimize"})

        def predict(current, point):
            return {
                "score": {"mean": float(point["x"]), "sigma": 0.25},
                "cost": {"mean": 12, "sigma": 2},
            }

        with patch.object(self.services.optimizer, "predict", side_effect=predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                draft_id = self.state["project"].value["draft_runs"][0]["id"]
                label = f"New run {draft_id[:8]}"
                def row():
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                                and w.children and row_label(w) == label)
                def text_cells():
                    return [c.children[0] for c in row().children if c.children and isinstance(c.children[0], str)]
                next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == "x").v_model = "4"
                next(w for w in widgets(row()) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: "4 ± 0.25" in text_cells() and "12 ± 2" in text_cells())
                self.assertEqual(len(self.state["project"].value["runs"]), 1)
                next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == "x").v_model = "6"
                self.assertIn("Save to update", text_cells())
                next(w for w in widgets(row()) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: "6 ± 0.25" in text_cells())
                restored = self.services.files.load_json(json.dumps(self.state["project"].value).encode())
            finally:
                context.close()

            self.state["project"].value = restored
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                self.assertIn("6 ± 0.25", text_cells())
                self.assertIn("12 ± 2", text_cells())
            finally:
                context.close()

    def test_converted_draft_resumes_interrupted_prediction(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def predict(project, point):
            calls.append(dict(point))
            if len(calls) == 1:
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Prediction test timed out.")
            return {"score": {"mean": 7, "sigma": 0.4}}

        with patch.object(self.services.optimizer, "predict", side_effect=predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                draft = self.state["project"].value["draft_runs"][0]
                label = f"New run {draft['id'][:8]}"
                row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                           and w.children and row_label(w) == label)
                next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x").v_model = "4"
                next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "score").v_model = "8"
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                self.assertTrue(started.wait(5))
                self.assertEqual(self.state["project"].value["runs"][-1]["prediction_status"], "refresh_required")
                restored = self.services.files.load_json(json.dumps(self.state["project"].value).encode())
                context.close()
                self.state["project"].value = restored
                root, reopened = solara.render(RunsView(self.state, self.services), handle_error=False)
                try:
                    wait_for(lambda: self.state["project"].value["runs"][-1].get("predictions", {}).get("score", {}).get("mean") == 7)
                    row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                               and w.children and row_label(w) == "Run 2")
                    self.assertIn("7 ± 0.4", [c.children[0] for c in row.children if c.children and isinstance(c.children[0], str)])
                finally:
                    reopened.close()
            finally:
                release.set()
                context.close()

    def test_manual_draft_prediction_with_real_ax_model(self):
        project = self.state["project"].value
        project["runs"] = [
            {"id": 1, "parameters": {"x": 1}, "objective": 1},
            {"id": 2, "parameters": {"x": 5}, "objective": 5},
            {"id": 3, "parameters": {"x": 9}, "objective": 10},
        ]
        with patch.object(self.services.optimizer, "predict", wraps=AppServices().optimizer.predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                draft = self.state["project"].value["draft_runs"][0]
                label = f"New run {draft['id'][:8]}"
                row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                           and w.children and row_label(w) == label)
                next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x").v_model = "6"
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: "predictions" in self.state["project"].value["draft_runs"][0], timeout=30)
                prediction = self.state["project"].value["draft_runs"][0]["predictions"]["score"]
                self.assertGreaterEqual(prediction["sigma"], 0)
                self.assertIn(f"{prediction['mean']:.6g} ± {prediction['sigma']:.6g}",
                              [c.children[0] for c in row.children if c.children and isinstance(c.children[0], str)])
            finally:
                context.close()

    def test_manual_draft_without_observations_reports_unavailable(self):
        self.state["project"].value["runs"] = []
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
            draft = self.state["project"].value["draft_runs"][0]
            label = f"New run {draft['id'][:8]}"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                       and w.children and row_label(w) == label)
            next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x").v_model = "4"
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            wait_for(lambda: self.state["project"].value["draft_runs"][0].get("prediction_status") == "model_unavailable")
            self.assertEqual(self.state["message_kind"].value, "warning")
            self.assertIn("at least one observed result", self.state["message"].value)
        finally:
            context.close()

    def test_edit_and_save_with_real_ax_model(self):
        project = self.state["project"].value
        project["runs"] = [
            {"id": 1, "parameters": {"x": 1}, "objective": 1},
            {"id": 2, "parameters": {"x": 5}, "objective": 5},
            {"id": 3, "parameters": {"x": 9}, "objective": 10},
        ]
        with patch.object(self.services.optimizer, "predict", wraps=AppServices().optimizer.predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                def row():
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == "x").v_model = "6"
                def predicted_mean():
                    cell = row().children[3]
                    try:
                        return float(cell.children[0].split(" ± ")[0])
                    except (ValueError, TypeError):
                        return None
                wait_for(lambda: predicted_mean() is not None, timeout=30)
                preview = predicted_mean()
                next(w for w in widgets(row()) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: "predictions" in self.state["project"].value["recommendation_batches"][0]["candidates"][0], timeout=30)
                candidate = self.state["project"].value["recommendation_batches"][0]["candidates"][0]
                self.assertEqual(candidate["parameters"], {"x": 6})
                self.assertAlmostEqual(candidate["predictions"]["score"]["mean"], preview, places=4)
                self.assertGreaterEqual(candidate["predictions"]["score"]["sigma"], 0)
            finally:
                context.close()

    def test_newer_parameter_edit_wins_over_slow_prediction(self):
        started = threading.Event()
        release = threading.Event()
        def predict(project, point):
            if point["x"] == "4":
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Prediction test timed out.")
            return {"score": {"mean": float(point["x"]), "sigma": 0.5}}

        with patch.object(self.services.optimizer, "predict", side_effect=predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                def row():
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                def values():
                    return [c.children[0] for c in row().children if getattr(c, "tag", None) == "td" and c.children and isinstance(c.children[0], str)]
                field = next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == "x")
                field.v_model = "4"
                self.assertTrue(started.wait(5))
                field.v_model = "5"
                release.set()
                wait_for(lambda: "5 ± 0.5" in values())
                self.assertNotIn("4 ± 0.5", values())
            finally:
                release.set()
                context.close()

    def test_save_retains_row_when_prediction_fails(self):
        with patch.object(self.services.optimizer, "predict", side_effect=RuntimeError("Prediction failed. Check the project and try again.")):
            _, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                row = next(w for w in widgets(context.container) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                field = next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "score")
                field.v_model = "9"
                row = next(w for w in widgets(context.container) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: "Prediction unavailable" in self.state["message"].value)
                project = self.state["project"].value
                self.assertEqual(project["runs"][-1]["objective"], 9)
                self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["prediction_status"], "refresh_required")
                self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
            finally:
                context.close()

    def test_save_refresh_retries_if_observations_change(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def predict(project, point):
            if point["x"] == 3:
                calls.append(project["runs"][0]["objective"])
            if len(calls) == 1:
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Prediction test timed out.")
            return {"score": {"mean": float(project["runs"][0]["objective"]), "sigma": 0.5}}

        with patch.object(self.services.optimizer, "predict", side_effect=predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                def row(label):
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                label = "Batch 1, recommendation 1"
                next(w for w in widgets(row(label)) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                self.assertTrue(started.wait(5))
                next(w for w in widgets(row("Run 1")) if isinstance(w, v.TextField) and w.label == "score").v_model = "7"
                next(w for w in widgets(row("Run 1")) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                release.set()
                wait_for(lambda: self.state["project"].value["recommendation_batches"][0]["candidates"][0].get("predictions", {}).get("score", {}).get("mean") == 7)
                self.assertEqual(calls, [2, 7])
            finally:
                release.set()
                context.close()

    def test_interrupted_saved_refresh_resumes_on_reopen(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def predict(project, point):
            calls.append(dict(point))
            if len(calls) == 1:
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Prediction test timed out.")
            return {"score": {"mean": 4.0, "sigma": 0.3}}

        with patch.object(self.services.optimizer, "predict", side_effect=predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            label = "Batch 1, recommendation 1"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            try:
                self.assertTrue(started.wait(5))
                context.close()
                _, reopened = solara.render(RunsView(self.state, self.services), handle_error=False)
                try:
                    wait_for(lambda: self.state["project"].value["recommendation_batches"][0]["candidates"][0].get("predictions", {}).get("score", {}).get("mean") == 4)
                    self.assertGreaterEqual(len(calls), 2)
                finally:
                    reopened.close()
            finally:
                release.set()

    def test_deleting_a_row_cancels_its_prediction_update(self):
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        def predict(project, point):
            started.set()
            release.wait(5)
            completed.set()
            return {"score": {"mean": 4.0, "sigma": 0.3}}

        with patch.object(self.services.optimizer, "predict", side_effect=predict):
            root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                self.assertTrue(started.wait(5))
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
                release.set()
                self.assertTrue(completed.wait(5))
                time.sleep(0.1)
                self.assertEqual(self.state["project"].value["recommendation_batches"][0]["candidates"], [{"parameters": {"x": 3}}])
            finally:
                release.set()
                context.close()


    def test_prediction_failure_does_not_add_a_batch(self):
        _, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            with patch.object(self.services.optimizer, "generate", side_effect=RuntimeError("Prediction failed. Check the project and try again.")):
                next(b for b in context.find(v.Btn).widgets if "Generate batch" in b.children).fire_event("click", {})
            self.assertEqual(len(self.state["project"].value["recommendation_batches"]), 1)
            self.assertEqual(self.state["message_kind"].value, "error")
            self.assertIn("Prediction failed", self.state["message"].value)
        finally:
            context.close()


    def test_edit_parameters_for_runs_and_recommendations(self):
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            def edit_and_save(label, parameter, result=None):
                row = next(
                    w for w in widgets(root)
                    if getattr(w, "tag", None) == "tr"
                    and w.children and row_label(w) == label
                )
                next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x").v_model = parameter
                if result is not None:
                    next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "score").v_model = result
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})

            label = "Batch 1, recommendation 1"
            edit_and_save(label, "99")
            self.assertEqual(self.state["message_kind"].value, "error")
            self.assertEqual(self.state["project"].value["recommendation_batches"][0]["candidates"][0]["parameters"]["x"], 3)

            edit_and_save(label, "4")
            project = self.state["project"].value
            self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["parameters"]["x"], 4)
            self.assertEqual(len(project["runs"]), 1)

            edit_and_save(label, "5", "10")
            edit_and_save(label, "6", "11")
            edit_and_save("Run 1", "7")
            project = self.state["project"].value
            self.assertEqual(project["runs"][0]["parameters"], {"x": 7})
            self.assertEqual(project["runs"][1]["parameters"], {"x": 6})
            self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["parameters"], {"x": 6})
            self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
        finally:
            context.close()

    def test_blank_draft_can_be_saved_without_an_observation_and_restored(self):
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
            draft = self.state["project"].value["draft_runs"][0]
            label = f"New run {draft['id'][:8]}"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
            field = next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x")
            self.assertEqual(field.v_model, "")
            self.assertEqual(len(self.state["project"].value["runs"]), 1)
            field.v_model = "8"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["draft_runs"][0]["parameters"], {"x": 8})
            self.assertEqual(len(project["runs"]), 1)
            self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
            next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "score").v_model = "5"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["draft_runs"], [])
            self.assertEqual(project["runs"][-1]["parameters"], {"x": 8})
            self.assertEqual(project["runs"][-1]["objective"], 5)
        finally:
            context.close()


    def test_multiple_blank_rows_can_be_deleted_independently(self):
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            for _ in range(2):
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
            drafts = self.state["project"].value["draft_runs"]
            self.assertEqual(len(drafts), 2)
            label = f"New run {drafts[0]['id'][:8]}"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == label)
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            self.assertEqual(self.state["project"].value["draft_runs"], [drafts[1]])
            self.assertEqual(len(self.state["project"].value["runs"]), 1)
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
