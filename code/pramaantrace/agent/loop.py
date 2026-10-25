"""Bounded tool-calling loop for read-only evidence investigation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .client import LLMClientError
from .tools import CaseToolbox, ToolObservation, TOOL_NAMES


PROMPT_VERSION = "investigator-v1"
MAX_TOOL_CALLS_PER_TURN = 8
MAX_CANDIDATES = 50
SYSTEM_PROMPT = (
    Path(__file__).resolve().parents[2] / "prompts" / "investigator_system.txt"
).read_text(encoding="utf-8")


class InvestigatorError(RuntimeError):
    """Raised when the model response cannot safely drive the investigation."""


class TurnCapExceeded(InvestigatorError):
    """Raised when the completion budget ends before the model returns a final answer."""


@dataclass(frozen=True)
class CandidateLink:
    resource_id: str
    capture_id: str
    observation_id: str


@dataclass(frozen=True)
class InvestigationResult:
    candidates: tuple[CandidateLink, ...]
    observations: tuple[ToolObservation, ...]
    turns: int


class Investigator:
    def __init__(self, client: Any, step_cap: int = 8) -> None:
        if not isinstance(step_cap, int) or isinstance(step_cap, bool) or not 1 <= step_cap <= 64:
            raise ValueError("step_cap must be an integer from 1 to 64")
        self.client = client
        self.step_cap = step_cap

    def investigate(
        self,
        request: Mapping[str, Any],
        toolbox: CaseToolbox,
    ) -> InvestigationResult:
        initial_observation_count = len(toolbox.observations)
        identity = toolbox.identity
        subject = {
            "user_id": identity.user_id,
            "emails": list(identity.emails),
            "email_hashes": list(identity.email_hashes),
            "phones": list(identity.phones),
            "customer_references": list(identity.customer_references),
        }
        user_message = json.dumps(
            {
                "audit_at": str(request["audit_at"]),
                "resolved_subject_identifiers": subject,
                "task": (
                    "Search for participant-visible records linked to this subject. "
                    "Return only candidate resource links grounded in your tool observations."
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        tools = toolbox.schemas()
        allowed_names = {schema["function"]["name"] for schema in tools}
        if not allowed_names.issubset(TOOL_NAMES):
            raise InvestigatorError("toolbox exposed an undeclared tool")

        turns = 0
        while turns < self.step_cap:
            try:
                completion = self.client.complete(messages, tools)
            except LLMClientError:
                raise InvestigatorError("model completion failed") from None
            turns += 1
            message = getattr(completion, "message", None)
            finish_reason = getattr(completion, "finish_reason", None)
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise InvestigatorError("model completion has an invalid assistant message")

            tool_calls = message.get("tool_calls")
            if tool_calls is not None:
                if not isinstance(tool_calls, list) or not tool_calls:
                    raise InvestigatorError("model completion contains malformed tool calls")
                if len(tool_calls) > MAX_TOOL_CALLS_PER_TURN:
                    raise InvestigatorError("model completion exceeded the per-turn tool-call limit")
                tool_messages = self._dispatch_tool_calls(tool_calls, toolbox)
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.get("content"),
                        "tool_calls": tool_calls,
                    }
                )
                messages.extend(tool_messages)
                if turns >= self.step_cap:
                    raise TurnCapExceeded("agent completion cap reached before a final answer")
                continue

            if finish_reason != "stop":
                raise InvestigatorError("model completion did not end with a final response")
            content = message.get("content")
            candidates = self._parse_candidates(content)
            observations = toolbox.observations[initial_observation_count:]
            return InvestigationResult(
                candidates=candidates,
                observations=observations,
                turns=turns,
            )

        raise TurnCapExceeded("agent completion cap reached")

    @staticmethod
    def _dispatch_tool_calls(
        calls: list[Any], toolbox: CaseToolbox
    ) -> list[dict[str, str]]:
        messages = []
        for call in calls:
            if not isinstance(call, dict) or call.get("type") != "function":
                raise InvestigatorError("model returned an invalid tool-call envelope")
            call_id = call.get("id")
            function = call.get("function")
            if not isinstance(call_id, str) or not call_id or not isinstance(function, dict):
                raise InvestigatorError("model returned an invalid tool-call envelope")
            name = function.get("name")
            raw_arguments = function.get("arguments")
            if not isinstance(name, str) or name not in TOOL_NAMES:
                raise InvestigatorError("model requested an undeclared tool")
            if not isinstance(raw_arguments, str):
                raise InvestigatorError("model returned malformed tool arguments")
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
                observation = toolbox.observe(name, arguments)
            except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                raise InvestigatorError("model returned invalid tool arguments") from None
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(
                        {
                            "observation_id": observation.observation_id,
                            "result": observation.result,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                }
            )
        return messages

    @staticmethod
    def _parse_candidates(content: Any) -> tuple[CandidateLink, ...]:
        if not isinstance(content, str) or not content.strip():
            raise InvestigatorError("model final response is empty or not text")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            raise InvestigatorError("model final response is not valid JSON") from None
        if not isinstance(payload, dict) or set(payload) != {"candidates"}:
            raise InvestigatorError("model final response does not match the candidate schema")
        raw_candidates = payload["candidates"]
        if not isinstance(raw_candidates, list) or len(raw_candidates) > MAX_CANDIDATES:
            raise InvestigatorError("model final candidates must be a bounded array")

        candidates: list[CandidateLink] = []
        seen: set[tuple[str, str, str]] = set()
        for item in raw_candidates:
            if not isinstance(item, dict) or set(item) != {
                "resource_id",
                "capture_id",
                "observation_id",
            }:
                raise InvestigatorError("model candidate does not match the candidate schema")
            values = (item["resource_id"], item["capture_id"], item["observation_id"])
            if any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in values):
                raise InvestigatorError("model candidate contains an invalid identifier")
            key = tuple(value.strip() for value in values)
            if key not in seen:
                candidates.append(CandidateLink(*key))
                seen.add(key)
        return tuple(candidates)
