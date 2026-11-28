import unittest
from unittest.mock import patch

import solara

from experiment.model.project import blank_project
from gui.objective_plots import ObjectivePlots
from gui.objective_visualization import ObjectiveVisualization


class ObjectiveVisualizationTests(unittest.TestCase):
    def setUp(self):
        self.plots = ObjectivePlots()
        self.project = {
            "objectives": [
                {"name": "score", "direction": "maximize"},
                {"name": "cost", "direction": "minimize"},
                {"name": "unmeasured", "direction": "maximize"},
            ],
            "runs": [
                {"results": {}},
                {"results": {"score": -3, "cost": 8}},
                {"results": {"score": -5}},
                {"results": {"score": -1, "cost": 10}},
                {"results": {"cost": 4}},
                {"results": {}},
            ],
            "recommendation_batches": [
                {"candidates": [{"predictions": {"score": {"mean": 100, "sigma": 1}}}]},
            ],
        }

    def test_running_best_respects_direction_and_missing_results(self):
        score, cost, _ = self.project["objectives"]
        score_line = self.plots.progress(self.project, score).axes[0].lines[0]
        cost_line = self.plots.progress(self.project, cost).axes[0].lines[0]
        self.assertEqual(list(score_line.get_xdata()), [2, 3, 4, 5, 6])
        self.assertEqual(list(score_line.get_ydata()), [-3, -3, -1, -1, -1])
        self.assertEqual(list(cost_line.get_ydata()), [8, 8, 8, 4, 4])

    def test_pair_uses_only_joint_observations(self):
        score, cost, _ = self.project["objectives"]
        axis = self.plots.pair(self.project, score, cost).axes[0]
        self.assertEqual(axis.collections[0].get_offsets().tolist(), [[-3, 8], [-1, 10]])
        self.assertEqual(axis.get_xlabel(), "score (maximize)")
        self.assertEqual(axis.get_ylabel(), "cost (minimize)")

    def test_legacy_progress_and_empty_plots(self):
        project = blank_project()
        project["objective"] = {"name": "score", "direction": "maximize"}
        project["runs"] = [{"objective": 2}, {"objective": 1}, {"objective": 4}]
        line = self.plots.progress(project, project["objective"]).axes[0].lines[0]
        self.assertEqual(list(line.get_ydata()), [2, 2, 4])
        score, _, unmeasured = self.project["objectives"]
        axis = self.plots.progress(self.project, unmeasured).axes[0]
        self.assertEqual(len(axis.lines[0].get_ydata()), 0)
        self.assertEqual(axis.texts[0].get_text(), "No saved observations")
        axis = self.plots.pair(self.project, score, unmeasured).axes[0]
        self.assertEqual(len(axis.collections[0].get_offsets()), 0)
        self.assertEqual(axis.texts[0].get_text(), "No jointly observed runs")

    def test_visualization_renders_all_pairs_and_updates_progress(self):
        figures = []

        @solara.component
        def figure_plot(figure):
            figures.append(figure)

        project = solara.reactive(self.project)

        @solara.component
        def view():
            ObjectiveVisualization(project.value, self.plots)

        with patch("solara.FigureMatplotlib", figure_plot):
            _, context = solara.render(view(), handle_error=False)
            try:
                self.assertEqual(len(figures), 6)
                self.assertEqual(
                    [figure.axes[0].get_title() for figure in figures[3:]],
                    ["score vs cost", "score vs unmeasured", "cost vs unmeasured"],
                )
                figures.clear()
                project.value = {**self.project, "runs": [*self.project["runs"], {"results": {"score": 7}}]}
                self.assertEqual(list(figures[0].axes[0].lines[0].get_ydata())[-1], 7)
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
