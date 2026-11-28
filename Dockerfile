FROM python:3.12-slim AS prod-cpu-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/experiment-guide-venv \
    PYTHONPATH=/app \
    MPLBACKEND=Agg

ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /app

FROM prod-cpu-base AS prod-cpu-build

RUN python -m venv "$VIRTUAL_ENV"
# Install Poetry outside the application environment so it is not copied into production.
RUN /usr/local/bin/python -m pip install --no-cache-dir poetry==2.1.3
COPY pyproject.tom[l] poetry.loc[k] ./
RUN poetry install --only main --no-interaction --no-ansi --no-cache --no-root

FROM prod-cpu-base AS prod-cpu

COPY --from=prod-cpu-build /opt/experiment-guide-venv /opt/experiment-guide-venv
COPY . ./
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/')" || exit 1
# A single worker keeps one shared training job visible to every browser session.
CMD ["solara", "run", "gui/app.py", "--host", "0.0.0.0", "--port", "8765", "--production", "--workers", "1", "--no-open"]