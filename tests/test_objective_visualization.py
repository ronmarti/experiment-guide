import unittest
from unittest.mock import patch

import solara

from experiment.model.project import blank_project
from gui.objective_plots import ObjectivePlots
from gui.objective_visualization import ObjectiveVisualization
from gui.plotly_chart import PlotlyChart
from test_results_table import widgets


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
        score_line = self.plots.progress(self.project, score).data[0]
        cost_line = self.plots.progress(self.project, cost).data[0]
        self.assertEqual(list(score_line.x), [2, 3, 4, 5, 6])
        self.assertEqual(list(score_line.y), [-3, -3, -1, -1, -1])
        self.assertEqual(list(cost_line.y), [8, 8, 8, 4, 4])
        self.assertEqual(score_line.line.shape, "hv")

    def test_pair_uses_only_joint_observations(self):
        score, cost, _ = self.project["objectives"]
        figure = self.plots.pair(self.project, score, cost)
        self.assertEqual(list(zip(figure.data[0].x, figure.data[0].y)), [(-3, 8), (-1, 10)])
        self.assertEqual(figure.layout.xaxis.title.text, "score (maximize)")
        self.assertEqual(figure.layout.yaxis.title.text, "cost (minimize)")

    def test_pair_desirable_corner_matches_each_direction_combination(self):
        for x_direction in ("maximize", "minimize"):
            for y_direction in ("maximize", "minimize"):
                with self.subTest(x=x_direction, y=y_direction):
                    first = {"name": "score", "direction": x_direction}
                    second = {"name": "cost", "direction": y_direction}
                    figure = self.plots.pair(self.project, first, second)
                    highlight = figure.layout.shapes[0]
                    self.assertEqual(
                        (highlight.x0, highlight.y0),
                        (0.72 if x_direction == "maximize" else 0,
                         0.72 if y_direction == "maximize" else 0),
                    )
                    cue = next(text for text in figure.layout.annotations if text.text == "Better")
                    self.assertEqual(
                        (cue.x, cue.y),
                        (0.96 if x_direction == "maximize" else 0.04,
                         0.96 if y_direction == "maximize" else 0.04),
                    )
                    self.assertEqual((cue.xref, cue.yref), ("paper", "paper"))
                    self.assertEqual(list(zip(figure.data[0].x, figure.data[0].y)), [(-3, 8), (-1, 10)])

    def test_pair_frontier_handles_directions_duplicates_and_ties(self):
        frontier = [(1, 5), (2, 3), (4, 1)]
        points = [*frontier, (2, 5), (3, 4), (4, 2), (1, 6), (5, 1), (2, 3)]
        for x_direction in ("maximize", "minimize"):
            for y_direction in ("maximize", "minimize"):
                with self.subTest(x=x_direction, y=y_direction):
                    x_sign = -1 if x_direction == "maximize" else 1
                    y_sign = -1 if y_direction == "maximize" else 1
                    project = {
                        **self.project,
                        "runs": [{"results": {"score": x_sign * x, "cost": y_sign * y}} for x, y in reversed(points)],
                    }
                    figure = self.plots.pair(
                        project, {"name": "score", "direction": x_direction},
                        {"name": "cost", "direction": y_direction},
                    )
                    line = figure.data[1]
                    self.assertEqual(
                        list(zip(line.x, line.y)),
                        sorted((x_sign * x, y_sign * y) for x, y in frontier),
                    )
                    self.assertEqual(len(figure.data[0].x), len(points))

    def test_single_frontier_point_and_empty_pair(self):
        score, cost, unmeasured = self.project["objectives"]
        project = {**self.project, "runs": [
            {"results": {"score": 5, "cost": 1}},
            {"results": {"score": 5, "cost": 1}},
            {"results": {"score": 2, "cost": 3}},
        ]}
        figure = self.plots.pair(project, score, cost)
        self.assertEqual(list(zip(figure.data[1].x, figure.data[1].y)), [(5, 1)])
        self.assertEqual(len(self.plots.pair(project, score, unmeasured).data), 1)

    def test_legacy_progress_and_empty_plots(self):
        project = blank_project()
        project["objective"] = {"name": "score", "direction": "maximize"}
        project["runs"] = [{"objective": 2}, {"objective": 1}, {"objective": 4}]
        line = self.plots.progress(project, project["objective"]).data[0]
        self.assertEqual(list(line.y), [2, 2, 4])
        score, _, unmeasured = self.project["objectives"]
        figure = self.plots.progress(self.project, unmeasured)
        self.assertEqual(len(figure.data[0].y), 0)
        self.assertEqual(figure.layout.annotations[0].text, "No saved observations")
        figure = self.plots.pair(self.project, score, unmeasured)
        self.assertEqual(len(figure.data[0].x), 0)
        self.assertEqual(figure.layout.annotations[0].text, "No jointly observed runs")

    def test_visualization_renders_all_pairs_and_updates_progress(self):
        figures = []

        @solara.component
        def figure_plot(figure):
            figures.append(figure)

        project = solara.reactive(self.project)

        @solara.component
        def view():
            ObjectiveVisualization(project.value, self.plots)

        with patch("gui.objective_visualization.PlotlyChart", figure_plot):
            _, context = solara.render(view(), handle_error=False)
            try:
                self.assertEqual(len(figures), 6)
                self.assertEqual(
                    [figure.layout.title.text for figure in figures[3:]],
                    ["score vs cost", "score vs unmeasured", "cost vs unmeasured"],
                )
                figures.clear()
                project.value = {**self.project, "runs": [*self.project["runs"], {"results": {"score": 7}}]}
                self.assertEqual(list(figures[0].data[0].y)[-1], 7)
            finally:
                context.close()

    def test_interactive_chart_embeds_local_plotly_and_run_hover_details(self):
        self.project["runs"][1]["notes"] = "Control"
        score, cost, _ = self.project["objectives"]
        figure = self.plots.pair(self.project, score, cost)
        self.assertEqual(figure.data[0].customdata[0], "Control")
        root, context = solara.render(PlotlyChart(figure), handle_error=False)
        try:
            frame = next(w for w in widgets(root) if getattr(w, "tag", None) == "iframe")
            html = frame.attributes["srcdoc"]
            self.assertIn("Plotly.newPlot", html)
            self.assertNotIn('<script src="https://cdn.plot.ly', html)
            self.assertIn('"scrollZoom": true', html)
            self.assertEqual(frame.attributes["title"], "score vs cost")
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
