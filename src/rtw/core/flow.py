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

        logger.info("Starting flow '%s' from node '%s'", self.name, current_node.name)

        while current_node is not None:
            if state.current_iteration >= state.max_iterations:
                logger.warning("Max iterations (%d) reached", state.max_iterations)
                state.status = FlowStatus.BLOCKED
                state.blocking_reason = (
                    f"Max iterations ({state.max_iterations}) reached without completion"
                )
                break

            logger.info("Executing node: %s", current_node.name)

            try:
                action = current_node.run(state)
            except Exception as e:
                logger.error("Node '%s' failed: %s", current_node.name, e)
                state.status = FlowStatus.FAILED
                state.blocking_reason = f"Node '{current_node.name}' failed: {str(e)}"
                self._persist_state(state)
                raise

            self._persist_state(state)

            match action:
                case None:
                    logger.info(
                        "Flow completed at node '%s' (status: %s)",
                        current_node.name,
                        state.status.value,
                    )
                    break
                case str():
                    next_node = current_node.successors.get(action) or current_node.successors.get(
                        "default"
                    )
                    if next_node is None:
                        logger.warning(
                            "No successor for action '%s' from node '%s'", action, current_node.name
                        )
                        break
                    logger.debug(
                        "Transitioning: %s --%s--> %s", current_node.name, action, next_node.name
                    )
                    current_node = next_node
                case _:
                    logger.warning(
                        "Unexpected action type %r from node '%s'", action, current_node.name
                    )
                    break

        return state

    def _persist_state(self, state: SharedState) -> None:
        """Trigger state persistence callback if configured."""
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception as e:
                logger.error("State persistence failed: %s", e)
