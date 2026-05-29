FROM docker.io/library/golang:1.23 AS pacctl-builder

WORKDIR /src
COPY binaries/pacctl/ ./binaries/pacctl/
WORKDIR /src/binaries/pacctl
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /out/pacctl .

FROM docker.io/library/node:20-slim

ARG PI_NPM_PACKAGE=pi-coding-agent
ARG PI_CONTAINER_VERSION=dev

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git openssh-client python3 tini \
    && rm -rf /var/lib/apt/lists/*

# The exact Pi npm package name may change. Override PI_NPM_PACKAGE at build time if needed.
# Example: podman build --build-arg PI_NPM_PACKAGE=@your/pi-package -t localhost/pi-agent-harness:stage11 .
RUN npm install -g ${PI_NPM_PACKAGE} || true

WORKDIR /workspace
COPY --from=pacctl-builder /out/pacctl /usr/local/bin/pacctl
COPY containers/pi-agent-harness/entrypoint.sh /usr/local/bin/pi-agent-entrypoint
LABEL org.opencontainers.image.version="${PI_CONTAINER_VERSION}" \
      pac.pi_container.version="${PI_CONTAINER_VERSION}" \
      pac.pi_npm_package="${PI_NPM_PACKAGE}"
RUN chmod +x /usr/local/bin/pi-agent-entrypoint /usr/local/bin/pacctl \
    && mkdir -p /workspace/pi-agent-artifacts
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/pi-agent-entrypoint"]
