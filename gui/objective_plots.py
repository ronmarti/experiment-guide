from typing import Any

import plotly.graph_objects as go

from experiment.model.project import results_for


class ObjectivePlots:
    """Build progress and pairwise trade-off plots from saved objective measurements."""

    def progress(self, project: dict[str, Any], objective: dict[str, str]) -> go.Figure:
        """Plot the running best after each saved run, carrying it across missing results."""
        name = objective["name"]
        choose_best = max if objective["direction"] == "maximize" else min
        steps, values, run_labels = [], [], []
        best = None
        for step, run in enumerate(project["runs"], 1):
            results = results_for(project, run)
            if name in results:
                best = results[name] if best is None else choose_best(best, results[name])
            if best is not None:
                steps.append(step)
                values.append(best)
                run_labels.append(run.get("notes", f"Run {run.get('id', step)}"))
        figure = go.Figure(go.Scatter(
            x=steps, y=values, mode="lines+markers", line={"shape": "hv"},
            customdata=run_labels, name="Best so far",
            hovertemplate="Step %{x}<br>%{customdata}<br>Best so far: %{y}<extra></extra>",
        ))
        figure.update_layout(
            template="plotly_white", title=f"{name}: best so far ({objective['direction']})",
            xaxis_title="Run step", yaxis_title=name, height=350,
            margin={"l": 65, "r": 25, "t": 65, "b": 55}, autosize=True,
        )
        figure.update_xaxes(tickmode="linear", dtick=1)
        if not values:
            figure.add_annotation(x=0.5, y=0.5, xref="paper", yref="paper",
                                  text="No saved observations", showarrow=False)
        return figure

    def pair(
        self, project: dict[str, Any], first: dict[str, str], second: dict[str, str],
    ) -> go.Figure:
        """Plot joint observations, their pairwise frontier, and the preferred direction."""
        x_name, y_name = first["name"], second["name"]
        points, run_labels = [], []
        for step, run in enumerate(project["runs"], 1):
            results = results_for(project, run)
            if x_name not in results or y_name not in results:
                continue
            points.append((results[x_name], results[y_name]))
            run_labels.append(run.get("notes", f"Run {run.get('id', step)}"))
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
                hovertemplate=x_name + ": %{x}<br>" + y_name + ": %{y}<extra>Pairwise Pareto frontier</extra>",
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
