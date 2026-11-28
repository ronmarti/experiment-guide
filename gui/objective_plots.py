from html import escape
from typing import Any

import plotly.graph_objects as go

from experiment.model.project import objectives_for, results_for


class ObjectivePlots:
    """Build progress and pairwise trade-off plots from saved objective measurements."""

    def progress(self, project: dict[str, Any]) -> go.Figure:
        """Plot all objectives' running best values together in their original units."""
        details = self._run_details(project)
        figure = go.Figure()
        for objective in objectives_for(project):
            figure.add_trace(self._progress_trace(project, objective, details))
        figure.update_layout(
            template="plotly_white", title="Best-so-far objective progress",
            xaxis_title="Run step", yaxis_title="Best objective value", height=420,
            margin={"l": 65, "r": 25, "t": 65, "b": 85}, autosize=True,
            legend={"orientation": "h", "y": -0.2},
        )
        figure.update_xaxes(tickmode="linear", dtick=1)
        if not any(len(trace.y) for trace in figure.data):
            figure.add_annotation(x=0.5, y=0.5, xref="paper", yref="paper",
                                  text="No saved observations", showarrow=False)
        return figure

    def _progress_trace(
        self, project: dict[str, Any], objective: dict[str, str], details: list[str],
    ) -> go.Scatter:
        """Carry the best value and its originating run details across subsequent steps."""
        name = objective["name"]
        steps, values, run_labels = [], [], []
        best = None
        best_details = ""
        for step, run in enumerate(project["runs"], 1):
            results = results_for(project, run)
            improves = name in results and (
                best is None or (
                    results[name] > best if objective["direction"] == "maximize" else results[name] < best
                )
            )
            if improves:
                best = results[name]
                best_details = details[step - 1]
            if best is not None:
                steps.append(step)
                values.append(best)
                run_labels.append(best_details)
        return go.Scatter(
            x=steps, y=values, mode="lines+markers", line={"shape": "hv"},
            customdata=run_labels, name=f"{name} ({objective['direction']})",
            hovertemplate="Step %{x}<br>" + escape(name) + " best so far: %{y}<br>"
            "Best observed run:<br>%{customdata}<extra></extra>",
        )

    def pair(
        self, project: dict[str, Any], first: dict[str, str], second: dict[str, str],
    ) -> go.Figure:
        """Plot joint observations, their pairwise frontier, and the preferred direction."""
        x_name, y_name = first["name"], second["name"]
        points, run_labels = [], []
        details = self._run_details(project)
        details_by_point: dict[tuple[float, float], list[str]] = {}
        for step, run in enumerate(project["runs"], 1):
            results = results_for(project, run)
            if x_name not in results or y_name not in results:
                continue
            point = (results[x_name], results[y_name])
            points.append(point)
            run_labels.append(details[step - 1])
            details_by_point.setdefault(point, []).append(details[step - 1])
        figure = go.Figure(go.Scatter(
            x=[point[0] for point in points], y=[point[1] for point in points],
            mode="markers", name="Observed runs", customdata=run_labels,
            marker={"size": 9},
            hovertemplate="%{customdata}<br>" + x_name + ": %{x}<br>" + y_name + ": %{y}<extra></extra>",
        ))
        frontier = self._pareto_frontier(points, first["direction"], second["direction"])
        if frontier:
            figure.add_trace(go.Scatter(
                x=[point[0] for point in frontier], y=[point[1] for point in frontier],
                mode="lines+markers", line={"color": "#c62828", "dash": "dash"},
                name="Pairwise Pareto frontier",
                customdata=["<br><br>".join(details_by_point[point]) for point in frontier],
                hovertemplate="%{customdata}<br>" + x_name + ": %{x}<br>" + y_name
                + ": %{y}<extra>Pairwise Pareto frontier</extra>",
            ))
        figure.update_layout(
            template="plotly_white", title=f"{x_name} vs {y_name}",
            xaxis_title=f"{x_name} ({first['direction']})",
            yaxis_title=f"{y_name} ({second['direction']})",
            height=450, margin={"l": 65, "r": 25, "t": 65, "b": 85}, autosize=True,
            legend={"orientation": "h", "y": -0.2},
        )
        if not points:
            figure.add_annotation(x=0.5, y=0.5, xref="paper", yref="paper",
                                  text="No jointly observed runs", showarrow=False)
        x_maximize = first["direction"] == "maximize"
        y_maximize = second["direction"] == "maximize"
        # Axes coordinates keep the direction cue independent of data ranges and outliers.
        figure.add_shape(
            type="rect", xref="paper", yref="paper",
            x0=0.72 if x_maximize else 0, x1=1 if x_maximize else 0.28,
            y0=0.72 if y_maximize else 0, y1=1 if y_maximize else 0.28,
            fillcolor="#2e7d32", opacity=0.12, line_width=0, layer="below",
        )
        figure.add_annotation(
            text="Better", xref="paper", yref="paper",
            x=0.96 if x_maximize else 0.04, y=0.96 if y_maximize else 0.04,
            ax=-60 if x_maximize else 60, ay=60 if y_maximize else -60,
            font={"color": "#1b5e20"}, arrowcolor="#1b5e20", arrowwidth=2, arrowhead=2,
        )
        return figure

    def _run_details(self, project: dict[str, Any]) -> list[str]:
        """Build hover text matching visible row notes, including linked recommendation rows."""
        labels = {}
        for batch_index, batch in enumerate(project.get("recommendation_batches", []), 1):
            for candidate_index, candidate in enumerate(batch["candidates"], 1):
                if "run_id" in candidate:
                    labels[candidate["run_id"]] = candidate.get(
                        "notes", f"Batch {batch_index}, recommendation {candidate_index}",
                    )
        details = []
        for step, run in enumerate(project["runs"], 1):
            label = labels.get(run.get("id"), run.get("notes", f"Run {run.get('id', step)}"))
            parameters = "<br>".join(
                f"{escape(name)}: {escape(str(value))}" for name, value in run.get("parameters", {}).items()
            )
            details.append(f"Run and notes: {escape(label)}<br>Parameters:<br>{parameters}")
        return details

    def _pareto_frontier(
        self, points: list[tuple[float, float]], x_direction: str, y_direction: str,
    ) -> list[tuple[float, float]]:
        """Return unique nondominated points, sorted by ascending plotted x coordinate."""
        x_sign = 1 if x_direction == "maximize" else -1
        y_sign = 1 if y_direction == "maximize" else -1
        # Best x first, then best y for equal x: only strict y improvements survive.
        ordered = sorted(set(points), key=lambda point: (-x_sign * point[0], -y_sign * point[1]))
        frontier = []
        best_y = None
        for point in ordered:
            y = y_sign * point[1]
            if best_y is not None and y <= best_y:
                continue
            frontier.append(point)
            best_y = y
        return sorted(frontier)
