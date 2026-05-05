FROM docker.io/library/golang:1.24-alpine
WORKDIR /src
COPY mcp/pac-mcp-go/ /src/
COPY VERSION /src/VERSION
COPY containers/mcp-builder/build.sh /src/build.sh
RUN chmod +x /src/build.sh
ENTRYPOINT ["/src/build.sh"]
