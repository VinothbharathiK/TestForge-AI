class ExecutionSandbox:
    async def run_test_in_docker(self, test_code: str) -> tuple[bool, str, str]:
        """Return mock execution results until Docker subprocess logic is added."""
        return True, "Pass", "Output logs"
