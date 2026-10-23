FROM node:24.22.1-bookworm@sha256:6449e19d8184d84062525b6a7524def03146c2cb04a7f08b076680d0e8e4240a

ENV CI=true \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0

RUN corepack enable \
    && corepack prepare pnpm@11.17.0 --activate \
    && git config --global user.name "VueBench" \
    && git config --global user.email "vuebench@localhost" \
    && git config --global init.defaultBranch main

WORKDIR /testbed

# Snapshot the base commit without any history, so the fix is not reachable.
RUN git init -q \
    && git fetch -q --depth 1 https://github.com/vueuse/vueuse.git 83e0043828c00cfbbba9fd310ecd59c5fba14db0 \
    && git checkout -q FETCH_HEAD \
    && rm -rf .git \
    && git init -q \
    && git add -A \
    && git commit -q -m "Base snapshot"

RUN pnpm install --frozen-lockfile --ignore-scripts
