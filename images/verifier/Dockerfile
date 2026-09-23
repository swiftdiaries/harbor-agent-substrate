ARG GO_BASE
ARG RUNTIME_BASE
FROM ${GO_BASE} AS build
WORKDIR /src
COPY agent-substrate/env/ .
RUN CGO_ENABLED=0 go build -o /ate-env-guest ./cmd/ate-env-guest

FROM ${RUNTIME_BASE}
RUN apt-get update && apt-get install -y --no-install-recommends tar && rm -rf /var/lib/apt/lists/*
COPY --from=build /ate-env-guest /usr/local/bin/ate-env-guest
COPY harbor-agent-substrate/smoke/tests/test.sh /tests/test.sh
RUN chmod 755 /tests/test.sh
EXPOSE 80
ENTRYPOINT ["/usr/local/bin/ate-env-guest"]
