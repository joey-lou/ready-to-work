"""Pytest fixtures for rtw test suite."""

import pytest
from helpers import (
    make_architect_flow,
    make_mock_llm,
    make_state,
)


@pytest.fixture
def mock_llm():
    return make_mock_llm()


@pytest.fixture
def architect_flow(mock_llm):
    return make_architect_flow(mock_llm)


@pytest.fixture
def base_state():
    return make_state()
