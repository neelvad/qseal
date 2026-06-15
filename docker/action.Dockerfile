# Container image for the snowprove GitHub Action (deterministic tier only:
# the builtin rule scanner needs no external solvers).
FROM python:3.12-slim

WORKDIR /opt/snowprove
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts/action_entrypoint.py ./action_entrypoint.py

# git is needed for --changed-since diff scoping.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir .

# The dbt project is mounted at the GitHub workspace; trust it for git ops.
RUN git config --system --add safe.directory '*'

ENTRYPOINT ["python", "/opt/snowprove/action_entrypoint.py"]
