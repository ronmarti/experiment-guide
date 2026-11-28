import solara


@solara.component
def AppDescription():
    solara.Markdown(
        "This app tries to bring simple general UI for automated parameters recommendations for running sequential experiments. "
        "If you have a problem of setting up many parameters while having measurable outcome you need to maximize (or minimize), this app will guide you sequentially through the parameter space search. "
        "It utilizes modern Explore-Exploit strategy while aiming for finding optimum with informed confidence estimate using mix of Bayesian Optimization built on stack of Ax>BOTorch>PyTorch."
    )
    solara.Markdown("## Getting Started")
    solara.Markdown(
        "Configure your experiment by parameters you can set before running an experiment, and objective that will be a measurable outcome of the experiment. "
        "If you have multiple objectives and don't know yet how to prioritize them, you can set up multiple objective and the app will aim for exploring the Pareto-frontier, a surface on which your final optimal parameter combination lies."
    )
