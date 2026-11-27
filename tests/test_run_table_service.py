import unittest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

from experiment.model.project import blank_project
from experiment.services.optimization import AxOptimizer
from experiment.services.persistence import ProjectFiles
from experiment.services.run_table import RunTableService
from experiment.services.runs import RunService
from experiment.services.validation import ProjectValidator


class RunTableServiceTests(unittest.TestCase):
    def setUp(self):
        self.project = blank_project("Test")
        self.project["parameters"] = [{"name": "x", "type": "continuous", "bounds": [0, 10]}]
        self.project["objective"] = {"name": "score", "direction": "maximize"}
        self.optimizer = Mock(spec=AxOptimizer)
        self.table = RunTableService(
            RunService(), ProjectFiles(ProjectValidator()), self.optimizer,
            new_id=lambda: "fixed-id",
            now=lambda: datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    def test_injected_generator_clock_and_id_append_after_draft(self):
        draft_project = self.table.add_draft(self.project)
        seen = []
        def generate(project, batch_size):
            seen.append((deepcopy(project), batch_size))
            return [{"parameters": {"x": 4}, "prediction_status": "model_unavailable"}]
        self.optimizer.generate.side_effect = generate
        updated, unavailable = self.table.generate(draft_project, 1)
        self.assertTrue(unavailable)
        self.assertEqual(self.project["recommendation_batches"], [])
        self.assertEqual(updated["draft_runs"][0]["table_order"], 0)
        batch = updated["recommendation_batches"][0]
        self.assertEqual((batch["id"], batch["created_at"]), ("fixed-id", "2026-01-02T00:00:00+00:00"))
        self.assertEqual(batch["candidates"][0]["table_order"], 1)
        self.assertEqual(seen, [(draft_project, 1)])

    def test_failed_import_or_generation_does_not_change_project(self):
        original = deepcopy(self.project)
        with self.assertRaisesRegex(ValueError, "CSV row 3"):
            self.table.import_csv(self.project, b"x,score\n1,2\n11,3\n")
        self.optimizer.generate.side_effect = RuntimeError("Generation failed")
        with self.assertRaisesRegex(RuntimeError, "Generation failed"):
            self.table.generate(self.project, 1)
        self.assertEqual(self.project, original)
