# experiment-guide

App for adaptive experimentation. It stores, visualizes results and propose next experiments based on the given data.

## Start a project

Set `APP_ACCESS_KEY` and run `docker compose up --build`, then open
http://localhost:8765. Enter the key and select **Authorize**. After login,
create a blank project or upload an exported project JSON file.

Projects are kept only in the current session. Download the project JSON
before closing the session or restarting the container to retain your changes.
You can upload another project JSON at any time to replace the active project;
download your current project first if you want to keep it.

On **Runs and recommendations**, generate a batch or select **Add run** to
create a blank row. Edit parameter values and results directly in the table,
then select **Save** for each row before leaving the screen or downloading.
New runs and recommendations appear at the end of the table and keep their
order when saved or reloaded.
You can save rows with missing objective results. Ax uses available results
without imputing the missing ones. Observed rows must have valid values for
all current parameters before generating another batch. **Delete** removes a
row; for a recommendation, it also removes the linked run, if any. CSV imports
add separate runs and do not automatically match recommendations, since parameter
values may repeat.
The best saved observed values are highlighted for each objective, including
ties; unsaved edits and predictions are not ranked.
Each row shows the model's predicted mean ± sigma for each objective
alongside, but separately from, observed results. Sigma is the
posterior standard deviation of the expected outcome, not measurement error.
Predictions update as you edit recommendation parameters, using saved
observations. Saving any row refreshes and stores its predictions,
including any result just saved. Prediction previews are not saved until the
row is saved. Predictions are unavailable without observations, for incomplete
or invalid parameter values, and for objectives without data.
Wait for the update to finish before downloading. If interrupted, a saved
refresh resumes when the runs tab is reopened. Other existing predictions
remain snapshots until their rows are refreshed.

On **Configuration**, add or edit parameters, objectives, and linear
constraints in their respective tables. Save each row before leaving the
screen. Multiple objectives are optimized simultaneously; existing measurements
are retained when definitions change.

## Source layout and tests

The Solara entry point is `gui/app.py`; components and session state live in
`gui/`. Project data helpers are in `experiment/model/`, while validation,
configuration, persistence, runs, and Ax integration are in
`experiment/services/`. `gui/services.py` wires the services and their
dependencies for each session; tests can inject an optimizer or Ax client
factory. Project JSON remains compatible with existing schema versions.

Run the unit and UI component tests with:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 poetry run python -m unittest discover -s tests -v
```

## Try it out

Try the python method with some noise:

```python
import numpy as np
z = lambda x, y: np.exp(-((x-1.67)*(y-1.35))**2) + np.exp( -1.2*(x+1.16)**2 ) + 0.1*np.random.normal()
z(0, 0)
```
