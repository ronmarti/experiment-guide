from itertools import combinations

import solara

from experiment.model.project import objectives_for


@solara.component
def ObjectiveVisualization(project, plots):
    objectives = objectives_for(project)
    solara.Markdown("## Optimization progress")
    solara.Markdown(
        "Best saved observation for each objective after each run step. "
        "Each objective is tracked independently; these best values need not belong to the same run."
    )
    for objective in objectives:
        solara.FigureMatplotlib(plots.progress(project, objective))
    if len(objectives) > 1:
        solara.Markdown("## Objective pairs")
        solara.Markdown(
            "Pairwise trade-offs between saved observations. Each point is a run with both objectives measured; "
            "predictions and missing results are excluded."
        )
        for first, second in combinations(objectives, 2):
            solara.FigureMatplotlib(plots.pair(project, first, second))
