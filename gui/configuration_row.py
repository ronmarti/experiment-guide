import reacton.ipyvuetify as v
import solara
from solara.util import IPYVUETIFY_V3


@solara.component
def ConfigurationRow(kind, item, label, on_save, on_delete):
    if kind == "parameter":
        bounds = item.get("bounds", ["", ""]) if item.get("type") not in ("categorical", "choice", "str") else ["", ""]
        initial = {
            "name": item.get("name", ""),
            "type": {"float": "continuous", "int": "integer", "choice": "categorical", "str": "categorical"}.get(item.get("type"), item.get("type", "continuous")),
            "lower": str(bounds[0]),
            "upper": str(bounds[1]),
            "choices": ", ".join(item.get("choices", [])),
        }
    elif kind == "objective":
        initial = {"name": item.get("name", ""), "direction": item.get("direction", "maximize")}
    else:
        initial = {"expression": item}
    fields = solara.use_reactive(initial)

    def update(name, value):
        fields.value = {**fields.value, name: value or ""}

    def text(name, disabled=False):
        with v.Html(tag="td", style_="padding: 0 8px; vertical-align: middle"):
            solara.InputText(
                f"{name} for {label}", value=fields.value[name],
                on_value=lambda value: update(name, value),
                continuous_update=True, dense=True, disabled=disabled, hide_details=True,
            )

    def select(name, options):
        with v.Html(tag="td", style_="padding: 0 8px; vertical-align: middle"):
            v.Select(
                label=f"{name} for {label}", items=options,
                v_model=fields.value[name], on_v_model=lambda value: update(name, value),
                hide_details=True, **({"density": "compact"} if IPYVUETIFY_V3 else {"dense": True}),
            )

    with v.Html(tag="tr"):
        if kind == "parameter":
            text("name")
            select("type", ["continuous", "integer", "categorical"])
            text("lower", disabled=fields.value["type"] == "categorical")
            text("upper", disabled=fields.value["type"] == "categorical")
            text("choices", disabled=fields.value["type"] != "categorical")
        elif kind == "objective":
            text("name")
            select("direction", ["maximize", "minimize"])
        else:
            text("expression")
        with v.Html(tag="td", style_="padding: 0 8px; vertical-align: middle; white-space: nowrap"):
            solara.Button("Save", on_click=lambda: on_save(fields.value), color="primary")
            solara.Button("Delete", on_click=on_delete, text=True)
