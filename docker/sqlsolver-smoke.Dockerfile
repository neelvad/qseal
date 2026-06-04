FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    file \
    openjdk-17-jdk \
  && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:${PATH}"
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/tmp/snowprove-venv
ENV UV_CACHE_DIR=/tmp/snowprove-uv-cache

WORKDIR /sqlsolver
