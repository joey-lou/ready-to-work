"""Pytest fixtures for rtw test suite."""

import pytest
from helpers import MockAgentBackend, make_architect_flow, make_state


@pytest.fixture
def mock_agent():
    return MockAgentBackend()


@pytest.fixture
def architect_flow(mock_agent):
    return make_architect_flow(mock_agent)


@pytest.fixture
def base_state():
    return make_state()
