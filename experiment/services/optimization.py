import math
from typing import Any

from ax import Client
from ax.adapter.registry import Generators
from ax.api.configs import ChoiceParameterConfig, RangeParameterConfig
from ax.core.observation import ObservationFeatures
from ax.exceptions.core import UnsupportedError

from experiment.model.project import objectives_for, results_for
from experiment.services.constraints import validate_constraints
from experiment.services.values import is_finite_number, validate_parameters


def ax_parameter_configs(project: dict[str, Any]) -> list[Any]:
    configs: list[Any] = []
    for parameter in project["parameters"]:
        name = parameter["name"]
        if parameter["type"] in ("continuous", "float"):
            configs.append(
                RangeParameterConfig(
                    name=name,
                    bounds=(float(parameter["bounds"][0]), float(parameter["bounds"][1])),
                    parameter_type="float",
                    scaling="linear",
                )
            )
        elif parameter["type"] in ("integer", "int"):
            configs.append(
                RangeParameterConfig(
                    name=name,
                    bounds=(int(parameter["bounds"][0]), int(parameter["bounds"][1])),
                    parameter_type="int",
                )
            )
        else:
            configs.append(
                ChoiceParameterConfig(
                    name=name,
                    values=parameter["choices"],
                    parameter_type="str",
                    is_ordered=False,
                )
            )
    return configs


def configured_client(project: dict[str, Any]) -> tuple[Client, list[tuple[dict[str, Any], dict[str, float]]]]:
    if not project["parameters"]:
        raise ValueError("Add at least one parameter before generating recommendations.")
    objectives = objectives_for(project)
    if not objectives:
        raise ValueError("Define an objective before generating recommendations.")

    validate_constraints(project)
    objective_names = {objective["name"] for objective in objectives}
    observations = []
    for run in project["runs"]:
        results = {
            name: value for name, value in results_for(project, run).items()
            if name in objective_names
        }
        if results:
            try:
                parameters = validate_parameters(project, run["parameters"])
            except ValueError as exc:
                raise ValueError(f"Run {run['id']} needs valid parameter values: {exc}") from exc
            observations.append((parameters, results))
    try:
        client = Client(random_seed=None)
        client.configure_experiment(
            name=project["name"],
            parameters=ax_parameter_configs(project),
            parameter_constraints=project["parameter_constraints"] or None,
        )
        objective_expression = ", ".join(
            f"-{objective['name']}" if objective["direction"] == "minimize" else objective["name"]
            for objective in objectives
        )
        client.configure_optimization(objective=objective_expression)

        for parameters, results in observations:
            trial_index = client.attach_trial(parameters=parameters)
            client.complete_trial(
                trial_index=trial_index,
                raw_data=results,
            )
    except Exception as exc:
        raise RuntimeError("Model setup failed. Check the project and try again.") from exc
    return client, observations


def generate_candidates(project: dict[str, Any], batch_size: int) -> list[dict[str, Any]]:
    if not 1 <= batch_size <= 100:
        raise ValueError("Batch size must be between 1 and 100.")
    client, observations = configured_client(project)
    objectives = objectives_for(project)
    objective_names = {objective["name"] for objective in objectives}
    try:
        if observations:
            # Reconstruction starts at the first node; skip the already-satisfied center node.
            client.configure_generation_strategy(
                initialize_with_center=False,
                allow_exceeding_initialization_budget=any(
                    len(results) < len(objectives) for _, results in observations
                ),
            )
        generated = client.get_next_trials(max_trials=batch_size)
    except Exception as exc:
        raise RuntimeError("Candidate generation failed. Check the project and try again.") from exc
    points = [dict(parameters) for parameters in generated.values()]
    if not points:
        return []
    try:
        predictions = client.predict(points)
    except UnsupportedError as exc:
        # Ax's initialization generators have no fitted predictive adapter.
        adapter = client._generation_strategy.adapter
        if adapter is not None and adapter.can_predict:
            raise RuntimeError("Prediction failed. Check the project and try again.") from exc
        return [{"parameters": point, "prediction_status": "model_unavailable"} for point in points]
    except Exception as exc:
        raise RuntimeError("Prediction failed. Check the project and try again.") from exc
    try:
        if len(predictions) != len(points):
            raise ValueError("Prediction count does not match candidate count.")
        candidates = []
        for point, predicted in zip(points, predictions):
            if not isinstance(predicted, dict):
                raise ValueError("Invalid prediction.")
            snapshot = {}
            for name in objective_names:
                if name in predicted:
                    mean, sigma = predicted[name]
                    if isinstance(mean, bool) or isinstance(sigma, bool):
                        raise ValueError("Invalid prediction.")
                    mean, sigma = float(mean), float(sigma)
                    if not is_finite_number(mean) or not is_finite_number(sigma) or sigma < 0:
                        raise ValueError("Invalid prediction.")
                    snapshot[name] = {"mean": mean, "sigma": sigma}
            candidates.append({"parameters": point, "predictions": snapshot})
        return candidates
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        raise RuntimeError("Ax returned invalid predictions. Check the project and try again.") from exc


def predict_candidate(project: dict[str, Any], parameters: dict[str, Any]) -> dict[str, dict[str, float]] | None:
    point = validate_parameters(project, parameters)
    client, observations = configured_client(project)
    if not observations:
        return None
    try:
        experiment = client._experiment
        adapter = Generators.BOTORCH_MODULAR(experiment=experiment, data=experiment.lookup_data())
        means, covariance = adapter.predict([ObservationFeatures(parameters=point)])
        predictions = {}
        for objective in objectives_for(project):
            name = objective["name"]
            if name in means:
                mean = float(means[name][0])
                variance = float(covariance[name][name][0])
                if not is_finite_number(mean) or not is_finite_number(variance) or variance < 0:
                    raise ValueError("Invalid prediction.")
                predictions[name] = {"mean": mean, "sigma": math.sqrt(variance)}
        return predictions
    except Exception as exc:
        raise RuntimeError("Prediction failed. Check the project and try again.") from exc
