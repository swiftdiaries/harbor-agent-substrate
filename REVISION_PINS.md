# Source revisions

| Source | Clone URL | Commit |
| --- | --- | --- |
| Harbor runtime | `https://github.com/harbor-framework/harbor.git` | `3665008f25744a7137215b3425e4f06a70fda297` |
| ate-env | `https://github.com/swiftdiaries/env.git` | `ab40c7bfb2049af1a7aade9e7bf9c6cac925b5ca` |
| Substrate | `https://github.com/agent-substrate/substrate.git` | `672533541dbfcd29084e4de2475267088bda3651` |

| Image | Digest or local image ID |
| --- | --- |
| Go base | `golang@sha256:3680233e3204827fbdc66088528ae6d4b3d034f51d03a99d454f6de034888244` |
| Runtime base | `ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3` |
| Locally built agent | `sha256:e93f09cf8864870b6dd4afd366e6d0447a76e6cf537418d91ffd18b9cc2019fb` |
| Locally built verifier | `sha256:a43588e5b1638e5ed8535b9cad904b352f71632890d62aaf5c63e6e134be951a` |

The smoke images have no registry `RepoDigests` until an operator pushes them. Template images must use those pushed digest references.
