"""Flow orchestrator for rtw architect loop."""

import logging
from collections.abc import Callable

from .nodes import Node
from .state import FlowStatus, SharedState

logger = logging.getLogger(__name__)


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

        logger.info(f"Starting flow '{self.name}' from node '{current_node.name}'")

        while current_node is not None:
            if state.current_iteration >= state.max_iterations:
                logger.warning(f"Max iterations ({state.max_iterations}) reached")
                state.status = FlowStatus.BLOCKED
                state.blocking_reason = (
                    f"Max iterations ({state.max_iterations}) reached without completion"
                )
                break

            logger.info(f"Executing node: {current_node.name}")

            try:
                action = current_node.run(state)
            except Exception as e:
                logger.error(f"Node '{current_node.name}' failed: {e}")
                state.status = FlowStatus.FAILED
                state.blocking_reason = f"Node '{current_node.name}' failed: {str(e)}"
                self._persist_state(state)
                raise

            self._persist_state(state)

            if action is None:
                logger.info(f"Flow completed at node '{current_node.name}'")
                break

            next_node = current_node.successors.get(action)
            if next_node is None:
                next_node = current_node.successors.get("default")

            if next_node is None:
                logger.warning(
                    f"No successor for action '{action}' from node '{current_node.name}'"
                )
                break

            logger.debug(f"Transitioning: {current_node.name} --{action}--> {next_node.name}")
            current_node = next_node

        return state

    def _persist_state(self, state: SharedState) -> None:
        """Trigger state persistence callback if configured."""
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception as e:
                logger.error(f"State persistence failed: {e}")
