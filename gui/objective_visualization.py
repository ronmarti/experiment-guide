from itertools import combinations

import solara

from experiment.model.project import objectives_for
from gui.plotly_chart import PlotlyChart


@solara.component
def ObjectiveVisualization(project, plots):
    objectives = objectives_for(project)
    solara.Markdown("## Optimization progress")
    solara.Markdown("Hover for values, run notes, and parameters. Drag to zoom, use the toolbar to pan or export, and double-click to reset.")
    solara.Markdown(
        "Best saved observation for each objective after each run step. "
        "Each objective is tracked independently in its original units, these best values need not belong to the same run. "
        "Progress tooltips describe the run that achieved the best value. Click legend entries to hide or show curves."
    )
    PlotlyChart(plots.progress(project))
    if len(objectives) > 1:
        solara.Markdown("## Objective pairs")
        solara.Markdown(
            "Pairwise trade-offs between saved observations. Each point is a run with both objectives measured, "
            "predictions and missing results are excluded. The green corner and arrow show the direction "
            "that improves both objectives, not a target threshold or a guaranteed attainable region. "
            "The red dashed frontier connects observed points that are nondominated for this pair only, "
            "connecting segments do not imply attainable outcomes."
        )
        for first, second in combinations(objectives, 2):
            PlotlyChart(plots.pair(project, first, second))
