# Harbor on Agent Substrate PoC

An external Harbor environment provider for one versioned Linux smoke task. The package uses Harbor's `environment.import_path` and the pinned `ate-env-client`; it does not provision a cluster. Source revisions and local image IDs are in [REVISION_PINS.md](REVISION_PINS.md).

## Local checks

```sh
uv sync --dev
uv run pytest tests/test_*.py -q
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

The lockfile currently uses exact Git `file://` revisions because the pinned Harbor commit is local and absent from its remote. Update the URLs to reachable commit pins before installing elsewhere.

## Prepare images and templates

Build from the `/Users/adhita/projects/python/src/github.com` directory, which contains both `agent-substrate/env` and this repository. Use the Go and Ubuntu base digests in `REVISION_PINS.md`:

```sh
docker build --build-arg GO_BASE=golang@sha256:3680233e3204827fbdc66088528ae6d4b3d034f51d03a99d454f6de034888244 --build-arg RUNTIME_BASE=ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3 -f harbor-agent-substrate/smoke/environment/Dockerfile -t harbor-smoke-agent:v1 .
docker build --build-arg GO_BASE=golang@sha256:3680233e3204827fbdc66088528ae6d4b3d034f51d03a99d454f6de034888244 --build-arg RUNTIME_BASE=ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3 -f harbor-agent-substrate/images/verifier/Dockerfile -t harbor-smoke-verifier:v1 .
```

Push both images to a registry visible to the existing cluster. Record their pushed `repo@sha256:...` digests in `REVISION_PINS.md`; local image IDs are not registry digests. Copy `provider.example.toml` to `provider.toml` and set those two digests, the atespace, worker label, and snapshot bucket. The configured CPU and memory must match both template limits.

```sh
uv run python scripts/check_cluster.py --config provider.toml --render-dir rendered-templates
kubectl ate create actor-template -f rendered-templates/agent.yaml
kubectl ate create actor-template -f rendered-templates/verifier.yaml
```

Use the pinned `kubectl ate` CLI for the cluster. The installed templates must route guest gRPC through the actor router and expose guest port 80 with `/readyz`.

## Run the proof on the existing cluster

In a separate terminal, create a private local port forward:

```sh
kubectl port-forward -n ate-env svc/ate-env-api 7777:7777
```

Then run:

```sh
export ATE_ENV_ENDPOINT=localhost:7777
export ATE_ENV_PROVIDER_CONFIG="$PWD/provider.toml"
uv run python scripts/check_cluster.py --config provider.toml
uv run pytest tests/cluster/test_smoke.py -q
```

The preflight checks installed templates against rendered manifests, then creates a temporary actor to test process and binary file routing. The cluster tests run Harbor's `oracle` on `poc/actor-smoke@1.0.0`, verify the declared artifact and reward, and must also prove concurrent isolation and suspended retention. Without `ATE_ENV_ENDPOINT`, the cluster test reports `UNVERIFIED SETUP` as a skip; that is not a PoC pass.
