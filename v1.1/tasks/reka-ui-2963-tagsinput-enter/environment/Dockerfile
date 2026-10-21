FROM node:24.22.0-bookworm@sha256:14078204b6bb268c107ceff6d3c43f45a888105e5c2b18b14c32b3409d93a1b0

ENV CI=true \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0

RUN corepack enable \
    && corepack prepare pnpm@10.13.1 --activate \
    && git config --global user.name "VueBench" \
    && git config --global user.email "vuebench@localhost" \
    && git config --global init.defaultBranch main

WORKDIR /testbed

# Snapshot the base commit without any history, so the fix is not reachable.
RUN git init -q \
    && git fetch -q --depth 1 https://github.com/unovue/reka-ui.git 65b6ced0e2cc0fed200e39cbc1eb8ebbd04616fb \
    && git checkout -q FETCH_HEAD \
    && rm -rf .git \
    && git init -q \
    && git add -A \
    && git commit -q -m "Base snapshot"

RUN pnpm install --frozen-lockfile --ignore-scripts
