import unittest
from unittest.mock import patch

from ax.exceptions.core import UnsupportedError

from experiment.model.project import blank_project, upgrade_project
from experiment.services.optimization import generate_candidates, predict_candidate


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.project = blank_project("Test")
        self.project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 10]}]
        self.project["objective"] = {"name": "score", "direction": "maximize"}
        self.project["runs"] = [{"id": 1, "parameters": {"x": 1}, "objective": 2}]
        self.project["recommendation_batches"] = [{
            "id": "batch", "candidates": [{"parameters": {"x": 3}}, {"parameters": {"x": 3}}],
        }]


    def test_ax_receives_only_completed_runs(self):
        project = self.project
        project["recommendation_batches"][0]["candidates"][0]["run_id"] = 1
        project["recommendation_batches"][0]["candidates"][0]["parameters"] = {"x": 1}
        with patch("experiment.services.optimization.Client") as client_type:
            client = client_type.return_value
            client.get_next_trials.return_value = {10: {"x": 5}}
            client.predict.return_value = [{"score": (3.5, 0.75)}]
            self.assertEqual(generate_candidates(project, 1), [
                {"parameters": {"x": 5}, "predictions": {"score": {"mean": 3.5, "sigma": 0.75}}}
            ])
            client.predict.assert_called_once_with([{"x": 5}])
            self.assertEqual(client.attach_trial.call_count, 1)
            self.assertEqual(client.complete_trial.call_count, 1)

    def test_real_prediction_uses_available_multi_objective_observations(self):
        project = self.project
        project["runs"] = []
        self.assertIsNone(predict_candidate(project, {"x": 5}))
        upgrade_project(project)
        project["objectives"].append({"name": "cost", "direction": "minimize"})
        project["objectives"].append({"name": "unmeasured", "direction": "maximize"})
        project["runs"] = [
            {"id": 1, "parameters": {"x": 1}, "results": {"score": 1}},
            {"id": 2, "parameters": {"x": 5}, "results": {"score": 5, "cost": 9}},
            {"id": 3, "parameters": {"x": 9}, "results": {"score": 10, "cost": 2}},
        ]
        left = predict_candidate(project, {"x": 2})
        right = predict_candidate(project, {"x": 8})
        self.assertEqual(set(left), {"score", "cost"})
        self.assertNotAlmostEqual(left["score"]["mean"], right["score"]["mean"], places=2)
        self.assertGreaterEqual(left["cost"]["sigma"], 0)
        self.assertGreater(left["cost"]["mean"], 0)
        with self.assertRaisesRegex(ValueError, "between"):
            predict_candidate(project, {"x": 11})

    def test_initial_generation_and_prediction_failures(self):
        project = self.project
        project["runs"] = []
        self.assertEqual(generate_candidates(project, 1)[0]["prediction_status"], "model_unavailable")
        with patch("experiment.services.optimization.Client") as client_type:
            client = client_type.return_value
            client.get_next_trials.return_value = {0: {"x": 5}}
            client._generation_strategy.adapter.can_predict = True
            client.predict.side_effect = UnsupportedError("model error")
            with self.assertRaisesRegex(RuntimeError, "Prediction failed"):
                generate_candidates(project, 1)
            client.predict.side_effect = None
            for prediction in ([{"score": (1, -1)}], [{"score": (float("nan"), 1)}], []):
                client.predict.return_value = prediction
                with self.subTest(prediction=prediction), self.assertRaisesRegex(RuntimeError, "invalid predictions"):
                    generate_candidates(project, 1)
