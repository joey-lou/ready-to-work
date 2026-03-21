"""Flow orchestrator for rtw architect loop."""

import logging
from collections.abc import Callable

from .nodes import Node
from .state import FlowStatus, SharedState

logger = logging.getLogger(__name__)

_NODE_RUN_EXCEPTIONS = (OSError, ValueError, TypeError, RuntimeError, KeyError)


class Flow:
    """
    Orchestrates node execution in the architect loop.

    Handles:
    - Node routing based on action strings
    - Max iteration limits
    - State persistence callbacks
    - Error handling and blocking detection
    """

    def __init__(
        self,
        start: Node,
        name: str = "rtw",
        on_state_change: Callable[[SharedState], None] | None = None,
    ):
        self.start = start
        self.name = name
        self.on_state_change = on_state_change

    def run(self, state: SharedState) -> SharedState:
        """Execute the flow until completion, blocking, or max iterations."""
        current_node = self.start
        logger.info("Starting flow '%s' from node '%s'", self.name, current_node.name)

        while current_node is not None:
            if current_node.increments_iteration and self._block_if_max_planning_rounds(state):
                break
            if current_node.increments_iteration:
                state.start_iteration()
            logger.info("Executing node: %s", current_node.name)
            try:
                action = current_node.run(state)
            except _NODE_RUN_EXCEPTIONS as e:
                self._fail_node(state, current_node, str(e))
                raise
            self._persist_state(state)
            current_node, done = self._apply_action(action, current_node, state)
            if done:
                break

        return state

    def _block_if_max_planning_rounds(self, state: SharedState) -> bool:
        """Before a planning round, block if the limit is already reached."""
        if state.current_iteration < state.max_iterations:
            return False
        logger.warning("Max planning rounds (%d) reached", state.max_iterations)
        state.status = FlowStatus.BLOCKED
        state.blocking_reason = (
            f"Max planning rounds ({state.max_iterations}) reached without completion"
        )
        return True

    def _fail_node(self, state: SharedState, node: Node, message: str) -> None:
        """Record node failure and persist state."""
        logger.error("Node '%s' failed: %s", node.name, message)
        state.status = FlowStatus.FAILED
        state.blocking_reason = f"Node '{node.name}' failed: {message}"
        self._persist_state(state)

    def _apply_action(
        self, action: str | None, current_node: Node, state: SharedState
    ) -> tuple[Node | None, bool]:
        """Apply action from current node; return (next_node, done)."""
        if action is None:
            logger.info(
                "Flow completed at node '%s' (status: %s)",
                current_node.name,
                state.status.value,
            )
            return None, True
        if isinstance(action, str):
            next_node = current_node.successors.get(action) or current_node.successors.get(
                "default"
            )
            if next_node is None:
                logger.warning(
                    "No successor for action '%s' from node '%s'", action, current_node.name
                )
                return None, True
            logger.debug("Transitioning: %s --%s--> %s", current_node.name, action, next_node.name)
            return next_node, False
        logger.warning("Unexpected action type %r from node '%s'", action, current_node.name)
        return None, True

    def _persist_state(self, state: SharedState) -> None:
        """Trigger state persistence callback if configured."""
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except (OSError, ValueError, TypeError, RuntimeError) as e:
                logger.error("State persistence failed: %s", e)
