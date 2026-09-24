# Harbor on Agent Substrate PoC

An external Harbor environment provider for one versioned Linux smoke task. The package uses Harbor's `environment.import_path` and the pinned `ate-env-client`; it does not provision a cluster. Source revisions and local image IDs are in [REVISION_PINS.md](REVISION_PINS.md).

## Local checks

Prerequisites: Git, `uv`, and Docker. Start in an empty directory and create this layout:

```sh
mkdir harbor-poc
cd harbor-poc
git clone https://github.com/swiftdiaries/harbor-agent-substrate.git harbor-agent-substrate
mkdir agent-substrate
git clone https://github.com/swiftdiaries/env.git agent-substrate/env
git -C agent-substrate/env checkout ab40c7bfb2049af1a7aade9e7bf9c6cac925b5ca
cd harbor-agent-substrate
uv sync --dev
uv run pytest tests/test_*.py -q
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

The resulting layout is `harbor-poc/harbor-agent-substrate` and `harbor-poc/agent-substrate/env`.

The lockfile pins publicly reachable Harbor and `ate-env-client` Git commits. The original Harbor design checkout had two additional documentation commits; its runtime code matches the pinned public commit.

## Prepare images and templates

The Dockerfiles expect this repository and the pinned `env` checkout under one parent directory. The checkout steps above already created this layout. From `harbor-poc/harbor-agent-substrate`, build with the parent as the Docker context:

```sh
cd ..
docker build --build-arg GO_BASE=golang@sha256:3680233e3204827fbdc66088528ae6d4b3d034f51d03a99d454f6de034888244 --build-arg RUNTIME_BASE=ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3 -f harbor-agent-substrate/smoke/environment/Dockerfile -t harbor-smoke-agent:v1 .
docker build --build-arg GO_BASE=golang@sha256:3680233e3204827fbdc66088528ae6d4b3d034f51d03a99d454f6de034888244 --build-arg RUNTIME_BASE=ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3 -f harbor-agent-substrate/images/verifier/Dockerfile -t harbor-smoke-verifier:v1 .
cd harbor-agent-substrate
```

Before the cluster commands, make sure you have access to an existing cluster with the `kubectl ate` plugin, a registry reachable by that cluster, and a snapshot bucket usable by its workers. This repository does not provision the cluster or document a `kubectl ate` version or installation procedure.

Push both images to the reachable registry. Put each pushed `repo@sha256:...` digest in the matching image field in `provider.toml`; local image IDs are not registry digests. You can also record the pushed digests in `REVISION_PINS.md`. Copy the example config and replace its values: set `atespace` (in the top-level setting and both template entries), the worker label key and value used by your cluster, the snapshot bucket URI, and both registry image digests. Set each template's CPU and memory values to the limits in its rendered template (currently 1 CPU and 512 MB for both).

```sh
cp provider.example.toml provider.toml
```

Render the templates, then install them into the existing cluster:

```sh
uv run python scripts/check_cluster.py --config provider.toml --render-dir rendered-templates
kubectl ate create actor-template -f rendered-templates/agent.yaml
kubectl ate create actor-template -f rendered-templates/verifier.yaml
```

The installed templates must route guest gRPC through the actor router and expose guest port 80 with `/readyz`.

## Run the proof on the existing cluster

In a separate terminal, from any directory, create a private local port forward:

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

Current state: the operator has no cluster available, so no installed template, real Harbor trial, concurrent run, or retention result has been verified. Local images were built but not pushed to a registry.
