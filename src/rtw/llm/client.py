"""LLM client abstraction for rtw.

Default backend: Cursor Agent CLI (cursor agent -p).
"""

import json
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract base for LLM backends."""

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """Generate a completion for the given prompt."""
        pass

    @abstractmethod
    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        """Generate a JSON-structured completion."""
        pass


class CursorAgentClient(LLMClient):
    """
    LLM client that uses Cursor Agent CLI in non-interactive mode.

    Uses `cursor agent -p` with --output-format json for structured responses.
    Requires cursor CLI to be installed and authenticated.
    """

    def __init__(
        self,
        workspace: str | Path,
        model: str = "sonnet-4.6",
        force: bool = True,
        trust: bool = True,
    ):
        self.workspace = Path(workspace)
        self.model = model
        self.force = force
        self.trust = trust
        self._cursor_path = self._find_cursor()

    def _find_cursor(self) -> str:
        """Find cursor CLI executable."""
        candidates = [
            "cursor",  # In PATH
            "/usr/local/bin/cursor",
            "/opt/homebrew/bin/cursor",
            os.path.expanduser("~/.cursor/bin/cursor"),
        ]

        for candidate in candidates:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    logger.debug(f"Found cursor CLI at: {candidate}")
                    return candidate
            except (subprocess.SubprocessError, FileNotFoundError):
                continue

        return "cursor"

    def complete(self, prompt: str, system: str | None = None) -> str:
        """
        Run cursor agent with prompt and return text response.

        Uses non-interactive mode (-p) with text output format.
        """
        full_prompt = self._build_prompt(prompt, system)

        cmd = [
            self._cursor_path,
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

        logger.info(f"Invoking cursor agent (model: {self.model})")
        logger.debug(f"Prompt length: {len(full_prompt)} chars")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(self.workspace),
            )

            if result.returncode != 0:
                logger.error(f"Cursor agent failed: {result.stderr}")
                raise RuntimeError(f"Cursor agent error: {result.stderr}")

            response = result.stdout.strip()
            logger.debug(f"Response length: {len(response)} chars")
            return response

        except subprocess.TimeoutExpired as e:
            logger.error("Cursor agent timed out")
            raise RuntimeError("Cursor agent timed out after 5 minutes") from e
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
            self._cursor_path,
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

        logger.info(f"Invoking cursor agent for JSON (model: {self.model})")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(self.workspace),
            )

            if result.returncode != 0:
                logger.error(f"Cursor agent failed: {result.stderr}")
                return {"error": f"Cursor agent error: {result.stderr}"}

            try:
                wrapper = json.loads(result.stdout)

                if wrapper.get("is_error"):
                    return {"error": wrapper.get("result", "Unknown error")}

                response_text = wrapper.get("result", "")
                return self._extract_json(response_text)

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse cursor wrapper JSON: {e}")
                return self._extract_json(result.stdout)

        except subprocess.TimeoutExpired:
            return {"error": "Cursor agent timed out"}
        except FileNotFoundError:
            return {"error": "Cursor CLI not found"}

    def _build_prompt(self, prompt: str, system: str | None) -> str:
        """Build full prompt with optional system context."""
        parts = []
        if system:
            parts.append(f"<system>\n{system}\n</system>\n")
        parts.append(prompt)
        return "\n".join(parts)

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from text, handling markdown code blocks."""
        text = text.strip()

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
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Raw text: {text[:500]}")
            return {"error": "Failed to parse JSON response", "raw": text[:500]}


class MockLLMClient(LLMClient):
    """Mock client for testing the flow without LLM calls."""

    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {}
        self.call_count = 0

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.call_count += 1

        if system:
            for key, response in self.responses.items():
                if key.lower() in system.lower():
                    return response

        for key, response in self.responses.items():
            if key.lower() in prompt.lower():
                return response

        return f"Mock response #{self.call_count}"

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        response = self.complete(prompt, system)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"mock": True, "response": response}
