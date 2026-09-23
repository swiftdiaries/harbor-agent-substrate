from harbor.environments.base import BaseEnvironment


class SubstrateEnvironment(BaseEnvironment):
    @staticmethod
    def type() -> str:
        return "agent-substrate"

    def _validate_definition(self):
        raise NotImplementedError

    async def start(self, force_build: bool):
        raise NotImplementedError

    async def stop(self, delete: bool):
        raise NotImplementedError

    async def upload_file(self, source_path, target_path):
        raise NotImplementedError

    async def upload_dir(self, source_dir, target_dir):
        raise NotImplementedError

    async def download_file(self, source_path, target_path):
        raise NotImplementedError

    async def download_dir(self, source_dir, target_dir):
        raise NotImplementedError

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        raise NotImplementedError
