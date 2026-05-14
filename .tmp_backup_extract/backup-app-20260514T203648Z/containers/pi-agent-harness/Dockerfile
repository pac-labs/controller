FROM node:20-slim

ARG PI_NPM_PACKAGE=@mariozechner/pi-coding-agent

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git openssh-client python3 tini \
    && rm -rf /var/lib/apt/lists/*

# The exact Pi npm package name may change. Override PI_NPM_PACKAGE at build time if needed.
# Example: podman build --build-arg PI_NPM_PACKAGE=@your/pi-package -t localhost/pi-agent-harness:stage11 .
RUN npm install -g ${PI_NPM_PACKAGE} || true

RUN useradd -m -u 10001 piagent
WORKDIR /workspace
COPY entrypoint.sh /usr/local/bin/pi-agent-entrypoint
RUN chmod +x /usr/local/bin/pi-agent-entrypoint && mkdir -p /workspace/pi-agent-artifacts && chown -R piagent:piagent /workspace
USER piagent
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/pi-agent-entrypoint"]
