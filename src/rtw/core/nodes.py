"""Base node abstraction for rtw architect loop."""

from abc import ABC, abstractmethod
from typing import Any

from .state import SharedState


class Node(ABC):
    """
    Base class for all nodes in the architect flow.

    Pattern inspired by PocketFlow:
    - prep(): Prepare inputs from shared state
    - exec(): Execute the node's logic (LLM call, file ops, etc.)
    - post(): Update shared state and return next action
    """

    def __init__(self, name: str | None = None):
        self.name = name or self.__class__.__name__
        self.successors: dict[str, Node] = {}
        #: If True, Flow increments current_iteration before this node and enforces max_iterations.
        self.increments_iteration: bool = False

    def prep(self, state: SharedState) -> Any:
        """Prepare inputs from shared state. Override in subclasses."""
        return None

    @abstractmethod
    def exec(self, prep_result: Any) -> Any:
        """Execute node logic. Must be implemented by subclasses."""
        pass

    def post(self, state: SharedState, prep_result: Any, exec_result: Any) -> str | None:
        """
        Update shared state and return next action.

        Returns:
            Action string that routes to next node, or None to end flow.
        """
        return None

    def run(self, state: SharedState) -> str | None:
        """Execute the full node lifecycle."""
        prep_result = self.prep(state)
        exec_result = self.exec(prep_result)
        return self.post(state, prep_result, exec_result)

    def __rshift__(self, other: "Node") -> "Node":
        """Default transition: self >> other"""
        self.successors["default"] = other
        return other

    def on(self, action: str) -> "_TransitionBuilder":
        """Conditional transition: self.on("action") >> other"""
        return _TransitionBuilder(self, action)


class _TransitionBuilder:
    """Helper for building conditional transitions."""

    def __init__(self, source: Node, action: str):
        self.source = source
        self.action = action

    def __rshift__(self, target: Node) -> Node:
        self.source.successors[self.action] = target
        return target
