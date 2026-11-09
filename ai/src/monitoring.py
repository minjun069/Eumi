"""Langfuse를 통한 Agent 실행 관측을 담당한다."""

import asyncio
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse, LangfuseAgent, propagate_attributes
from langfuse.langchain import CallbackHandler
from langfuse.types import MaskOtelSpansParams, MaskOtelSpansResult, OtelSpanPatch
from langgraph.errors import GraphBubbleUp

from src.settings import Settings
from src.state import Execution, State

logger = logging.getLogger(__name__)


def _safe_error(error: BaseException) -> BaseException:
    # OTel status.description is outside mask_otel_spans' attribute contract.
    # Preserve LangGraph control flow classification, but remove payload text
    # before the SDK copies the exception into the OTel status.
    kind = GraphBubbleUp if isinstance(error, GraphBubbleUp) else RuntimeError
    return kind(type(error).__name__)


class _OperationalCallbackHandler(CallbackHandler):
    def on_chain_error(self, error: BaseException, **kwargs):
        return super().on_chain_error(_safe_error(error), **kwargs)

    def on_llm_error(self, error: BaseException, **kwargs):
        return super().on_llm_error(_safe_error(error), **kwargs)

    def on_tool_error(self, error: BaseException, **kwargs):
        return super().on_tool_error(_safe_error(error), **kwargs)

    def on_retriever_error(self, error: BaseException, **kwargs):
        return super().on_retriever_error(_safe_error(error), **kwargs)


# Only operational fields are exported. State, prompts, tool arguments and error
# messages can contain user data. Token/cost details remain available for models.
_ATTRIBUTES = {
    "session.id",
    "langfuse.trace.name",
    "langfuse.trace.tags",
    "langfuse.observation.type",
    "langfuse.observation.level",
    "langfuse.observation.model.name",
    "langfuse.observation.usage_details",
    "langfuse.observation.cost_details",
    "langfuse.observation.completion_start_time",
    "langfuse.environment",
    "langfuse.release",
    "langfuse.version",
    "langfuse.internal.as_root",
    "langfuse.internal.is_app_root",
}
_METADATA = {
    "run_id",
    "version",
    "phase",
    "status",
    "response_kind",
    "result_count",
    "failure_count",
    "artifact_count",
    "exception_type",
    "error_code",
}


def mask_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
    """Remove payload attributes, retaining identifiers and operational metrics."""
    allowed = _ATTRIBUTES | {
        f"langfuse.{scope}.metadata.{key}"
        for scope in ("trace", "observation")
        for key in _METADATA
    }
    return MaskOtelSpansResult(
        span_patches={
            identifier: OtelSpanPatch(
                delete_attributes=tuple(
                    key for key in span.attributes if key not in allowed
                )
            )
            for identifier, span in params.spans.items()
        }
    )


def create_monitoring(settings: Settings) -> Langfuse | None:
    """Initialize once at process startup; disabled mode creates no SDK client."""
    if not settings.langfuse_enabled:
        return None
    try:
        # SDK media processing precedes export masking. Disable its separate
        # upload path as this integration exports operational metrics only.
        os.environ["LANGFUSE_MEDIA_UPLOAD_ENABLED"] = "false"
        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=str(settings.langfuse_base_url),
            environment=settings.langfuse_environment,
            sample_rate=settings.langfuse_sample_rate,
            timeout=5,
            mask_otel_spans=mask_spans,
            should_export_span=lambda span: (
                span.instrumentation_scope is not None
                and span.instrumentation_scope.name == "langfuse"
            ),
        )
    except Exception as error:
        logger.warning("Langfuse initialization failed (%s)", type(error).__name__)
        return None


def _update(observation: LangfuseAgent | None, **kwargs) -> None:
    if observation is None:
        return
    try:
        observation.update(**kwargs)
    except Exception as error:
        logger.warning("Langfuse update failed (%s)", type(error).__name__)


@contextmanager
def trace_execution(
    client: Langfuse | None,
    execution: Execution,
    *,
    phase: Literal["start", "resume"] = "start",
) -> Iterator[tuple[RunnableConfig, LangfuseAgent | None]]:
    """Supply standard graph config and an observation without changing State.

    The root is ended when the invocation returns (including waiting_input), so
    human waiting time is excluded from segment latency. No graph retry is made
    when instrumentation fails.
    """
    run_id = execution["run_id"]
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}
    observation = None
    if client is not None:
        try:
            trace_id = Langfuse.create_trace_id(seed=run_id)
            with propagate_attributes(session_id=run_id, tags=["eumi", phase]):
                observation = client.start_observation(
                    name=f"eumi.agent.{phase}",
                    as_type="agent",
                    trace_context={"trace_id": trace_id},
                    version=execution["version"],
                    metadata={
                        "run_id": run_id,
                        "version": execution["version"],
                        "phase": phase,
                    },
                )
            config.update(
                run_name="eumi.graph",
                callbacks=[
                    _OperationalCallbackHandler(
                        trace_context={
                            "trace_id": trace_id,
                            "parent_span_id": observation.id,
                        },
                    )
                ],
                metadata={"langfuse_session_id": run_id},
                tags=["eumi", phase],
            )
        except Exception as error:
            logger.warning("Langfuse trace setup failed (%s)", type(error).__name__)
    try:
        yield config, observation
    except asyncio.CancelledError:
        _update(observation, level="WARNING", metadata={"status": "cancelled"})
        raise
    except Exception as error:
        _update(
            observation,
            level="ERROR",
            metadata={
                "status": "failed",
                "exception_type": type(error).__name__,
            },
        )
        raise
    finally:
        if observation is not None:
            try:
                observation.end()
            except Exception as error:
                logger.warning("Langfuse span end failed (%s)", type(error).__name__)


def record_execution(observation: LangfuseAgent | None, state: State) -> None:
    """Record reported outcome, not an evaluation of answer quality.

    Counts are State snapshot totals. Resume snapshots must not be summed together.
    """
    status = state["execution"]["status"]
    response = state["response"]
    error = state["execution"]["error"]
    _update(
        observation,
        level="ERROR"
        if status == "failed"
        else ("WARNING" if status in {"partial", "cancelled"} else "DEFAULT"),
        metadata={
            "status": status,
            "error_code": error["code"] if error else None,
            "response_kind": response["kind"] if response else None,
            "result_count": len(state["results"]),
            "failure_count": sum(r["outcome"] == "failure" for r in state["results"]),
            "artifact_count": len(response["artifacts"]) if response else 0,
        },
    )


async def shutdown_monitoring(client: Langfuse | None) -> None:
    """Drain queued telemetry off the event loop at process shutdown."""
    if client is None:
        return
    try:
        await asyncio.to_thread(client.shutdown)
    except Exception as error:
        logger.warning("Langfuse shutdown failed (%s)", type(error).__name__)
