FROM pytorch/pytorch:2.15.0-cuda13.2-cudnn9-runtime AS base

LABEL version="2025.8" maintainer="https://github.com/ronmarti"

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=2.1

ENV PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    pipx && \
    rm -rf /var/lib/apt/lists/* && \
    pipx install "poetry==$POETRY_VERSION"

FROM base AS dev_claude

ARG TZ
ENV TZ="$TZ"

ARG CLAUDE_CODE_VERSION=latest

ARG USERNAME=node

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    iptables \
    ipset \
    iproute2 \
    dnsutils \
    aggregate \
    jq \
    sudo \
    wget && \
    useradd --create-home --shell /bin/bash "$USERNAME" && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Ensure default node user has access to /usr/local/share
RUN mkdir -p /usr/local/share/npm-global && \
    chown -R $USERNAME:$USERNAME /usr/local/share/npm-global
ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global \
    PATH="/usr/local/share/npm-global/bin:$PATH"

# Persist bash history.
RUN SNIPPET="export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
    && mkdir /commandhistory \
    && touch /commandhistory/.bash_history \
    && chown -R $USERNAME /commandhistory

# Set `DEVCONTAINER` environment variable to help with orientation
ENV DEVCONTAINER=true

# Create workspace and config directories and set permissions
RUN mkdir -p /workspace /home/node/.claude && \
    chown -R $USERNAME:$USERNAME /workspace /home/node/.claude

WORKDIR /workspace

ARG GIT_DELTA_VERSION=0.18.2
RUN ARCH=$(dpkg --print-architecture) && \
  wget "https://github.com/dandavison/delta/releases/download/${GIT_DELTA_VERSION}/git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb" && \
  dpkg -i "git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb" && \
  rm "git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb"

# Set up non-root user
USER node

# Set the default shell to bash rather than sh
ENV SHELL=/bin/bash

# Install Claude
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Copy and set up firewall script
COPY .devcontainer/init-firewall.sh /usr/local/bin/
USER root
RUN chmod +x /usr/local/bin/init-firewall.sh && \
  echo "node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall
USER node

FROM dev_claude AS dev

COPY pyproject.tom[l] poetry.loc[k] ./
# RUN poetry config virtualenvs.in-project true
RUN poetry install --no-interaction --no-ansi --no-cache --no-root
USER root
RUN ln -s "$(su node -c 'poetry env info --path')" /opt/experiment-guide-venv
USER node
ENTRYPOINT []
CMD ["/bin/sh", "-c", "while sleep 1000; do :; done"]

FROM base AS prod
WORKDIR /experiment-guide
COPY pyproject.tom[l] poetry.loc[k] ./
RUN poetry install --no-interaction --no-ansi --no-cache --no-root && \
    ln -s "$(poetry env info --path)" /opt/experiment-guide-venv
COPY . ./
ENV PATH="/opt/experiment-guide-venv/bin:$PATH" \
    PYTHONPATH=/experiment-guide \
    MPLBACKEND=Agg
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/')" || exit 1
# A single worker keeps one shared training job visible to every browser session.
CMD ["solara", "run", "gui/app.py", "--host", "0.0.0.0", "--port", "8765", "--production", "--workers", "1", "--no-open"]