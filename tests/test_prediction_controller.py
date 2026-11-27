import threading
import unittest
from unittest.mock import Mock

from experiment.services.optimization import AxOptimizer
from experiment.services.prediction import PredictionController


class PredictionControllerTests(unittest.TestCase):
    def setUp(self):
        self.optimizer = Mock(spec=AxOptimizer)
        self.controller = PredictionController(self.optimizer, new_id=lambda: "request-id")
        self.project = {
            "name": "Test", "runs": [],
            "recommendation_batches": [{"candidates": [{"parameters": {"x": 2}}]}],
        }

    def test_snapshot_retry_and_apply(self):
        request = self.controller.request(self.project, {"x": 2}, True)
        self.project["runs"].append({"id": 1})
        self.assertEqual(request["project"]["runs"], [])
        self.assertTrue(self.controller.needs_retry(self.project, request))
        self.optimizer.predict.return_value = {"score": {"mean": 3, "sigma": 0.5}}
        result = self.controller.calculate(request, threading.Event())
        updated = self.controller.apply(self.project, request, result, 0, 0)
        self.assertEqual(updated["recommendation_batches"][0]["candidates"][0]["predictions"], result["predictions"])
        self.assertNotIn("predictions", self.project["recommendation_batches"][0]["candidates"][0])
        self.assertIsNone(self.controller.apply(self.project, request, {**result, "id": "stale"}, 0, 0))
        self.project["recommendation_batches"][0]["candidates"][0]["parameters"]["x"] = 4
        self.assertIsNone(self.controller.apply(self.project, request, result, 0, 0))

    def test_cancelled_preview_and_reported_error(self):
        request = self.controller.request(self.project, {"x": 2}, False)
        cancel = threading.Event()
        cancel.set()
        self.assertIsNone(self.controller.calculate(request, cancel))
        self.optimizer.predict.assert_not_called()
        request["persist"] = True
        self.optimizer.predict.side_effect = RuntimeError("model failed")
        result = self.controller.calculate(request, cancel)
        self.assertEqual(result["error"], "model failed")
        with self.assertRaisesRegex(ValueError, "model failed"):
            self.controller.apply(self.project, request, result, 0, 0)
