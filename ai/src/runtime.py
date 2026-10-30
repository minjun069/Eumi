"""Local graph/task handles; all run data is held in the execution State."""

import asyncio
from copy import deepcopy
from time import monotonic

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.graph import compile_graph
from src.settings import Settings
from src.state import Request, State, create_state

TERMINAL = {"completed", "partial", "failed", "cancelled"}


class AgentRuntime:
    def __init__(self, agents: dict, settings: Settings):
        self.settings = settings.model_copy(deep=True, update={"api_key": None})
        self.graphs = {
            name: compile_graph(agent, checkpointer=InMemorySaver())
            for name, agent in agents.items()
        }
        self.runs: dict[str, State] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    @staticmethod
    def config(state):
        return {
            "configurable": {"thread_id": state["run_id"]},
            "recursion_limit": state["settings"]["max_steps"] * 8
            + state["settings"]["max_tool_retries"] * 2
            + 20,
        }

    async def start(
        self,
        agent: str,
        request: Request,
        *,
        instruction_version: str,
        info: dict | None = None,
        data_versions: dict[str, str] | None = None,
    ):
        if agent not in self.graphs:
            raise KeyError(agent)
        state = create_state(
            request,
            self.settings,
            agent=agent,
            instruction_version=instruction_version,
            info=info,
            data_versions=data_versions,
        )
        self.runs[state["run_id"]] = state
        return await self._drive(state, state.copy())

    def get(self, run_id: str) -> dict:
        state = self.runs[run_id]
        result = state["result"] or {}
        response = {
            "content": result.get("content", ""),
            "references": result.get("references", []),
        }
        if state["pending"]:
            response = {"content": state["pending"]["question"], "references": []}
        elif state["error"]:
            response = {"content": state["error"]["cause"], "references": []}
        return deepcopy(
            {
                "request": state["request"],
                "info": state["info"],
                "messages": state["public_messages"],
                "results": state["results"],
                "response": response,
                "execution": {
                    "run_id": run_id,
                    "status": state["status"],
                    "input_version": state["input_version"],
                    "data_versions": state["data_versions"],
                    "instruction_version": state["instruction_version"],
                    "pending": state["pending"],
                    "attempts": state["usage"],
                    "error": state["error"],
                },
            }
        )

    async def resume(
        self,
        run_id: str,
        *,
        pending_id: str,
        expected_input_version: int,
        content: str,
        data_versions: dict[str, str],
    ):
        state = self.runs[run_id]
        if (
            run_id in self.tasks
            or state["status"] != "waiting_input"
            or state["cancel_requested"]
        ):
            raise ValueError("Run is not waiting for input")
        if (
            pending_id != state["pending"]["id"]
            or expected_input_version != state["input_version"]
        ):
            raise ValueError("Stale question or input version")
        if data_versions != state["data_versions"]:
            raise ValueError("Data versions changed; start a new run")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("A non-empty answer is required")
        state["input_version"] += 1
        state["public_messages"] = [
            *state["public_messages"],
            {"role": "user", "content": content},
        ]
        state["pending"] = None
        return await self._drive(
            state,
            Command(
                resume=content,
                update={
                    "input_version": state["input_version"],
                    "public_messages": state["public_messages"],
                    "pending": None,
                    "status": "running",
                },
            ),
        )

    async def cancel(self, run_id: str):
        state = self.runs[run_id]
        if state["status"] in TERMINAL:
            return self.get(run_id)
        first = not state["cancel_requested"]
        state["cancel_requested"] = True
        if run_id in self.tasks:
            active = self.tasks[run_id]
            if first:
                active.cancel()
            await asyncio.shield(active)
        else:
            self._stop(
                state,
                "cancelled",
                "cancelled",
                "Execution cancelled; prior effects remain.",
            )
            self._save(state)
        return self.get(run_id)

    @staticmethod
    def _stop(state, status, code, cause):
        state["status"] = status
        state["error"] = {"code": code, "cause": cause, "retryable": False}
        state["pending"] = None

    def _save(self, state):
        # Persist lifecycle fields after streaming pauses or finishes.
        self.graphs[state["agent"]].update_state(
            self.config(state),
            {
                key: state[key]
                for key in (
                    "status",
                    "error",
                    "pending",
                    "cancel_requested",
                    "usage",
                    "input_version",
                    "public_messages",
                )
            },
        )

    async def _drive(self, state, value):
        run_id = state["run_id"]
        self.tasks[run_id] = asyncio.current_task()
        state["status"] = "running"
        if isinstance(value, dict):
            value["status"] = "running"
        graph = self.graphs[state["agent"]]
        config = self.config(state)
        started = monotonic()
        external_cancel = False
        try:
            remaining = (
                state["settings"]["runtime_timeout"] - state["usage"]["active_seconds"]
            )
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                async for snapshot in graph.astream(
                    value, config, stream_mode="values"
                ):
                    if "__interrupt__" not in snapshot:
                        cancel_requested = state["cancel_requested"]
                        state.update(snapshot)
                        state["cancel_requested"] = cancel_requested
            saved = graph.get_state(config)
            if saved.interrupts:
                item = saved.interrupts[0]
                state["status"] = "waiting_input"
                state["pending"] = {"id": item.id, "question": item.value["question"]}
                state["public_messages"] = [
                    *state["public_messages"],
                    {"role": "assistant", "content": item.value["question"]},
                ]
            elif state["error"]:
                state["status"] = (
                    "partial" if state["error"]["code"].endswith("_limit") else "failed"
                )
            else:
                result = state["result"]
                state["status"] = "partial" if result["partial"] else "completed"
                state["public_messages"] = [
                    *state["public_messages"],
                    {"role": "assistant", "content": result["content"]},
                ]
        except TimeoutError:
            self._stop(
                state, "partial", "time_limit", "Active execution time limit reached."
            )
        except asyncio.CancelledError:
            external_cancel = not state["cancel_requested"]
            self._stop(
                state,
                "cancelled",
                "cancelled",
                "Execution cancelled; prior effects remain.",
            )
        except Exception as exc:
            self._stop(
                state,
                "failed",
                "runtime_error",
                f"Execution failed ({type(exc).__name__}).",
            )
        finally:
            state["usage"] = state["usage"] | {
                "active_seconds": state["usage"]["active_seconds"]
                + monotonic()
                - started
            }
            self.tasks.pop(run_id, None)
            self._save(state)
        if external_cancel:
            raise asyncio.CancelledError
        return self.get(run_id)
