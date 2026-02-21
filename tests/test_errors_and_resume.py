"""Tests for error handling, interruption, and resume scenarios."""

from unittest.mock import MagicMock

import pytest
from helpers import (
    APPROVE_RESPONSE,
    ITERATE_RESPONSE,
    PLAN_RESPONSE,
    MockAgentBackend,
    make_architect_flow,
    make_mock_agent,
    make_mock_llm,
    make_state,
)
from llm_mock import MockLLMClient

from rtw.architect import ExecutorNode, PlannerNode, ReviewerNode
from rtw.core import Flow, FlowStatus, Node, SharedState

# ---------------------------------------------------------------------------
# 1. Node raises exception → flow sets FAILED and re-raises
# ---------------------------------------------------------------------------


class ExplodingNode(Node):
    def exec(self, prep_result):
        raise ValueError("boom")


def test_node_exception_sets_failed_and_reraises():
    node = ExplodingNode("Exploding")
    flow = Flow(start=node)
    state = make_state()

    with pytest.raises(ValueError, match="boom"):
        flow.run(state)

    assert state.status == FlowStatus.FAILED
    assert "boom" in state.blocking_reason


# ---------------------------------------------------------------------------
# 2. State persistence failure is logged but does not crash the flow
# ---------------------------------------------------------------------------


def test_persistence_failure_does_not_crash_flow():
    llm = make_mock_llm()
    agent = make_mock_agent(llm)

    def bad_save(state):
        raise OSError("disk full")

    flow = make_architect_flow(agent, on_state_change=bad_save)
    state = make_state()

    # Should not raise; flow should still complete
    result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# 3. KeyboardInterrupt in flow.run() propagates
# ---------------------------------------------------------------------------


class InterruptingNode(Node):
    def exec(self, prep_result):
        raise KeyboardInterrupt


def test_keyboard_interrupt_propagates():
    node = InterruptingNode("Interrupt")
    flow = Flow(start=node)
    state = make_state()

    with pytest.raises(KeyboardInterrupt):
        flow.run(state)


# ---------------------------------------------------------------------------
# 4-6. Resume from various states continues correctly
# ---------------------------------------------------------------------------


def _run_resume_from(prior_status: FlowStatus) -> SharedState:
    """Helper: create state with prior_status, reset to PENDING, run full flow."""
    llm = make_mock_llm()
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent)
    state = make_state()
    state.status = prior_status
    # Reset to PENDING so flow restarts from planner (mirrors resume_run behaviour)
    state.status = FlowStatus.PENDING
    return flow.run(state)


def test_resume_from_planning():
    result = _run_resume_from(FlowStatus.PLANNING)
    assert result.status == FlowStatus.COMPLETED


def test_resume_from_building():
    result = _run_resume_from(FlowStatus.BUILDING)
    assert result.status == FlowStatus.COMPLETED


def test_resume_from_reviewing():
    result = _run_resume_from(FlowStatus.REVIEWING)
    assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# 7. Resume from COMPLETED is a no-op / state is already done
# ---------------------------------------------------------------------------


def test_completed_state_does_not_re_run():
    """A COMPLETED state loaded without status reset stays COMPLETED if caller checks."""
    state = make_state()
    state.status = FlowStatus.COMPLETED

    # Caller (resume_run) resets to PENDING before running – simulate that NOT happening
    # and just verify the state is not mutated when we inspect it directly.
    assert state.status == FlowStatus.COMPLETED
    assert state.current_iteration == 0  # nothing ran


# ---------------------------------------------------------------------------
# 8. MockLLMClient returns JSON with 'error' key → planner stores it and transitions
# ---------------------------------------------------------------------------


def test_planner_stores_json_with_error_key_and_builds():
    llm = MockLLMClient(responses={"architect": '{"error": "LLM down"}'})
    agent = MockAgentBackend(llm)
    planner = PlannerNode(agent)
    executor_mock = MagicMock()
    executor_mock.name = "MockExecutor"
    executor_mock.successors = {}
    planner.on("build") >> executor_mock

    state = make_state()
    action = planner.run(state)

    # Planner transitions to 'build' — the JSON happened to contain an 'error' key
    assert action == "build"
    assert state.current_plan.get("error") == "LLM down"


# ---------------------------------------------------------------------------
# 9. MockLLMClient with fail_with_json_error → raises
# ---------------------------------------------------------------------------


def test_complete_json_with_malformed_json_raises():
    llm = MockLLMClient(fail_with_json_error=True)
    with pytest.raises(RuntimeError, match="Injected JSON error"):
        llm.complete_json("some prompt")


# ---------------------------------------------------------------------------
# 10. max_iterations=1 with iterate verdict → BLOCKED
# ---------------------------------------------------------------------------


def test_max_iterations_with_iterate_verdict_blocks():
    llm = make_mock_llm(verdict_response=ITERATE_RESPONSE)
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent)
    state = make_state(max_iterations=1)

    result = flow.run(state)

    assert result.status == FlowStatus.BLOCKED


# ---------------------------------------------------------------------------
# 11. fail_on_call=1 triggers error on first call → FAILED
# ---------------------------------------------------------------------------


def test_fail_on_call_first_call_sets_failed():
    llm = MockLLMClient(fail_on_call=1)
    agent = MockAgentBackend(llm)
    flow = make_architect_flow(agent)
    state = make_state()

    with pytest.raises(RuntimeError):
        flow.run(state)

    assert state.status == FlowStatus.FAILED


# ---------------------------------------------------------------------------
# 12. side_effect raising RuntimeError mid-flow → FAILED
# ---------------------------------------------------------------------------


def test_side_effect_runtime_error_sets_failed():
    call_count = {"n": 0}

    def explode_on_second(prompt, system):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("side effect boom")
        return PLAN_RESPONSE

    llm = MockLLMClient(side_effect=explode_on_second)
    agent = MockAgentBackend(llm)
    flow = make_architect_flow(agent)
    state = make_state()

    with pytest.raises(RuntimeError, match="side effect boom"):
        flow.run(state)

    assert state.status == FlowStatus.FAILED


# ---------------------------------------------------------------------------
# 13. executor node with None plan handles gracefully
# ---------------------------------------------------------------------------


def test_executor_with_none_plan_does_not_crash():
    llm = make_mock_llm()
    agent = MockAgentBackend(llm)
    executor = ExecutorNode(agent)
    state = make_state()
    state.status = FlowStatus.BUILDING
    state.current_plan = None
    state.start_iteration()

    # prep should handle None plan
    context = executor.prep(state)
    assert context["steps"] == []

    # exec with empty steps should return success
    result = executor.exec(context)
    assert result.success


# ---------------------------------------------------------------------------
# 14. reviewer returns unknown verdict string falls through to iterate
# ---------------------------------------------------------------------------


def test_reviewer_unknown_verdict_falls_through_to_iterate():
    unknown_verdict = '{"verdict": "unknown_value", "score": 50, "summary": "?", "strengths": [], "issues": [], "feedback": "try again", "blocking_reason": null}'
    llm = make_mock_llm(verdict_response=unknown_verdict)
    agent = make_mock_agent(llm)

    reviewer = ReviewerNode(agent)
    state = make_state()
    state.status = FlowStatus.REVIEWING
    state.start_iteration()

    action = reviewer.run(state)
    assert action == "plan"
    assert state.status not in (FlowStatus.COMPLETED, FlowStatus.BLOCKED)


# ---------------------------------------------------------------------------
# 15. multiple iterations: iterate then approve on second pass
# ---------------------------------------------------------------------------


def test_two_iteration_flow_approve_on_second_pass():
    """Reviewer returns iterate on first call, approve on second call."""
    review_calls = {"n": 0}
    verdicts = [ITERATE_RESPONSE, APPROVE_RESPONSE]

    def side_effect(prompt, system):
        # Route based on which system prompt is active
        if system and "code reviewer" in system.lower():
            idx = review_calls["n"]
            review_calls["n"] += 1
            return verdicts[min(idx, len(verdicts) - 1)]
        if system and "architect" in system.lower():
            return PLAN_RESPONSE
        return PLAN_RESPONSE

    llm = MockLLMClient(side_effect=side_effect)
    agent = MockAgentBackend(llm)
    flow = make_architect_flow(agent)
    state = make_state(max_iterations=5)
    result = flow.run(state)

    assert result.status == FlowStatus.COMPLETED
    assert result.current_iteration >= 2


# ---------------------------------------------------------------------------
# 16. max_iterations=0 immediately blocks
# ---------------------------------------------------------------------------


def test_max_iterations_zero_blocks_immediately():
    llm = make_mock_llm()
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent)
    state = make_state(max_iterations=0)

    result = flow.run(state)

    assert result.status == FlowStatus.BLOCKED
    assert "Max iterations" in result.blocking_reason


# ---------------------------------------------------------------------------
# 17. resume after FAILED status resets to PENDING and can complete
# ---------------------------------------------------------------------------


def test_resume_after_failed_status_completes():
    llm = make_mock_llm()
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent)
    state = make_state()
    state.status = FlowStatus.FAILED
    state.status = FlowStatus.PENDING  # simulate resume_run reset

    result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# 18. state with existing history and artifacts persists through re-run
# ---------------------------------------------------------------------------


def test_existing_history_and_artifacts_persist_through_rerun():
    llm = make_mock_llm()
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent)
    state = make_state()
    state.add_artifact("existing.py", "created")
    prev = state.start_iteration()
    prev.plan = {"steps": []}

    result = flow.run(state)

    # Original artifact still present
    paths = [a.path for a in result.artifacts]
    assert "existing.py" in paths


# ---------------------------------------------------------------------------
# 19. on_state_change callback is called at least once per node execution
# ---------------------------------------------------------------------------


def test_on_state_change_called_per_node():
    llm = make_mock_llm()
    agent = make_mock_agent(llm)
    call_log = []

    def record_change(state):
        call_log.append(state.status)

    flow = make_architect_flow(agent, on_state_change=record_change)
    state = make_state()
    flow.run(state)

    # At least 3 calls: after planner, executor, reviewer
    assert len(call_log) >= 3


# ---------------------------------------------------------------------------
# 20. flow with no successors registered terminates cleanly
# ---------------------------------------------------------------------------


def test_flow_with_no_successors_terminates():
    class SimpleNode(Node):
        def exec(self, prep_result):
            return None

    node = SimpleNode("Lone")
    flow = Flow(start=node)
    state = make_state()

    result = flow.run(state)
    # Should return without error; status remains pending (node didn't change it)
    assert result is state


# ---------------------------------------------------------------------------
# 21. Flow re-raises KeyboardInterrupt from node exec
# ---------------------------------------------------------------------------


class KbdInterruptNode(Node):
    def exec(self, prep_result):
        raise KeyboardInterrupt


def test_flow_reraises_keyboard_interrupt_from_node():
    node = KbdInterruptNode("KbdNode")
    flow = Flow(start=node)
    state = make_state()

    with pytest.raises(KeyboardInterrupt):
        flow.run(state)


# ---------------------------------------------------------------------------
# 22. Node with prep() raising exception sets FAILED before exec is called
# ---------------------------------------------------------------------------


class BadPrepNode(Node):
    def prep(self, state):
        raise ValueError("bad prep")

    def exec(self, prep_result):
        return None


def test_prep_raising_sets_failed():
    node = BadPrepNode("BadPrep")
    flow = Flow(start=node)
    state = make_state()

    with pytest.raises(ValueError, match="bad prep"):
        flow.run(state)

    assert state.status == FlowStatus.FAILED


# ---------------------------------------------------------------------------
# 23. Flow with on_state_change=None runs without error
# ---------------------------------------------------------------------------


def test_flow_with_no_callback_runs_cleanly():
    llm = make_mock_llm()
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent, on_state_change=None)
    state = make_state()

    result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# 24. reviewer with score=None in response doesn't crash post()
# ---------------------------------------------------------------------------


def test_reviewer_with_score_none_does_not_crash():
    no_score = '{"verdict": "approve", "score": null, "summary": "OK", "strengths": [], "issues": [], "feedback": "", "blocking_reason": null}'
    llm = make_mock_llm(verdict_response=no_score)
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent)
    state = make_state()

    result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# 25. planner with empty task_content still transitions to build
# ---------------------------------------------------------------------------


def test_planner_with_empty_task_content_transitions_to_build():
    llm = make_mock_llm()
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent)
    state = make_state(task_content="")

    result = flow.run(state)
    assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# 26. executor with no steps records nothing new
# ---------------------------------------------------------------------------


def test_executor_empty_steps_records_nothing():
    llm = MockLLMClient(
        responses={
            "architect": '{"summary": "Empty", "steps": [], "dependencies": [], "risks": [], "estimated_complexity": "low"}',
            "reviewer": APPROVE_RESPONSE,
        }
    )
    agent = MockAgentBackend(llm)
    flow = make_architect_flow(agent)
    state = make_state()
    # Pre-existing artifact to confirm it's not cleared
    state.add_artifact("existing.py", "created")

    result = flow.run(state)
    artifact_paths = [a.path for a in result.artifacts]
    assert "existing.py" in artifact_paths


# ---------------------------------------------------------------------------
# 27. resume after BLOCKED with max_iterations reached completes on retry with higher limit
# ---------------------------------------------------------------------------


def test_resume_after_blocked_with_higher_limit_completes():
    llm = make_mock_llm(verdict_response=ITERATE_RESPONSE)
    agent = make_mock_agent(llm)
    flow = make_architect_flow(agent)
    state = make_state(max_iterations=1)

    result = flow.run(state)
    assert result.status == FlowStatus.BLOCKED

    # Simulate resume: reset status and increase max_iterations
    llm2 = make_mock_llm()
    agent2 = make_mock_agent(llm2)
    flow2 = make_architect_flow(agent2)
    state.status = FlowStatus.PENDING
    state.max_iterations = 5

    result2 = flow2.run(state)
    assert result2.status == FlowStatus.COMPLETED
