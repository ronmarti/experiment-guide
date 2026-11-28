import reacton.ipyvuetify as v
import solara


@solara.component
def PlotlyChart(figure):
    html = solara.use_memo(
        lambda: figure.to_html(
            include_plotlyjs=True, full_html=True,
            config={"responsive": True, "displaylogo": False, "scrollZoom": True},
            default_width="100%", default_height=f"{figure.layout.height}px",
        ),
        dependencies=[figure],
    )
    v.Html(
        tag="iframe",
        attributes={
            "srcdoc": html, "title": figure.layout.title.text,
            "sandbox": "allow-scripts allow-downloads", "loading": "lazy",
        },
        style_=f"width: 100%; height: {figure.layout.height + 20}px; border: 0; display: block",
    )
