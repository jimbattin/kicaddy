FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 git curl ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent
USER node
WORKDIR /home/node
