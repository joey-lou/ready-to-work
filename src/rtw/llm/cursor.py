"""Cursor Agent CLI backend for rtw (cursor agent -p)."""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from .client import LLMClient, LLMResponseError

logger = logging.getLogger(__name__)

# Keep in sync with cursor CLI available models; set RTW_SKIP_MODEL_VALIDATION=1 if stale
KNOWN_MODELS = frozenset(
    {
        "auto",
        "composer-1.5",
        "composer-1",
        "gpt-5.3-codex",
        "gpt-5.3-codex-low",
        "gpt-5.3-codex-high",
        "gpt-5.3-codex-xhigh",
        "gpt-5.3-codex-fast",
        "gpt-5.3-codex-low-fast",
        "gpt-5.3-codex-high-fast",
        "gpt-5.3-codex-xhigh-fast",
        "gpt-5.2",
        "gpt-5.2-codex",
        "gpt-5.2-codex-high",
        "gpt-5.2-codex-low",
        "gpt-5.2-codex-xhigh",
        "gpt-5.2-codex-fast",
        "gpt-5.2-codex-high-fast",
        "gpt-5.2-codex-low-fast",
        "gpt-5.2-codex-xhigh-fast",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex-max-high",
        "opus-4.6-thinking",
        "gpt-5.2-high",
        "opus-4.6",
        "opus-4.5",
        "opus-4.5-thinking",
        "sonnet-4.6",
        "sonnet-4.6-thinking",
        "sonnet-4.5",
        "sonnet-4.5-thinking",
        "gpt-5.1-high",
        "gemini-3.1-pro",
        "gemini-3-pro",
        "gemini-3-flash",
        "gpt-5.1-codex-mini",
        "grok",
    }
)


class CursorAgentClient(LLMClient):
    """
    LLM client that uses Cursor Agent CLI in non-interactive mode.

    Uses `cursor agent -p` with --output-format json for structured responses.
    Requires cursor CLI to be installed and authenticated.
    """

    DEFAULT_AGENT_TIMEOUT = 1800

    def __init__(
        self,
        workspace: str | Path,
        model: str = "sonnet-4.6",
        force: bool = True,
        trust: bool = True,
        timeout: int | None = None,
    ):
        self.workspace = Path(workspace)
        self.model = model
        self.force = force
        self.trust = trust
        self.timeout = timeout or int(
            os.environ.get("RTW_AGENT_TIMEOUT", self.DEFAULT_AGENT_TIMEOUT)
        )

    def complete(self, prompt: str, system: str | None = None) -> str:
        """
        Run cursor agent with prompt and return text response.

        Uses non-interactive mode (-p) with text output format.
        """
        full_prompt = self._build_prompt(prompt, system)

        cmd = [
            "cursor",
            "agent",
            "-p",
            "--output-format",
            "text",
            "--model",
            self.model,
            "--workspace",
            str(self.workspace),
        ]

        if self.force:
            cmd.append("--force")
        if self.trust:
            cmd.append("--trust")

        cmd.append(full_prompt)

        logger.info("Invoking cursor agent (model: %s)", self.model)
        logger.debug("Prompt length: %d chars", len(full_prompt))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.workspace),
            )

            if result.returncode != 0:
                logger.error("Cursor agent failed: %s", result.stderr)
                raise RuntimeError(f"Cursor agent error: {result.stderr}")

            response = result.stdout.strip()
            logger.debug("Response length: %d chars", len(response))
            return response

        except subprocess.TimeoutExpired as e:
            logger.error("Cursor agent timed out")
            raise RuntimeError(f"Cursor agent timed out after {self.timeout}s") from e
        except FileNotFoundError as e:
            logger.error("Cursor CLI not found. Install from https://cursor.com")
            raise RuntimeError("Cursor CLI not found") from e

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        """
        Run cursor agent and parse JSON response.

        Uses json output format for structured parsing.
        """
        json_prompt = f"""{prompt}

IMPORTANT: Respond with valid JSON only. No markdown code blocks, no explanation, just raw JSON."""

        full_prompt = self._build_prompt(json_prompt, system)

        cmd = [
            "cursor",
            "agent",
            "-p",
            "--output-format",
            "json",
            "--model",
            self.model,
            "--workspace",
            str(self.workspace),
        ]

        if self.force:
            cmd.append("--force")
        if self.trust:
            cmd.append("--trust")

        cmd.append(full_prompt)

        logger.info("Invoking cursor agent for JSON (model: %s)", self.model)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.workspace),
            )

            if result.returncode != 0:
                logger.error("Cursor agent failed: %s", result.stderr)
                raise LLMResponseError(
                    f"Cursor agent error: {result.stderr}", raw=result.stderr or ""
                )

            stdout = result.stdout
            if stdout is None or (stdout or "").strip() == "":
                logger.error(
                    "Empty response from cursor agent (stderr: %s)",
                    (result.stderr or "")[:200],
                )
                raise LLMResponseError(
                    "Empty response from cursor agent",
                    raw=(result.stderr or "")[:500],
                )

            try:
                wrapper = json.loads(stdout)

                if wrapper.get("is_error"):
                    raise LLMResponseError(
                        wrapper.get("result", "Unknown error from cursor agent"),
                        raw=stdout,
                    )

                response_text = wrapper.get("result", "")
                return self._extract_json(response_text)

            except json.JSONDecodeError as e:
                logger.warning("Failed to parse cursor wrapper JSON: %s", e)
                return self._extract_json(stdout)

        except subprocess.TimeoutExpired as e:
            raise LLMResponseError(f"Cursor agent timed out after {self.timeout}s", raw="") from e
        except FileNotFoundError as e:
            raise LLMResponseError("Cursor CLI not found", raw="") from e

    def _build_prompt(self, prompt: str, system: str | None) -> str:
        """Build full prompt with optional system context."""
        parts = []
        if system:
            parts.append(f"<system>\n{system}\n</system>\n")
        parts.append(prompt)
        return "\n".join(parts)

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from text, handling markdown code blocks and leading/trailing prose."""
        if not text or not text.strip():
            raise LLMResponseError("Empty response from cursor agent", raw="")

        text = text.strip()

        logger.debug(
            "Extracting JSON: total length=%d, first200=%r, last200=%r",
            len(text),
            text[:200],
            text[-200:],
        )

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            brace_slice = text[first : last + 1]
            try:
                return json.loads(brace_slice)
            except json.JSONDecodeError:
                logger.warning(
                    "Brace-slice extraction failed; trying depth-counting scan. Raw preview: %r…%r",
                    text[:200],
                    text[-200:],
                )
                result = self._scan_largest_json_object(text)
                if result is not None:
                    return result

        logger.error("Failed to parse JSON from response")
        raise LLMResponseError("Failed to parse JSON response", raw=text[:500])

    @staticmethod
    def _scan_largest_json_object(text: str) -> dict[str, Any] | None:
        """
        Find the largest well-formed JSON object in *text* using depth-counting.

        Iterates over every '{' as a candidate start and attempts to parse the
        substring ending at the matching '}'. Returns the first successful parse
        (leftmost / largest object) or None if nothing succeeds.
        """
        for start in range(len(text)):
            if text[start] != "{":
                continue
            depth = 0
            in_string = False
            escape_next = False
            for i, ch in enumerate(text[start:], start=start):
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\" and in_string:
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : i + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break
        return None
