from harbor.environments.base import BaseEnvironment

from harbor_agent_substrate.environment import SubstrateEnvironment


def test_import_path():
    assert issubclass(SubstrateEnvironment, BaseEnvironment)
