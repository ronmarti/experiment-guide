from typing import Any

from matplotlib.figure import Figure

from experiment.model.project import results_for


class ObjectivePlots:
    """Build progress and pairwise trade-off plots from saved objective measurements."""

    def progress(self, project: dict[str, Any], objective: dict[str, str]) -> Figure:
        """Plot the running best after each saved run, carrying it across missing results."""
        name = objective["name"]
        choose_best = max if objective["direction"] == "maximize" else min
        steps, values = [], []
        best = None
        for step, run in enumerate(project["runs"], 1):
            results = results_for(project, run)
            if name in results:
                best = results[name] if best is None else choose_best(best, results[name])
            if best is not None:
                steps.append(step)
                values.append(best)
        figure = Figure(figsize=(7, 3))
        axis = figure.subplots()
        axis.step(steps, values, where="post", marker="o")
        axis.set_title(f"{name}: best so far ({objective['direction']})")
        axis.set_xlabel("Run step")
        axis.set_ylabel(name)
        if not values:
            axis.text(0.5, 0.5, "No saved observations", ha="center", va="center", transform=axis.transAxes)
        axis.grid(True, alpha=0.25)
        figure.tight_layout()
        return figure

    def pair(
        self, project: dict[str, Any], first: dict[str, str], second: dict[str, str],
    ) -> Figure:
        """Plot only runs with both objectives observed, without imputing missing values."""
        x_name, y_name = first["name"], second["name"]
        results = [results_for(project, run) for run in project["runs"]]
        paired = [result for result in results if x_name in result and y_name in result]
        figure = Figure(figsize=(5, 4))
        axis = figure.subplots()
        axis.scatter([result[x_name] for result in paired], [result[y_name] for result in paired])
        axis.set_title(f"{x_name} vs {y_name}")
        axis.set_xlabel(f"{x_name} ({first['direction']})")
        axis.set_ylabel(f"{y_name} ({second['direction']})")
        if not paired:
            axis.text(0.5, 0.5, "No jointly observed runs", ha="center", va="center", transform=axis.transAxes)
        axis.grid(True, alpha=0.25)
        figure.tight_layout()
        return figure
