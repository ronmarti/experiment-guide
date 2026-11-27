import json
import unittest
from unittest.mock import patch

from experiment.model.project import blank_project
from gui.services import AppServices


class ProjectDataTests(unittest.TestCase):
    def setUp(self):
        self.services = AppServices()
        self.project = blank_project("Test")
        self.project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 10]}]
        self.project["objective"] = {"name": "score", "direction": "maximize"}
        self.project["runs"] = [{"id": 1, "parameters": {"x": 1}, "objective": 2}]
        self.project["recommendation_batches"] = [{
            "id": "batch", "candidates": [{"parameters": {"x": 3}}, {"parameters": {"x": 3}}],
        }]


    def test_legacy_draft_keeps_its_order_when_saved(self):
        project = self.project
        project["draft_runs"] = [{"id": "draft", "parameters": {"x": 8}, "table_order": 5}]
        self.services.runs.save(project, "9", draft_id="draft")
        self.assertEqual(project["runs"][-1]["table_order"], 5)
        self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)

    def test_import_rejects_invalid_or_duplicate_table_orders(self):
        project = self.project
        candidate = project["recommendation_batches"][0]["candidates"][0]
        for value in (True, -1, "1"):
            candidate["table_order"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Table row order"):
                self.services.files.load_json(json.dumps(project).encode())
        candidate["table_order"] = 1
        project["runs"][0]["table_order"] = 1
        with self.assertRaisesRegex(ValueError, "orders must be unique"):
            self.services.files.load_json(json.dumps(project).encode())

    def test_prediction_round_trip_and_parameter_edits(self):
        project = self.project
        candidate = project["recommendation_batches"][0]["candidates"][0]
        candidate["predictions"] = {"score": {"mean": 2, "sigma": 0.5}}
        self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)
        self.services.runs.save(project, "4", batch_index=0, candidate_index=0, parameters={"x": "3"})
        self.assertIn("predictions", candidate)
        self.services.runs.save(project, "5", run_id=candidate["run_id"], parameters={"x": "4"})
        self.assertNotIn("predictions", candidate)
        self.assertEqual(candidate["prediction_status"], "parameters_changed")
        self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)

    def test_import_rejects_invalid_predictions(self):
        project = self.project
        candidate = project["recommendation_batches"][0]["candidates"][0]
        for predictions in ([], {"score": {"mean": 1, "sigma": -1}}, {"score": {"mean": float("inf"), "sigma": 1}}, {"score": {"mean": True, "sigma": 1}}, {"score": {"mean": 1}}):
            candidate["predictions"] = predictions
            with self.subTest(predictions=predictions), self.assertRaisesRegex(ValueError, "predictions"):
                self.services.files.load_json(json.dumps(project).encode())

    def test_import_rejects_invalid_candidate_links(self):
        project = self.project
        project["recommendation_batches"][0]["candidates"][0]["run_id"] = 99
        with self.assertRaisesRegex(ValueError, "invalid linked run"):
            self.services.files.load_json(json.dumps(project).encode())

    def test_repeated_recommendations_have_independent_results(self):
        project = self.project
        self.services.runs.save(project, "3", batch_index=0, candidate_index=0)
        self.services.runs.save(project, "4", batch_index=0, candidate_index=1)
        candidates = project["recommendation_batches"][0]["candidates"]
        self.assertNotEqual(candidates[0]["run_id"], candidates[1]["run_id"])
        self.assertEqual([run["objective"] for run in project["runs"]], [2, 3, 4])
        self.assertEqual(self.services.files.load_json(json.dumps(project).encode()), project)

    def test_invalid_parameter_types_and_constraints_do_not_change_rows(self):
        project = self.project
        project["parameters"] += [
            {"name": "count", "type": "integer", "bounds": [1, 5]},
            {"name": "color", "type": "categorical", "choices": ["red", "blue"]},
        ]
        project["parameter_constraints"] = ["x + count <= 8"]
        draft = {"id": "draft", "parameters": {}}
        project["draft_runs"] = [draft]
        for parameters in (
            {"x": "3", "count": "1.5", "color": "red"},
            {"x": "3", "count": "2", "color": "green"},
            {"x": "7", "count": "2", "color": "red"},
        ):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                self.services.runs.save(project, "1", draft_id="draft", parameters=parameters)
            self.assertEqual(draft["parameters"], {})
            self.assertEqual(len(project["runs"]), 1)
        self.services.runs.save(project, "1", draft_id="draft", parameters={"x": "3", "count": "2", "color": "red"})
        self.assertEqual(project["runs"][-1]["parameters"], {"x": 3.0, "count": 2, "color": "red"})

    def test_project_constraints_reject_executable_expressions_before_ax(self):
        project = self.project
        project["parameter_constraints"] = ["__import__('os').system('anything') <= 0"]
        with patch("experiment.services.constraints.ParameterConstraint") as constraint:
            with self.assertRaisesRegex(ValueError, "Invalid parameter constraint"):
                self.services.files.load_json(json.dumps(project).encode())
            constraint.assert_not_called()
