import csv
import io
import json
from typing import Any

from experiment.model.project import objectives_for
from experiment.services.validation import validate_project
from experiment.services.values import validate_run

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_PROJECT_BYTES = 10 * 1024 * 1024


def parse_csv(project: dict[str, Any], data: bytes) -> list[dict[str, Any]]:
    if len(data) > MAX_CSV_BYTES:
        raise ValueError("CSV upload exceeds the 5 MB size limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV must be UTF-8 encoded.")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    fieldnames = set(reader.fieldnames)
    required = {p["name"] for p in project["parameters"]} | {o["name"] for o in objectives_for(project)}
    missing = sorted(required - fieldnames)
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(missing))

    parsed: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        values = {name: row[name] for name in required}
        try:
            parsed.append(validate_run(project, values))
        except ValueError as exc:
            raise ValueError(f"CSV row {row_number}: {exc}") from exc
    if not parsed:
        raise ValueError("CSV contains no data rows.")
    return parsed


def load_project_json(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_PROJECT_BYTES:
        raise ValueError("Project JSON exceeds the 10 MB size limit.")
    try:
        project = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise ValueError("Project file must be UTF-8 encoded.")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid project JSON: {exc.msg}") from exc
    return validate_project(project)
