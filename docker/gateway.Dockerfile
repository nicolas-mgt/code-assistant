FROM eceasy/cli-proxy-api:v8.0.28@sha256:5de1679350c368fb031d46900da30d97c1e9e9a3b150fc4c4181e7e65022a09e
LABEL org.opencontainers.image.source="https://github.com/nicolas-mgt/code-assistant"
ENV TZ=Europe/Warsaw
ENTRYPOINT ["/CLIProxyAPI/CLIProxyAPI"]
CMD ["--config", "/etc/ai-gateway/config.json", "--local-model"]
