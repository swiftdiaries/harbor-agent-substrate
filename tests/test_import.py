from harbor_agent_substrate.environment import SubstrateEnvironment
from harbor.environments.base import BaseEnvironment


def test_import_path():
    assert issubclass(SubstrateEnvironment, BaseEnvironment)
