import pytest

from src.sdk.agent import BaseAgent


class DemoAgent(BaseAgent):
    async def setup(self):
        pass

    async def handle_task(self, task):
        return task

    async def cleanup(self):
        pass


class TestBaseAgentMetadata:
    def setup_method(self):
        self.agent = DemoAgent("agent-1", "demo")

    def test_set_metadata_accepts_non_empty_string_key(self):
        self.agent.set_metadata("trace_id", "abc")

        assert self.agent.get_metadata("trace_id") == "abc"

    def test_set_metadata_rejects_empty_key(self):
        with pytest.raises(ValueError, match="non-empty"):
            self.agent.set_metadata("", "abc")

        assert self.agent.get_metadata("", "missing") == "missing"

    def test_set_metadata_rejects_whitespace_key(self):
        with pytest.raises(ValueError, match="non-empty"):
            self.agent.set_metadata("   ", "abc")

        assert self.agent.get_metadata("   ", "missing") == "missing"

    def test_set_metadata_rejects_non_string_key(self):
        with pytest.raises(TypeError, match="string"):
            self.agent.set_metadata(123, "abc")

        assert self.agent.get_metadata(123, "missing") == "missing"
