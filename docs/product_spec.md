# Adaptive Experimentation SaaS - Product Specification

## 1. Product summary

Build a public, domain-neutral SaaS for manual adaptive experimentation. Users
describe an experiment search space and numeric objectives, enter run results,
and request a batch of candidate parameterizations. The platform shows observed
history and model predictions with uncertainty.

The product is not an equipment-automation system in the first release. The
system may be extended later through an API that lets external runners retrieve
recommendations and submit results.

## 2. Launch scope

The public launch must include:

- Google OAuth sign-in.
- Invitation-only registration by default, with an admin-controlled open-registration setting.
- Admin and user roles.
- Project ownership, reusable teams, project sharing, and email invitations.
- Continuous, integer, choice/categorical, boolean, and fixed parameters.
  Conditional/dependent and derived parameters are deferred.
- Linear numeric parameter constraints.
- Log-scaled continuous/integer ranges.
- One or more numeric scalar metrics with maximize or minimize direction.
- Single-objective and multi-objective Pareto modes.
- Weighted-scalar objective mode with nonnegative raw-value coefficients.
- Automatic Ax strategy selection and an initial Sobol/space-filling phase.
- CPU and GPU recommendation jobs.
- Asynchronous jobs with status.
- Audited experiment-row edits.
- CSV import/export.
- Metric history, parameter-response, and Pareto visualizations.
- Project-scoped external-runner API tokens reserved for the future integration API.

## 3. Roles and access

### 3.1 Platform roles

- **User**: owns projects and teams, joins teams, and interacts with shared projects.
- **Admin**: manages users and projects, controls registration, GPU availability,
  and per-user runtime, concurrency, and batch-size limits.

The first platform admin is configured by deployment settings using the verified
Google email address. Account deletion requires that every owned project first
be transferred or deleted.

### 3.2 Registration and invitations

- Registration defaults to invitation-only.
- Admins may switch to open Google registration.
- Team owners invite users by exact email address.
- There is no global user search or account directory.
- A team invitation may be accepted after the invitee signs in with Google.
- Only team owners manage team membership and sharing.

### 3.3 Projects and teams

- Projects are private by default.
- Owners may create reusable teams and invite users to them.
- A project may be shared with multiple teams.
- Each team-project grant is view-only or edit.
- The owner retains ownership and project administration.
- If a user receives both view and edit grants, edit permission wins.
- Shared users with edit access may edit experiment data/settings and generate
  jobs. View users may view project data and results.

## 4. Project model

A project contains:

- Search-space parameter definitions.
- Parameter constraints.
- Objective/metric definitions and directions.
- Objective mode.
- Experiment runs.
- Recommendation batches.
- Project sharing and API-token settings.
- Audit history.

### 4.1 Parameters

Supported types:

- Continuous float ranges with inclusive bounds.
- Integer ranges with inclusive bounds.
- Choice/categorical parameters.
- Boolean choice parameters.
- Fixed parameters.
- Log scale for float and integer ranges.

Numeric linear constraints are supported, for example
`x1 + 2*x2 <= 10`. Conditional/dependent parameter choices are deferred.

### 4.2 Metrics

- Each metric is one numeric scalar per run.
- Every metric has a maximize or minimize direction.
- Missing metric values are allowed.
- Missing values are never imputed.
- Optional measurement standard error may be supplied per run and metric.
- Partial observations contribute to objective-specific modeling where Ax
  supports partial data.

## 5. Optimization behavior

### 5.1 Strategy selection

The app uses Ax for strategy selection and candidate generation. Users do not
choose an algorithm in the MVP.

- Before enough observations exist, request an initial space-filling/Sobol batch.
- Use Ax's automatic generation strategy after the initialization phase.
- Existing externally supplied observations may count toward initialization.
- For GPU jobs, select GPU for Ax/PyTorch/BoTorch model fitting and candidate
  generation when available.
- The CPU default must remain the lowest-cost option.

CPU and GPU are independent execution resources, not a parameter of the Ax
experiment state.

### 5.2 Batch generation

- The user requests a batch and chooses N.
- The platform generates N together from one snapshot of current project data.
- The batch remains fixed until results are entered or the batch is modified.
- Fewer than N results may be entered.
- Unrun recommendations in a returned batch are marked skipped.
- The user explicitly requests the next batch after entering results.
- External runs may be added in addition to generated recommendations.
- An external run may link to a recommendation while retaining actual parameter
  values different from the suggested values.

### 5.3 Initial observations

- A project may generate recommendations before it has any results.
- The initial batch uses an Ax space-filling design.
- Later batches adapt to observed data.

### 5.4 Out-of-space observations

- External runs may store parameter values outside the current search space.
- Such runs remain visible as history.
- They are excluded from optimization until a project parameter update brings
  them inside the active search space.

### 5.5 Objective modes

**Single objective**

- Use the configured maximize/minimize direction.

**Pareto/multi-objective**

- Generate candidate designs intended to represent or improve the Pareto frontier.
- Show observed and predicted Pareto tradeoffs.

**Weighted scalar**

- Allow nonnegative user-specified weights.
- Apply weights directly to raw metric values.
- Convert maximize objectives to positive terms and minimize objectives to negative
  terms, or otherwise define the score with a single unambiguous expression.
- Do not normalize or rescale metrics automatically.
- Users are responsible for scale choices.
- The UI shows units/ranges and warns about potentially unbalanced scales.

## 6. Uncertainty and predictions

- Model-predicted outcomes show 95% posterior credible intervals by default.
- Observed-run summaries show 95% statistical confidence intervals by default.
- The UI labels these interval types separately rather than presenting them as
  interchangeable.
- Optional measurement standard errors are used as observation noise where Ax
  supports that information.
- If no standard error is supplied, the model infers observation noise from runs.

## 7. Experiment data

### 7.1 Runs

One table row represents one completed or partial run:

- Run ID.
- Parameter values.
- Metric values.
- Optional metric standard errors.
- Optional link to a recommendation batch item.
- Origin: generated, external, or modified recommendation.
- Status: planned, running, completed, skipped, or failed.
- Audit metadata.

Repeated parameterizations are stored as separate rows.

### 7.2 Editing

- Users with edit permission may modify parameter and metric values.
- The platform keeps a change history with user, timestamp, old value, and new
  value.
- Compatible project-definition edits are allowed.
- Incompatible edits also remain allowed; affected old batches become historical
  and incompatible. Users may edit saved recommendation parameter values to restore
  compatibility.
- Editing a saved recommendation recalculates predictions and intervals for the
  edited parameterization and marks the item user-modified.
- Relevant project edits invalidate refreshable predictions and trigger
  recalculation of saved batch predictions using current project data.

**For an old batch:**

1. Preserve the original candidate parameterizations.
2. Refresh predictions and intervals against current data.
3. Mark the batch recomputed after relevant edits.
4. If a project-definition edit makes a candidate incompatible, preserve the
   candidate, mark it historical/incompatible, and do not silently drop it.

## 8. Visualizations

The launch UI must provide:

- Metric history over run order.
- Parameter-versus-metric plots with model uncertainty.
- Pareto plot for multi-objective projects.
- Batch candidate table with predictions and interval bounds.
- Convergence indicators derived from observed history/model behavior.
- CSV export of project runs and recommendation batches.

Convergence indicators are informational. The app never stops or suppresses
experiments automatically.

## 9. Async jobs and compute

### 9.1 Job lifecycle

Recommendation jobs are asynchronous:

`queued -> starting -> running -> succeeded | failed | cancelled`

The UI shows status and allows users to return later. Job failures include a
user-visible reason without exposing credentials or infrastructure details.

### 9.2 Compute

- Solara/FastAPI hosts UI and API; it does not perform heavy optimization inline.
- CPU jobs run in portable workers.
- GPU jobs run in GPU-capable workers.
- The AWS-first deployment uses Lambda-compatible CPU modules and a separate
  GPU-capable compute path.
- Lambda remains part of the CPU architecture; GPU execution is not assumed to
  be available there.
- A job must not silently change a GPU request to CPU.
- If GPU is unavailable or over its limit, fall back to CPU and show a clear
  notification.
- Admin GPU disablement prevents GPU job dispatch.

### 9.3 Limits

Admins configure per-user limits for:

- Maximum concurrent jobs.
- Maximum job runtime.
- Maximum batch size.
- Maximum GPU availability.

The UI shows a user's applicable limits and resource usage. There is no billing
system in the launch release.

## 10. Future external-runner API

The external runner API is not required for public launch hardware integration,
but the data model and authentication boundary must support it.

- Project-scoped revocable API tokens.
- Tokens have narrow permissions, such as fetch recommendations or submit runs.
- Users may create and revoke project tokens.
- External runners may fetch recommendation batches and submit actual runs.
- Submitted actual runs may differ from saved recommendations and remain linkable.
- Project edit permission rules do not bypass token-project scope.

## 11. Persistence and reproducibility

- Store project data, runs, audit changes, jobs, and saved batch configurations.
- Reconstruct Ax state from project data when generating jobs.
- A batch does not store an immutable Ax snapshot or model/package version.
- Batch edits and refreshes use current project data.
- The app stores enough configuration and data to generate future recommendations,
  but this is not a versioned experiment ledger.

## 12. Security and privacy

- All project access checks occur server-side.
- Project, team, token, and job operations use authorization checks at the API
  boundary and in worker entry points.
- API tokens are hashed at rest and shown only once.
- Google OAuth accounts must have verified email addresses.
- CSV uploads are size-limited, schema-validated, and parsed without code execution.
- Deleting a project deletes its runs, recommendation batches, audit history,
  API tokens, and job records, after owner confirmation.
