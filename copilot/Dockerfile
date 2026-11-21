# Incident copilot: the CLI plus a pinned kubectl, running as a non-root user.
# Build context is the copilot/ folder:  docker build -t incident-copilot copilot/

# --- build the single-file CLI -------------------------------------------------------------
FROM node:22.23.4-slim AS build
WORKDIR /src
COPY package.json package-lock.json tsconfig.base.json tsconfig.json ./
COPY packages ./packages
COPY scripts ./scripts
RUN npm ci --ignore-scripts && npm run bundle

# --- fetch kubectl, verifying a pinned checksum --------------------------------------------
FROM node:22.23.4-slim AS kubectl
ARG TARGETARCH=amd64
ARG KUBECTL_VERSION=v1.37.2
ARG KUBECTL_SHA256_AMD64=c04487523e7aa7d1493f7808174c899db93d7a9cf57531420cd76b9bd415f8f4
ARG KUBECTL_SHA256_ARM64=fcc16f63186659d9722014b7e02d5fdd2d4e669cb8c0ab66365d7d3b8ba03509
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && case "$TARGETARCH" in \
      amd64) sum="$KUBECTL_SHA256_AMD64" ;; \
      arm64) sum="$KUBECTL_SHA256_ARM64" ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
 && echo "${sum}  /usr/local/bin/kubectl" | sha256sum -c - \
 && chmod 0755 /usr/local/bin/kubectl

# --- runtime: no curl, no compiler, no package manager state -------------------------------
FROM node:22.23.4-slim
LABEL org.opencontainers.image.title="incident-copilot" \
      org.opencontainers.image.description="Read-only incident triage for Kubernetes and Prometheus" \
      org.opencontainers.image.source="https://github.com/Bilalkhanten/ai-digest" \
      org.opencontainers.image.licenses="MIT"
COPY --from=kubectl /usr/local/bin/kubectl /usr/local/bin/kubectl
COPY --from=build /src/packages/cli/dist/copilot.js /app/copilot.js
USER node
WORKDIR /home/node
# Mount your kubeconfig read-only:  -v ~/.kube:/home/node/.kube:ro
ENTRYPOINT ["node", "/app/copilot.js"]
CMD ["--help"]
