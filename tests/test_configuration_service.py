import unittest
from copy import deepcopy

from experiment.model.project import blank_project
from experiment.services.configuration import ConfigurationService
from experiment.services.validation import ProjectValidator


class ConfigurationServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ConfigurationService(ProjectValidator())
        self.project = blank_project("Test")
        self.project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 10]}]
        self.project["objective"] = {"name": "score", "direction": "maximize"}
        self.project["parameter_constraints"] = ["x <= 8"]
        self.project["runs"] = [{"id": 1, "parameters": {"x": 2}, "objective": 3}]
        self.project["recommendation_batches"] = [{
            "candidates": [{"parameters": {"x": 2}, "run_id": 1, "predictions": {"score": {"mean": 3, "sigma": 1}}}],
        }]

    def test_rename_keeps_measurements_constraints_and_predictions(self):
        original = deepcopy(self.project)
        updated = self.service.save(self.project, "parameter", 0, {
            "name": "temperature", "type": "continuous", "lower": "0", "upper": "10", "choices": "",
        })
        self.assertEqual(self.project, original)
        self.assertEqual(updated["runs"][0]["parameters"], {"temperature": 2})
        candidate = updated["recommendation_batches"][0]["candidates"][0]
        self.assertEqual(candidate["parameters"], {"temperature": 2})
        self.assertIn("predictions", candidate)
        self.assertEqual(updated["parameter_constraints"], ["temperature <= 8"])

    def test_invalid_changes_leave_original_project_untouched(self):
        original = deepcopy(self.project)
        with self.assertRaises(ValueError):
            self.service.save(self.project, "parameter", 0, {
                "name": "x", "type": "continuous", "lower": "10", "upper": "0", "choices": "",
            })
        self.assertEqual(self.project, original)

    def test_deleting_objective_retains_results_but_removes_its_predictions(self):
        updated = self.service.delete(self.project, "objective", 0)
        self.assertEqual(updated["runs"][0]["results"], {"score": 3})
        self.assertEqual(updated["recommendation_batches"][0]["candidates"][0]["predictions"], {})
        self.assertEqual(self.project["runs"][0]["objective"], 3)

    def test_manual_predictions_follow_configuration_changes(self):
        prediction = {"score": {"mean": 3, "sigma": 1}}
        self.project["runs"][0]["predictions"] = deepcopy(prediction)
        self.project["draft_runs"] = [{"id": "draft", "parameters": {"x": 4}, "predictions": deepcopy(prediction)}]
        renamed = self.service.save(self.project, "objective", 0, {"name": "quality", "direction": "maximize"})
        self.assertIn("quality", renamed["runs"][0]["predictions"])
        self.assertIn("quality", renamed["draft_runs"][0]["predictions"])
        invalidated = self.service.save(renamed, "parameter", 0, {
            "name": "x", "type": "continuous", "lower": "0", "upper": "9", "choices": "",
        })
        for row in (invalidated["runs"][0], invalidated["draft_runs"][0]):
            self.assertNotIn("predictions", row)
            self.assertEqual(row["prediction_status"], "configuration_changed")
        deleted = self.service.delete(renamed, "objective", 0)
        self.assertEqual(deleted["runs"][0]["predictions"], {})
        self.assertEqual(deleted["draft_runs"][0]["predictions"], {})


if __name__ == "__main__":
    unittest.main()
