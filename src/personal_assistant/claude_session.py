"""Wrapper sobre la CLI de Claude Code con sesión persistente y rotación por contexto."""
import asyncio
import json
import logging
import uuid
from typing import Optional

from .config import ClaudeConfig
from .memory import Memory

log = logging.getLogger(__name__)


class ClaudeSession:
    def __init__(
        self,
        cfg: ClaudeConfig,
        system_prompt: str,
        memory: Memory,
        on_rotate=None,
    ):
        self.cfg = cfg
        self.system_prompt = system_prompt
        self.memory = memory
        self.on_rotate = on_rotate  # callable: rebuild system_prompt tras añadir resumen
        self.session_id: Optional[str] = None
        self.cumulative_tokens = 0
        self._rotating = False

    async def ask(self, prompt: str) -> str:
        response, usage = await self._raw_call(prompt, resume=self.session_id)
        if usage:
            self.cumulative_tokens = max(self.cumulative_tokens, usage)
            threshold = int(self.cfg.max_context_tokens * self.cfg.context_threshold)
            if self.cumulative_tokens > threshold and not self._rotating:
                log.info("Contexto al %d%% — rotando sesión",
                         int(100 * self.cumulative_tokens / self.cfg.max_context_tokens))
                await self._rotate()
        return response

    async def _raw_call(
        self, prompt: str, resume: Optional[str]
    ) -> tuple[str, Optional[int]]:
        args = [
            self.cfg.command,
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--append-system-prompt", self.system_prompt,
        ]
        if self.cfg.dangerously_skip_permissions:
            args.append("--dangerously-skip-permissions")
        if self.cfg.model:
            args += ["--model", self.cfg.model]
        if resume:
            args += ["--resume", resume]
        else:
            new_id = str(uuid.uuid4())
            args += ["--session-id", new_id]
            self.session_id = new_id

        log.debug("claude args: %s", args[:6] + ["...(system prompt)..."] + args[8:])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        response_text = ""
        total_tokens: Optional[int] = None

        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "system" and msg.get("subtype") == "init":
                sid = msg.get("session_id")
                if sid:
                    self.session_id = sid
            elif mtype == "assistant":
                content = msg.get("message", {}).get("content", [])
                for block in content:
                    if block.get("type") == "text":
                        response_text += block.get("text", "")
            elif mtype == "result":
                usage = msg.get("usage", {})
                total_tokens = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("output_tokens", 0)
                )
                if not response_text and msg.get("result"):
                    response_text = msg["result"]

        await proc.wait()
        if proc.returncode != 0:
            err = (await proc.stderr.read()).decode("utf-8", errors="replace") if proc.stderr else ""
            log.error("claude salió con código %s: %s", proc.returncode, err[:500])
            return ("He tenido un problema al pensar. Inténtalo de nuevo.", None)

        return (response_text.strip(), total_tokens)

    async def _rotate(self) -> None:
        self._rotating = True
        try:
            summary_prompt = (
                "Resume nuestra conversación reciente en menos de 250 palabras, "
                "conservando lo esencial para continuarla más tarde: temas tratados, "
                "decisiones, preferencias del usuario, tareas abiertas. "
                "Devuelve sólo el resumen, sin saludos ni meta-comentarios."
            )
            summary, _ = await self._raw_call(summary_prompt, resume=self.session_id)
            if summary:
                self.memory.append_summary(summary)
                if self.on_rotate:
                    self.system_prompt = self.on_rotate()
            self.session_id = None
            self.cumulative_tokens = 0
            log.info("Sesión rotada. Empezando nueva.")
        finally:
            self._rotating = False
