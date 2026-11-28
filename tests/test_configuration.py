import json
import unittest
from unittest.mock import Mock, patch

import ipyvuetify as v
import solara
from solara.util import IPYVUETIFY_V3

from experiment.model.project import blank_project, upgrade_project
from experiment.services.optimization import AxOptimizer
from gui.configuration import ParameterConfiguration
from gui.runs_view import RunsView
from gui.services import AppServices
from test_results_table import row_label, widgets


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.services = AppServices()
        project = blank_project("Test")
        project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 10]}]
        project["objective"] = {"name": "score", "direction": "maximize"}
        project["runs"] = [{"id": 1, "parameters": {"x": 2}, "objective": 3.0}]
        project["recommendation_batches"] = [{
            "id": "batch", "candidates": [{"parameters": {"x": 2}, "run_id": 1}],
        }]
        self.state = {
            "project": solara.reactive(project),
            "message": solara.reactive(""),
            "message_kind": solara.reactive("info"),
        }
        prediction_patch = patch.object(self.services.optimizer, "predict", return_value=None)
        prediction_patch.start()
        self.addCleanup(prediction_patch.stop)

    def test_tables_add_edit_delete_and_preserve_measurements(self):
        root, context = solara.render(ParameterConfiguration(self.state, self.services.configuration), handle_error=False)
        try:
            def click(label):
                next(b for b in context.find(v.Btn).widgets if label in b.children).fire_event("click", {})

            def field(prefix):
                return next(w for w in context.find(v.TextField).widgets if w.label.startswith(prefix))

            def save_row(prefix):
                row = next(
                    w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                    and any(isinstance(c, v.TextField) and c.label.startswith(prefix) for c in widgets(w))
                )
                next(b for b in widgets(row) if isinstance(b, v.Btn) and "Save" in b.children).fire_event("click", {})

            tables = [w for w in widgets(root) if getattr(w, "tag", None) == "table"]
            self.assertEqual(len(tables), 3)
            field("name for parameter 1").v_model = "temperature"
            save_row("name for parameter 1")
            project = self.state["project"].value
            self.assertEqual(project["schema_version"], 2)
            self.assertEqual(project["runs"][0]["parameters"], {"temperature": 2})
            self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["parameters"], {"temperature": 2})
            self.assertEqual(project["runs"][0]["results"], {"score": 3})

            click("Add parameter")
            field("name for new parameter").v_model = "count"
            field("lower for new parameter").v_model = "0"
            field("upper for new parameter").v_model = "10"
            save_row("name for new parameter")
            self.assertEqual(len(self.state["project"].value["parameters"]), 2)
            self.assertEqual(self.state["project"].value["runs"][0]["parameters"], {"temperature": 2})
            with self.assertRaisesRegex(ValueError, "Run 1.*count"):
                self.services.optimizer.generate(self.state["project"].value, 1)

            click("Add objective")
            field("name for new objective").v_model = "cost"
            select = next(w for w in context.find(v.Select).widgets if w.label.startswith("direction for new objective"))
            select.v_model = "minimize"
            save_row("name for new objective")
            project = self.state["project"].value
            self.assertEqual(project["objectives"], [
                {"name": "score", "direction": "maximize"},
                {"name": "cost", "direction": "minimize"},
            ])
            self.assertEqual(project["runs"][0]["results"], {"score": 3})
            self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)

            click("Add constraint")
            field("expression for new constraint").v_model = "temperature + count <= 12"
            save_row("expression for new constraint")
            self.assertEqual(self.state["project"].value["parameter_constraints"], ["temperature + count <= 12"])

            row = next(
                w for w in widgets(root) if getattr(w, "tag", None) == "tr"
                and any(isinstance(c, v.TextField) and c.label.startswith("expression for constraint 1") for c in widgets(w))
            )
            next(b for b in widgets(row) if isinstance(b, v.Btn) and "Delete" in b.children).fire_event("click", {})
            self.assertEqual(self.state["project"].value["parameter_constraints"], [])
        finally:
            context.close()

    def test_parameter_rows_keep_controls_aligned_for_each_type(self):
        project = self.state["project"].value
        project["parameters"].append({"name": "color", "type": "categorical", "choices": ["red", "blue"]})
        root, context = solara.render(ParameterConfiguration(self.state, self.services.configuration), handle_error=False)
        try:
            next(b for b in context.find(v.Btn).widgets if "Add parameter" in b.children).fire_event("click", {})
            table = next(w for w in widgets(root) if getattr(w, "tag", None) == "table")
            rows = [w for w in widgets(table) if getattr(w, "tag", None) == "tr"][1:]
            self.assertEqual(len(rows), 3)
            for row in rows:
                cells = [w for w in row.children if getattr(w, "tag", None) == "td"]
                self.assertEqual(len(cells), 6)
                self.assertTrue(all("vertical-align: middle" in cell.style_ for cell in cells))
                self.assertIn("white-space: nowrap", cells[-1].style_)
                controls = [w for w in widgets(row) if isinstance(w, (v.TextField, v.Select))]
                self.assertTrue(all(w.hide_details is True for w in controls))
                if IPYVUETIFY_V3:
                    self.assertTrue(all(w.density == "compact" for w in controls))
                else:
                    self.assertTrue(all(w.dense is True for w in controls))
            select = next(w for w in context.find(v.Select).widgets if w.label.startswith("type for new parameter"))
            select.v_model = "categorical"
            choices = next(w for w in context.find(v.TextField).widgets if w.label.startswith("choices for new parameter"))
            lower = next(w for w in context.find(v.TextField).widgets if w.label.startswith("lower for new parameter"))
            self.assertFalse(choices.disabled)
            self.assertTrue(lower.disabled)
        finally:
            context.close()

    def test_configuration_tables_have_keyboard_accessible_horizontal_scroll(self):
        root, context = solara.render(ParameterConfiguration(self.state, self.services.configuration), handle_error=False)
        try:
            regions = [w for w in widgets(root) if getattr(w, "attributes", {}).get("role") == "region"]
            self.assertEqual({w.attributes["aria-label"] for w in regions}, {"Parameter table", "Objective table", "Constraint table"})
            for region in regions:
                self.assertIn("overflow-x: auto", region.style_)
                self.assertIn("max-width: 100%", region.style_)
                self.assertEqual(region.attributes["tabindex"], "0")
                table = next(w for w in widgets(region) if getattr(w, "tag", None) == "table")
                self.assertIn("min-width:", table.style_)
        finally:
            context.close()

    def test_partial_objectives_are_sent_to_ax_without_imputation(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["objectives"].append({"name": "cost", "direction": "minimize"})
        project["runs"].append({"id": 2, "parameters": {"x": 4}, "results": {"cost": 8}})
        client = Mock()
        client.get_next_trials.return_value = {2: {"x": 6}}
        client.predict.return_value = [{"score": (2, 0.5), "cost": (8, 1.2)}]
        candidates = AxOptimizer(client_factory=lambda: client).generate(project, 1)
        self.assertEqual(candidates[0]["predictions"], {
            "score": {"mean": 2, "sigma": 0.5}, "cost": {"mean": 8, "sigma": 1.2},
        })
        client.configure_optimization.assert_called_once_with(objective="score, -cost")
        client.configure_generation_strategy.assert_called_once_with(
            initialize_with_center=False, allow_exceeding_initialization_budget=True,
        )
        self.assertEqual(
            [call.kwargs["raw_data"] for call in client.complete_trial.call_args_list],
            [{"score": 3.0}, {"cost": 8}],
        )

    def test_generation_with_unobserved_new_objective_after_initial_budget(self):
        project = self.state["project"].value
        project["runs"] = [
            {"id": i, "parameters": {"x": i}, "objective": i}
            for i in range(1, 7)
        ]
        upgrade_project(project)
        project["objectives"].append({"name": "cost", "direction": "minimize"})
        self.assertEqual(len(self.services.optimizer.generate(project, 1)), 1)

    def test_multi_objective_rows_and_partial_results(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["objectives"].append({"name": "cost", "direction": "minimize"})
        root, context = solara.render(RunsView(self.state, self.services), handle_error=False)
        try:
            labels = [field.label for field in context.find(v.TextField).widgets]
            self.assertIn("score", labels)
            self.assertIn("cost", labels)
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and w.children and row_label(w) == "Batch 1, recommendation 1")
            field = next(w for w in widgets(row) if isinstance(w, v.TextField) and w.label == "cost")
            field.v_model = "4"
            next(b for b in widgets(row) if isinstance(b, v.Btn) and "Save" in b.children).fire_event("click", {})
            self.assertEqual(self.state["project"].value["runs"][0]["results"], {"score": 3, "cost": 4})
        finally:
            context.close()

    def test_partial_new_recommendation_result_is_preserved(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["objectives"].append({"name": "cost", "direction": "minimize"})
        project["recommendation_batches"][0]["candidates"].append({"parameters": {"x": 4}})
        self.services.runs.save(
            project, {"score": "", "cost": "6"}, batch_index=0, candidate_index=1,
            parameters={"x": "4"},
        )
        self.assertEqual(project["runs"][-1]["results"], {"cost": 6})
        self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)

    def test_rename_parameter_updates_constraints_and_existing_measurements(self):
        self.state["project"].value["parameter_constraints"] = ["x <= 8"]
        self.state["project"].value["recommendation_batches"][0]["candidates"][0]["predictions"] = {"score": {"mean": 3, "sigma": 0.4}}
        root, context = solara.render(ParameterConfiguration(self.state, self.services.configuration), handle_error=False)
        try:
            name = next(w for w in context.find(v.TextField).widgets if w.label == "name for parameter 1")
            name.v_model = "temperature"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and name in list(widgets(w)))
            next(b for b in widgets(row) if isinstance(b, v.Btn) and "Save" in b.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["parameter_constraints"], ["temperature <= 8"])
            self.assertEqual(project["runs"][0]["parameters"], {"temperature": 2})
            self.assertEqual(project["recommendation_batches"][0]["candidates"][0]["parameters"], {"temperature": 2})
            self.assertIn("predictions", project["recommendation_batches"][0]["candidates"][0])
        finally:
            context.close()

    def test_partial_saved_row_and_legacy_load(self):
        legacy = self.state["project"].value
        self.assertEqual(self.services.files.load_json(json.dumps(legacy).encode()), legacy)
        upgrade_project(legacy)
        legacy["objectives"].append({"name": "cost", "direction": "minimize"})
        self.services.runs.save(legacy, {"score": "5", "cost": ""}, run_id=1, parameters={"x": "3"})
        self.assertEqual(legacy["runs"][0]["results"], {"score": 5})
        self.assertEqual(self.services.files.load_json(json.dumps(legacy).encode()), legacy)

    def test_multi_objective_parameter_edit_invalidates_predictions(self):
        project = self.state["project"].value
        upgrade_project(project)
        candidate = project["recommendation_batches"][0]["candidates"][0]
        candidate["predictions"] = {"score": {"mean": 3, "sigma": 0.4}}
        self.services.runs.save(project, {"score": "4"}, batch_index=0, candidate_index=0, parameters={"x": "3"})
        self.assertNotIn("predictions", candidate)
        self.assertEqual(candidate["prediction_status"], "parameters_changed")
        self.assertEqual(project["runs"][0]["parameters"], {"x": 3})

    def test_multi_objective_csv_retains_partial_results(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["objectives"].append({"name": "cost", "direction": "minimize"})
        self.assertEqual(
            self.services.files.parse_csv(project, b"x,score,cost\n1,4,\n2,,5\n"),
            [{"x": 1.0, "score": 4.0}, {"x": 2.0, "cost": 5.0}],
        )
        with self.assertRaisesRegex(ValueError, "CSV row 2"):
            self.services.files.parse_csv(project, b"x,score,cost\n1,,\n")

    def test_rename_objective_and_delete_parameter_retain_values(self):
        candidate = self.state["project"].value["recommendation_batches"][0]["candidates"][0]
        candidate["predictions"] = {"score": {"mean": 3, "sigma": 0.4}}
        root, context = solara.render(ParameterConfiguration(self.state, self.services.configuration), handle_error=False)
        try:
            name = next(w for w in context.find(v.TextField).widgets if w.label == "name for objective 1")
            name.v_model = "quality"
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and name in list(widgets(w)))
            next(b for b in widgets(row) if isinstance(b, v.Btn) and "Save" in b.children).fire_event("click", {})
            self.assertEqual(self.state["project"].value["runs"][0]["results"], {"quality": 3})
            candidate = self.state["project"].value["recommendation_batches"][0]["candidates"][0]
            self.assertEqual(candidate["predictions"], {"quality": {"mean": 3, "sigma": 0.4}})

            name = next(w for w in context.find(v.TextField).widgets if w.label == "name for parameter 1")
            row = next(w for w in widgets(root) if getattr(w, "tag", None) == "tr" and name in list(widgets(w)))
            next(b for b in widgets(row) if isinstance(b, v.Btn) and "Delete" in b.children).fire_event("click", {})
            project = self.state["project"].value
            self.assertEqual(project["parameters"], [])
            self.assertEqual(project["runs"][0]["parameters"], {"x": 2})
            candidate = project["recommendation_batches"][0]["candidates"][0]
            self.assertNotIn("predictions", candidate)
            self.assertEqual(candidate["prediction_status"], "configuration_changed")
            self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
        finally:
            context.close()

    def test_bad_schema_and_invalid_persisted_numbers_are_rejected(self):
        project = self.state["project"].value
        upgrade_project(project)
        project["runs"][0]["results"]["score"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            self.services.files.load_json(json.dumps(project).encode())
        project["runs"][0]["results"]["score"] = 3
        project["runs"][0]["parameters"]["x"] = {"not": "a value"}
        with self.assertRaisesRegex(ValueError, "parameter values"):
            self.services.files.load_json(json.dumps(project).encode())


if __name__ == "__main__":
    unittest.main()
