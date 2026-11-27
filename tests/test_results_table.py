import json
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

import ipyvuetify as v
import solara

from experiment.model.project import blank_project, upgrade_project
from experiment.services.optimization import predict_candidate
from experiment.services.persistence import load_project_json
from experiment.services.runs import save_result
from gui.runs_view import RunsView


def widgets(root):
    yield root
    for child in getattr(root, "children", ()):
        if not isinstance(child, (str, int, float)):
            yield from widgets(child)


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for prediction refresh.")


class ResultsTableTests(unittest.TestCase):
    def setUp(self):
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
        prediction_patch = patch("gui.result_row.predict_candidate", return_value=None)
        prediction_patch.start()
        self.addCleanup(prediction_patch.stop)

    def test_table_precedes_generation_and_run_sections(self):
        project = self.state["project"].value
        project["runs"] = []
        project["recommendation_batches"] = []
        root, context = solara.render(RunsView(self.state), handle_error=False)
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
                runs = next(i for i, w in enumerate(all_widgets) if 'id="runs-and-recommendations"' in getattr(w, "template", ""))
                add_button = next(i for i, w in enumerate(all_widgets) if isinstance(w, v.Btn) and "Add run" in w.children)
                return content, generation, generate_button, runs, add_button

            order = ordered_widgets()
            self.assertEqual(order, tuple(sorted(order)))
            next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
            order = ordered_widgets()
            self.assertEqual(order, tuple(sorted(order)))
            self.assertEqual(len(self.state["project"].value["draft_runs"]), 1)
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
            root, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                def rows():
                    table = next(w for w in widgets(root) if getattr(w, "tag", None) == "table")
                    return [w for w in widgets(table) if getattr(w, "tag", None) == "tr"][1:]

                def labels():
                    return [row.children[0].children[0] for row in rows()]

                initial = ["Run 1", "Batch 1, recommendation 1", "Batch 1, recommendation 2"]
                self.assertEqual(labels(), initial)
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                first_draft = self.state["project"].value["draft_runs"][0]
                first_label = f"New run {first_draft['id'][:8]}"
                self.assertEqual(labels(), [*initial, first_label])
                next(w for w in widgets(rows()[-1]) if isinstance(w, v.TextField) and w.label == f"x for {first_label}").v_model = "8"

                with patch("gui.runs_view.generate_candidates", return_value=[{"parameters": {"x": 5}}]):
                    next(b for b in context.find(v.Btn).widgets if "Generate batch" in b.children).fire_event("click", {})
                new_candidate = "Batch 2, recommendation 1"
                self.assertEqual(labels(), [*initial, first_label, new_candidate])
                first_row = rows()[-2]
                self.assertEqual(next(w for w in widgets(first_row) if isinstance(w, v.TextField) and w.label == f"x for {first_label}").v_model, "8")

                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                second_draft = self.state["project"].value["draft_runs"][1]
                second_label = f"New run {second_draft['id'][:8]}"
                self.assertEqual(labels(), [*initial, first_label, new_candidate, second_label])
                first_row = rows()[-3]
                next(w for w in widgets(first_row) if isinstance(w, v.TextField) and w.label == f"Result for {first_label}").v_model = "9"
                next(w for w in widgets(first_row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                expected = [*initial, "Run 2", new_candidate, second_label]
                self.assertEqual(labels(), expected)

                uploaded["callback"]({"data": b"x,score\n4,2\n5,3\n"})
                expected += ["Run 3", "Run 4"]
                self.assertEqual(labels(), expected)
                project = self.state["project"].value
                restored = load_project_json(json.dumps(project).encode())
            finally:
                context.close()

            self.state["project"].value = restored
            root, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                self.assertEqual(labels(), expected)
                draft_row = next(row for row in rows() if row.children[0].children[0] == second_label)
                next(w for w in widgets(draft_row) if isinstance(w, v.TextField) and w.label == f"x for {second_label}").v_model = "7"
                recommendation_row = rows()[1]
                next(w for w in widgets(recommendation_row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
                expected = ["Run 1", "Batch 1, recommendation 1", "Run 2", new_candidate, second_label, "Run 3", "Run 4"]
                self.assertEqual(labels(), expected)
                draft_row = next(row for row in rows() if row.children[0].children[0] == second_label)
                self.assertEqual(next(w for w in widgets(draft_row) if isinstance(w, v.TextField) and w.label == f"x for {second_label}").v_model, "7")
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                last_draft = self.state["project"].value["draft_runs"][-1]
                self.assertEqual(labels(), [*expected, f"New run {last_draft['id'][:8]}"])
                load_project_json(json.dumps(self.state["project"].value).encode())
            finally:
                context.close()


    def test_edit_results_and_reload_without_duplicate_rows(self):
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            def rows():
                tables = [w for w in widgets(root) if getattr(w, "tag", None) == "table"]
                self.assertEqual(len(tables), 1)
                return [w for w in widgets(tables[0]) if getattr(w, "tag", None) == "tr"][1:]

            def row(label):
                return next(r for r in rows() if label in r.children[0].children)

            def save(label, value):
                current = row(label)
                field = next(w for w in widgets(current) if isinstance(w, v.TextField) and w.label == f"Result for {label}")
                field.v_model = value
                current = row(label)
                next(w for w in widgets(current) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})

            candidate = "Batch 1, recommendation 1"
            self.assertEqual(len(rows()), 3)
            self.assertEqual(next(w for w in widgets(row(candidate)) if isinstance(w, v.TextField) and w.label == f"Result for {candidate}").v_model, "")
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
            self.assertEqual(load_project_json(json.dumps(project).encode()), project)

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
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            def row(label):
                return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))

            def best(label):
                fields = {}
                for cell in row(label).children:
                    inputs = [w for w in widgets(cell) if isinstance(w, v.TextField)]
                    if inputs and any(getattr(w, "tag", None) == "span" and "Best observed" in w.children for w in widgets(cell)):
                        fields[inputs[0].label.split(" result for ")[0]] = True
                return set(fields)

            linked = "Batch 1, recommendation 1"
            pending = "Batch 1, recommendation 2"
            self.assertEqual(best(linked), {"score"})
            self.assertEqual(best("Run 3"), {"score"})
            self.assertEqual(best("Run 4"), {"cost"})
            self.assertEqual(best("Run 1"), set())
            self.assertEqual(best(pending), set())

            field = next(w for w in widgets(row("Run 3")) if isinstance(w, v.TextField) and w.label == "score result for Run 3")
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
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            def row(label):
                return next(
                    w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                    and w.children and label in getattr(w.children[0], "children", ())
                )

            first = "Batch 1, recommendation 1"
            second = "Batch 1, recommendation 2"
            next(w for w in widgets(row(second)) if isinstance(w, v.TextField) and w.label == f"Result for {second}").v_model = "9"
            next(w for w in widgets(row(first)) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["recommendation_batches"][0]["candidates"], [{"parameters": {"x": 7}}])
            self.assertEqual(project["runs"], [{"id": 1, "parameters": {"x": 1}, "objective": 2}])
            self.assertEqual(next(w for w in widgets(row(first)) if isinstance(w, v.TextField) and w.label == f"x for {first}").v_model, "7")
            self.assertEqual(next(w for w in widgets(row(first)) if isinstance(w, v.TextField) and w.label == f"Result for {first}").v_model, "9")
            next(w for w in widgets(row(first)) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["runs"][-1]["parameters"], {"x": 7})
            self.assertEqual(project["runs"][-1]["objective"], 9)
            self.assertEqual(load_project_json(json.dumps(project).encode()), project)
            next(w for w in widgets(row(first)) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["recommendation_batches"][0]["candidates"], [])
            self.assertEqual(len(project["runs"]), 1)
            self.assertEqual(load_project_json(json.dumps(project).encode()), project)
            with patch("gui.runs_view.generate_candidates", return_value=[{"parameters": {"x": 5}}]):
                next(b for b in context.find(v.Btn).widgets if "Generate batch" in b.children).fire_event("click", {})
            self.assertEqual(
                next(w for w in widgets(row("Batch 2, recommendation 1")) if isinstance(w, v.TextField) and w.label == "x for Batch 2, recommendation 1").v_model,
                "5",
            )
        finally:
            context.close()

    def test_delete_filled_recommendation_removes_only_its_linked_run(self):
        project = self.state["project"].value
        save_result(project, "4", batch_index=0, candidate_index=0)
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            label = "Batch 1, recommendation 1"
            row = next(
                w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                and w.children and label in getattr(w.children[0], "children", ())
            )
            self.assertEqual(
                [w.children for w in widgets(row) if isinstance(w, v.Btn) and any(str(c).startswith("Delete") for c in w.children)],
                [["Delete"]],
            )
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["runs"], [{"id": 1, "parameters": {"x": 1}, "objective": 2}])
            self.assertEqual(project["recommendation_batches"][0]["candidates"], [{"parameters": {"x": 3}}])
            self.assertEqual(load_project_json(json.dumps(project).encode()), project)
        finally:
            context.close()

    def test_delete_manual_run(self):
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            row = next(
                w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                and w.children and "Run 1" in getattr(w.children[0], "children", ())
            )
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["runs"], [])
            self.assertEqual(len(project["recommendation_batches"][0]["candidates"]), 2)
        finally:
            context.close()

    def test_generation_adds_pending_rows_and_respects_batch_size(self):
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            context.find(v.Slider).widget.v_model = 2
            with patch("gui.runs_view.generate_candidates", return_value=[
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
            self.assertTrue(any(
                w.label == "Result for Batch 2, recommendation 1" and w.v_model == ""
                for w in context.find(v.TextField).widgets
            ))
            self.assertIn("Predictions are unavailable", self.state["message"].value)
            rows = [w for w in widgets(root) if getattr(w, "tag", None) == "tr"]
            row = next(r for r in rows if r.children and "Batch 2, recommendation 1" in getattr(r.children[0], "children", ()))
            self.assertIn("2.5", [str(c.children[0]) for c in row.children if getattr(c, "tag", None) == "td" and c.children and isinstance(c.children[0], str)])
            self.assertIn("0.3", [str(c.children[0]) for c in row.children if getattr(c, "tag", None) == "td" and c.children and isinstance(c.children[0], str)])
            field = next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "x for Batch 2, recommendation 1")
            field.v_model = "4.0"
            row = next(r for r in widgets(root) if getattr(r, "tag", None) == "tr" and r.children and "Batch 2, recommendation 1" in getattr(r.children[0], "children", ()))
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
            _, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
                draft_id = self.state["project"].value["draft_runs"][0]["id"]
                label = f"New run {draft_id[:8]}"
                for field_label, value in ((f"x for {label}", "8"), (f"Result for {label}", "9")):
                    field = next(w for w in context.find(v.TextField).widgets if w.label == field_label)
                    field.v_model = value
                row = next(w for w in widgets(context.container) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
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

        with patch("gui.result_row.predict_candidate", side_effect=predict) as mock_predict:
            root, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                def row():
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
                def text_cells():
                    return [c.children[0] for c in row().children if getattr(c, "tag", None) == "td" and c.children and isinstance(c.children[0], str)]

                next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == f"x for {label}").v_model = "6"
                wait_for(lambda: "6" in text_cells() and "0.1" in text_cells())
                candidate = self.state["project"].value["recommendation_batches"][0]["candidates"][0]
                self.assertEqual(candidate["parameters"], {"x": 3})
                self.assertEqual(candidate["predictions"]["score"]["mean"], 2)

                next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == f"Result for {label}").v_model = "8"
                next(w for w in widgets(row()) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: self.state["project"].value["recommendation_batches"][0]["candidates"][0].get("predictions", {}).get("score", {}).get("sigma") == 0.2)
                project = self.state["project"].value
                self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["predictions"]["score"]["mean"], 6)
                self.assertEqual(project["runs"][-1]["objective"], 8)
                self.assertEqual(load_project_json(json.dumps(project).encode()), project)
                self.assertEqual(mock_predict.call_args.args[0]["runs"][-1]["objective"], 8)

                next(w for w in widgets(row()) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: mock_predict.call_count >= 3)
            finally:
                context.close()

    def test_edit_and_save_with_real_ax_model(self):
        project = self.state["project"].value
        project["runs"] = [
            {"id": 1, "parameters": {"x": 1}, "objective": 1},
            {"id": 2, "parameters": {"x": 5}, "objective": 5},
            {"id": 3, "parameters": {"x": 9}, "objective": 10},
        ]
        with patch("gui.result_row.predict_candidate", wraps=predict_candidate):
            root, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                def row():
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
                next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == f"x for {label}").v_model = "6"
                def predicted_mean():
                    cell = row().children[3]
                    try:
                        return float(cell.children[0])
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

        with patch("gui.result_row.predict_candidate", side_effect=predict):
            root, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                def row():
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
                def values():
                    return [c.children[0] for c in row().children if getattr(c, "tag", None) == "td" and c.children and isinstance(c.children[0], str)]
                field = next(w for w in widgets(row()) if isinstance(w, v.TextField) and w.label == f"x for {label}")
                field.v_model = "4"
                self.assertTrue(started.wait(5))
                field.v_model = "5"
                release.set()
                wait_for(lambda: "5" in values() and "0.5" in values())
                self.assertNotIn("4", values())
            finally:
                release.set()
                context.close()

    def test_save_retains_row_when_prediction_fails(self):
        with patch("gui.result_row.predict_candidate", side_effect=RuntimeError("Prediction failed. Check the project and try again.")):
            _, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                field = next(w for w in context.find(v.TextField).widgets if w.label == f"Result for {label}")
                field.v_model = "9"
                row = next(w for w in widgets(context.container) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
                next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                wait_for(lambda: "Prediction unavailable" in self.state["message"].value)
                project = self.state["project"].value
                self.assertEqual(project["runs"][-1]["objective"], 9)
                self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["prediction_status"], "refresh_required")
                self.assertEqual(load_project_json(json.dumps(project).encode()), project)
            finally:
                context.close()

    def test_save_refresh_retries_if_observations_change(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def predict(project, point):
            calls.append(project["runs"][0]["objective"])
            if len(calls) == 1:
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Prediction test timed out.")
            return {"score": {"mean": float(project["runs"][0]["objective"]), "sigma": 0.5}}

        with patch("gui.result_row.predict_candidate", side_effect=predict):
            root, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                def row(label):
                    return next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
                label = "Batch 1, recommendation 1"
                next(w for w in widgets(row(label)) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
                self.assertTrue(started.wait(5))
                next(w for w in widgets(row("Run 1")) if isinstance(w, v.TextField) and w.label == "Result for Run 1").v_model = "7"
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

        with patch("gui.result_row.predict_candidate", side_effect=predict):
            root, context = solara.render(RunsView(self.state), handle_error=False)
            label = "Batch 1, recommendation 1"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            try:
                self.assertTrue(started.wait(5))
                context.close()
                _, reopened = solara.render(RunsView(self.state), handle_error=False)
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

        with patch("gui.result_row.predict_candidate", side_effect=predict):
            root, context = solara.render(RunsView(self.state), handle_error=False)
            try:
                label = "Batch 1, recommendation 1"
                row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
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
        _, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            with patch("gui.runs_view.generate_candidates", side_effect=RuntimeError("Prediction failed. Check the project and try again.")):
                next(b for b in context.find(v.Btn).widgets if "Generate batch" in b.children).fire_event("click", {})
            self.assertEqual(len(self.state["project"].value["recommendation_batches"]), 1)
            self.assertEqual(self.state["message_kind"].value, "error")
            self.assertIn("Prediction failed", self.state["message"].value)
        finally:
            context.close()


    def test_edit_parameters_for_runs_and_recommendations(self):
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            def edit_and_save(label, parameter, result=None):
                row = next(
                    w for w in widgets(root)
                    if getattr(w, "tag", None) == "tr"
                    and w.children and label in getattr(w.children[0], "children", ())
                )
                next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == f"x for {label}").v_model = parameter
                if result is not None:
                    next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == f"Result for {label}").v_model = result
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
            self.assertEqual(load_project_json(json.dumps(project).encode()), project)
        finally:
            context.close()

    def test_blank_draft_can_be_saved_without_an_observation_and_restored(self):
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
            draft = self.state["project"].value["draft_runs"][0]
            label = f"New run {draft['id'][:8]}"
            field = next(w for w in context.find(v.TextField).widgets if w.label == f"x for {label}")
            self.assertEqual(field.v_model, "")
            self.assertEqual(len(self.state["project"].value["runs"]), 1)
            field.v_model = "8"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["draft_runs"][0]["parameters"], {"x": 8})
            self.assertEqual(len(project["runs"]), 1)
            self.assertEqual(load_project_json(json.dumps(project).encode()), project)
            next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == f"Result for {label}").v_model = "5"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Save" in w.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["draft_runs"], [])
            self.assertEqual(project["runs"][-1]["parameters"], {"x": 8})
            self.assertEqual(project["runs"][-1]["objective"], 5)
        finally:
            context.close()


    def test_multiple_blank_rows_can_be_deleted_independently(self):
        root, context = solara.render(RunsView(self.state), handle_error=False)
        try:
            for _ in range(2):
                next(b for b in context.find(v.Btn).widgets if "Add run" in b.children).fire_event("click", {})
            drafts = self.state["project"].value["draft_runs"]
            self.assertEqual(len(drafts), 2)
            label = f"New run {drafts[0]['id'][:8]}"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and label in getattr(w.children[0], "children", ()))
            next(w for w in widgets(row) if isinstance(w, v.Btn) and "Delete" in w.children).fire_event("click", {})
            self.assertEqual(self.state["project"].value["draft_runs"], [drafts[1]])
            self.assertEqual(len(self.state["project"].value["runs"]), 1)
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
