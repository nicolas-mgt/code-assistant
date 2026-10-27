FROM --platform=$BUILDPLATFORM golang:1.26-alpine@sha256:a2012b4a1d1f9f7e9f44e0d39b805a901e856b1dd80b4e6ee4338db547050308 AS guard-build
WORKDIR /src
COPY docker/request-guard/ ./
RUN go test ./...
ARG TARGETOS TARGETARCH
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags="-s -w" -o /request-guard .

FROM eceasy/cli-proxy-api:v8.0.28@sha256:5de1679350c368fb031d46900da30d97c1e9e9a3b150fc4c4181e7e65022a09e
COPY --from=guard-build /request-guard /usr/local/bin/request-guard
LABEL org.opencontainers.image.source="https://github.com/nicolas-mgt/code-assistant"
ENV TZ=Europe/Warsaw
ENTRYPOINT ["/CLIProxyAPI/CLIProxyAPI"]
CMD ["--config", "/etc/ai-gateway/config.json", "--local-model"]
