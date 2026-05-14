FROM python:3.12-slim
ARG PAC_VERSION=dev
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git openssh-client ripgrep file sudo nano vim tree w3m jq bc \
    && pip install --no-cache-dir mdv pygments \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 piagent
COPY entrypoint.sh /usr/local/bin/pi-agent-entrypoint
RUN chmod +x /usr/local/bin/pi-agent-entrypoint \
    && mkdir -p /workspace/pi-agent-artifacts /workspace/repos /workspace/index \
    && chown -R piagent:piagent /workspace
WORKDIR /workspace
USER piagent
ENTRYPOINT ["/usr/local/bin/pi-agent-entrypoint"]
