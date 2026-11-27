# Adaptive Experimentation - MVP Product Specification

## 1. Product summary

Build a domain-neutral web app for manual adaptive experimentation. A user
defines a search space and a numeric objective, imports or enters experiment
results, and requests batches of candidate parameterizations. The user performs
the experiments outside the app and records the results.

The MVP is a stateless, ephemeral service demonstrated locally with Docker
Desktop. A project is portable as a JSON file rather than stored by the
service. Deployment to an AWS container service may follow, but AWS-specific
architecture is not part of the MVP.

## 2. MVP scope

- Access using a deployment-configured API key supplied at startup.
- Start a blank project or upload a previously exported project JSON file.
- Define continuous, integer, and categorical parameters.
- Define one numeric objective to maximize or minimize.
- Import experiment results from CSV, and add, edit, or delete results in the UI.
- Generate user-requested batches using Ax: start with a space-filling design
  and adapt subsequent recommendations to observed results.
- View experiment runs, recommendations, and objective history.
- Download the complete project state as JSON.
- Run on CPU in a standard application container.

Accounts, teams, sharing, permissions, persistent server-side project storage,
GPU execution, and AWS-specific services are outside the MVP.

## 3. Access and session

- The deployment supplies an application access key through configuration.
- The user enters the key on the startup screen; the server validates it before
  allowing project operations.
- Authorization applies to the current session. There are no user accounts,
  registration, roles, project ownership, or per-user limits.
- Separate sessions must not expose each other's in-memory project state.
- The key is not included in exported project files or logs, and invalid keys
  are rejected without revealing the configured key.
- Use HTTPS when the app is exposed beyond a trusted local environment.

## 4. Project and data

A project contains its parameter definitions, objective definition, experiment
runs, and generated recommendation batches. The app holds the active project
only for the current session; the service is not a durable project store.

### 4.1 Parameters and objective

- Continuous parameters have inclusive numeric bounds.
- Integer parameters have inclusive integer bounds.
- linear constraints are part of MVP.
- Categorical parameters have a defined set of choices.
- The project has one numeric scalar objective, with a maximize or minimize
  direction.
- Boolean and fixed parameters, log-scaled ranges,
  conditional parameters, and derived parameters are deferred.

### 4.2 Runs

- A run records parameter values and one numeric objective result.
- Users can import runs from CSV and add, edit, or delete runs in the UI.
- Repeated parameterizations are allowed as separate runs.
- The app validates parameter names, values, and the objective against the
  current project definition. Invalid input is reported to the user rather than
  silently accepted or discarded.
- Partial results, measurement standard errors, run statuses, and audit history
  are deferred.

### 4.3 CSV import

- CSV represents experiment results; it is not the project persistence format.
- The import identifies columns for each project parameter and the objective.
- The app reports schema and row validation errors so the user can correct the
  file. An invalid import must not partially change the project.
- Uploads are size-limited and parsed as data, without executing file contents.
- CSV export is deferred; the project JSON is the MVP export.

## 5. Recommendations

- The user chooses a batch size and explicitly requests recommendations.
- Ax selects the generation strategy; the user does not select an algorithm.
- Before sufficient observations exist, Ax generates a space-filling initial
  batch. Valid imported or manually entered observations can contribute to
  subsequent adaptive generation.
- The app displays and retains generated parameterizations in the project.
  Users perform the experiments externally and enter or import their results.
- Failures are shown to the user without exposing credentials or infrastructure
  details. The app must not present a failed generation as a successful batch.
- Multi-objective and weighted-scalar optimization, prediction refresh,
  uncertainty intervals, and recommendation editing.

## 6. UI

The MVP provides:

- A startup screen for the access key and a choice to create or load a project.
- Access key must be treated as a secure password that has to stay safe.
- Project configuration and run entry/import screens.
- A run table and a table of generated recommendations.
- A simple chart of the objective over run order.
- A project JSON download action and clear feedback for invalid input or errors.
- Parameter-response plots, Pareto plots, convergence indicators, and model
predictions.

## 7. Persistence and portability

- The user explicitly downloads a JSON file containing the complete project
  state, including definitions, runs, and recommendation batches.
- Uploading a valid exported JSON file restores that state for continued work.
  Project files do not contain the access key or session credentials.
- The file format includes a schema version. Invalid or unsupported files are
  rejected with a clear error without replacing the active project.
- There is no server-side durable storage or automatic save. Closing a session,
  restarting the container, or losing session state can discard changes since
  the last download; the UI makes this risk clear.
- Ax state is reconstructed from the project data when generating candidates;
  the MVP does not promise immutable model snapshots or versioned reproducibility.

## 8. Execution and deployment

- The application and CPU-based optimization run in a standard Docker container,
  suitable for demonstration on localhost with Docker Desktop - prepare production Docker stage.
- Recommendation generation may take time; the UI communicates progress or
  waiting and reports failures.
- Separate workers, durable job queues, returning later to jobs, GPU execution,
  and AWS-specific deployment research or infrastructure are deferred.
- An external-runner API and project-scoped API tokens are deferred.
