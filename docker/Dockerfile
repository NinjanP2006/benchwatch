# Pinned toolchain for benchmark builds: both sides of every comparison, and
# every CI run, compile with the same GCC/CMake/Python. Bump the base image or
# uv version deliberately; it changes generated code and therefore timings.
#
# Build from the repo root:  docker build -f docker/Dockerfile -t benchwatch-toolchain .
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates ccache cmake g++ git ninja-build python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

ENV CMAKE_GENERATOR=Ninja \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# The repo is bind-mounted and owned by a different uid than root.
RUN git config --system --add safe.directory '*'

# Bake the Python dependencies into the image; only the project itself is
# installed at run time. The venv lives outside the mount so it can't clash
# with a host .venv.
COPY pyproject.toml uv.lock /tmp/deps/
RUN cd /tmp/deps && uv sync --frozen --no-install-project --no-dev && rm -rf /tmp/deps

WORKDIR /work
