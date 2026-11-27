FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS dev
RUN pip install --no-cache-dir poetry==2.1.3
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root
COPY . .
CMD ["solara", "run", "gui/app.py", "--host", "0.0.0.0", "--port", "8756", "--no-open"]

FROM base AS prod
RUN pip install --no-cache-dir poetry==2.1.3
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root
COPY . .
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/')" || exit 1
CMD ["solara", "run", "gui/app.py", "--host", "0.0.0.0", "--port", "8765", "--production", "--workers", "1", "--no-open"]
