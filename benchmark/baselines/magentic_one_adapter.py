"""C0 baseline: upstream Microsoft AutoGen Magentic-One with GAS worker proxies.

The orchestration algorithm is **not** reimplemented here. It is imported from
``autogen_agentchat.teams.MagenticOneGroupChat``. See benchmark/baselines/README.md
for an upstream GitHub revision pin and provenance limitations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

from gas_server.core.llm_client import InfrastructureError
from gas_server.core.service_registry import get_service_registration

UPSTREAM_REVISION = "83afbf5857aac683340d4c692194e548b1e8edda"

logger = logging.getLogger(__name__)

GAS_WORKERS = (
    "data_retrieval_agent",
    "vector_analysis_a",
    "vector_analysis_b",
    "raster_analysis_agent",
    "projection_agent",
    "conversion_agent",
    "statistics_agent",
    "mapping_agent",
)


class MagenticOneC0Adapter:
    """Synchronous compatibility wrapper for benchmark.runner.execute_trajectory.

    Upstream Magentic-One runs the Task Ledger / Progress Ledger and routes
    turns to eight specialist AutoGen AssistantAgents. Their only tools call
    the same deterministic GAS worker service registrations as C1--C5.
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        if not os.getenv("OPENAI_API_KEY"):
            raise InfrastructureError("OPENAI_API_KEY is required for AutoGen Magentic-One.")

    @staticmethod
    def _model_client(model: str):
        # Import explicitly here, so missing upstream dependencies fail clearly.
        try:
            from autogen_ext.models.openai import OpenAIChatCompletionClient
        except ImportError as exc:
            raise InfrastructureError(
                "Microsoft AutoGen is not installed. See benchmark/baselines/README.md."
            ) from exc

        class CountedOpenAIClient(OpenAIChatCompletionClient):
            def __init__(self, **kwargs: Any):
                super().__init__(**kwargs)
                self.number_of_calls = 0

            async def create(self, *args: Any, **kwargs: Any):
                self.number_of_calls += 1
                return await super().create(*args, **kwargs)

            async def create_stream(self, *args: Any, **kwargs: Any):
                self.number_of_calls += 1
                async for item in super().create_stream(*args, **kwargs):
                    yield item

        settings: dict[str, Any] = {"model": model, "parallel_tool_calls": False}
        try:
            return CountedOpenAIClient(**settings)
        except ValueError as exc:
            # For OpenAI-compatible model IDs unknown to the pinned AutoGen
            # package; does not imply the upstream API actually serves them.
            if "model_info" not in str(exc).lower() and "unknown model" not in str(exc).lower():
                raise
            from autogen_core.models import ModelFamily

            return CountedOpenAIClient(
                **settings,
                model_info={
                    "vision": False,
                    "function_calling": True,
                    "json_output": True,
                    "family": ModelFamily.UNKNOWN,
                    "structured_output": True,
                },
            )

    async def _run_async(
        self, query: str, initial_paths: list[str], max_rounds: int
    ) -> dict[str, Any]:
        try:
            from autogen_agentchat.agents import AssistantAgent
            from autogen_agentchat.teams import MagenticOneGroupChat
        except ImportError as exc:
            raise InfrastructureError("AutoGen MagenticOneGroupChat is unavailable.") from exc

        model_client = self._model_client(self.model)
        known_paths: list[str] = [str(Path(p).resolve(strict=True)) for p in initial_paths]
        produced_paths: list[str] = []
        steps: list[dict[str, Any]] = []
        guard = Lock()
        worker_seconds = 0.0

        def tool_factory(service_id: str):
            async def run_gas_worker(
                instructions: str,
                parameters_json: str = "{}",
                input_artifacts_json: str = "[]",
            ) -> str:
                """Run this specialist's registered GAS service; arguments are JSON text."""
                nonlocal worker_seconds
                try:
                    params = json.loads(parameters_json)
                    selected = json.loads(input_artifacts_json)
                    if not isinstance(params, dict) or not isinstance(selected, list):
                        raise ValueError("parameters_json must be an object; input_artifacts_json must be a list")
                    with guard:
                        allowlist = set(known_paths)
                        if selected:
                            paths = [str(Path(p).resolve(strict=True)) for p in selected]
                            if not set(paths).issubset(allowlist):
                                raise ValueError("Only previously supplied or produced artifact paths are permitted")
                        else:
                            paths = list(known_paths)
                except (ValueError, TypeError, OSError) as exc:
                    return json.dumps({"error": "INVALID_TOOL_ARGUMENTS", "message": str(exc)})

                def execute() -> dict[str, Any]:
                    registration = get_service_registration(service_id)
                    worker = registration.build_agent()
                    return worker.run_service(
                        query=instructions,
                        input_dataset_paths=paths,
                        parameters=params,
                    )

                tick = time.monotonic()
                try:
                    result = await asyncio.to_thread(execute)
                except InfrastructureError:
                    raise
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                elapsed = time.monotonic() - tick
                artifacts = result.get("artifacts") or []
                if isinstance(artifacts, str):
                    artifacts = [artifacts]
                if not isinstance(artifacts, list):
                    artifacts = []
                safe_paths = [str(Path(p).resolve()) for p in artifacts if isinstance(p, str)]
                with guard:
                    worker_seconds += elapsed
                    for path in safe_paths:
                        if path not in known_paths:
                            known_paths.append(path)
                        if path not in produced_paths:
                            produced_paths.append(path)
                    steps.append(
                        {
                            "step_index": len(steps) + 1,
                            "agent_id": service_id,
                            "instruction": instructions[:200],
                            "parameters": params,
                            "artifacts_produced": safe_paths,
                            "error": result.get("error"),
                            "duration_seconds": round(elapsed, 3),
                        }
                    )
                return json.dumps(
                    {"service": service_id, "summary": result.get("summary"),
                     "artifacts": safe_paths, "error": result.get("error"),
                     "available_artifacts": list(known_paths)}, default=str
                )

            return run_gas_worker

        team_members = []
        for service_id in GAS_WORKERS:
            team_members.append(
                AssistantAgent(
                    name=service_id,
                    description=f"GAS deterministic geospatial specialist {service_id}; calls its own registered service.",
                    model_client=model_client,
                    tools=[tool_factory(service_id)],
                    system_message=(
                        f"You are the {service_id} specialist in a Magentic-One team. "
                        "Use the run_gas_worker tool for your delegated geospatial operation. "
                        "Pass specific instructions and optional parameters_json as a JSON object string. "
                        "The input_artifacts_json argument is an optional JSON array of exact known artifact paths; "
                        "omit it to forward all currently known artifacts. "
                        "Report actual tool outputs; do not invent artifacts or call other workers."
                    ),
                    reflect_on_tool_use=True,
                )
            )

        team = MagenticOneGroupChat(
            participants=team_members,
            model_client=model_client,
            max_turns=max_rounds,
            max_stalls=3,
        )
        prompt = (
            f"Task: {query}\n"
            "Available input artifacts (absolute paths):\n"
            + json.dumps(known_paths, indent=2)
            + "\nUse the specialist GAS worker agents to carry out the requested workflow. "
            "They can pass artifact paths to later workers. "
            "Do not treat a tool summary alone as proof of task completion."
        )
        started = time.monotonic()
        try:
            outcome = await team.run(task=prompt)
            elapsed = time.monotonic() - started
            usage = model_client.actual_usage()
            final_message = outcome.messages[-1] if outcome.messages else None
            summary = str(getattr(final_message, "content", "") or "")
            stop_reason = outcome.stop_reason or ""
            limited = "maximum number of turns" in stop_reason.lower()
            # Preserve the runner's existing return contract. Final scoring is
            # independently determined by the benchmark oracle.
            succeeded = bool(produced_paths) and not limited and not (
                steps and steps[-1].get("error")
            )
            return {
                "status": "successful" if succeeded else "failed",
                "duration_seconds": round(elapsed, 3),
                "worker_execution_time": round(worker_seconds, 3),
                # Upstream AutoGen owns API calls; these subcomponents cannot
                # be separated without instrumenting its own HTTP client.
                "rate_limit_wait_time": 0.0,
                "provider_retry_wait_time": 0.0,
                "orchestration_active_time": round(max(0.0, elapsed - worker_seconds), 3),
                "model_calls": model_client.number_of_calls,
                "input_tokens": int(usage.prompt_tokens),
                "output_tokens": int(usage.completion_tokens),
                "total_tokens": int(usage.prompt_tokens + usage.completion_tokens),
                "baseline_implementation": "microsoft/autogen:MagenticOneGroupChat",
                "upstream_revision": UPSTREAM_REVISION,
                "stop_reason": stop_reason,
                "outputs": {
                    "summary": summary,
                    "upstream_revision": UPSTREAM_REVISION,
                    "baseline_implementation": "microsoft/autogen:MagenticOneGroupChat",
                    "artifacts": list(produced_paths),
                    "produced_artifacts": list(produced_paths),
                    "workflow_steps": list(steps),
                },
                "steps_executed": list(steps),
            }
        finally:
            await model_client.close()

    def run(
        self,
        query: str,
        input_dataset_paths: list[str] | None = None,
        max_rounds: int = 10,
    ) -> dict[str, Any]:
        """Invoke the genuine AutoGen team, preserving the synchronous C0 API."""
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        return asyncio.run(
            self._run_async(query, list(input_dataset_paths or []), max_rounds)
        )
