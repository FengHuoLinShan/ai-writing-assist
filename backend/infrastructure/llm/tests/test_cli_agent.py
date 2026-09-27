"""CLI event contracts; no paid provider calls or user configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from infrastructure.llm.cli_agent import CLIAgentError, CLIEvent, CLISpec, run_cli_agent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "lines", "expected_tools"),
    [
        (
            "codex",
            [
                {"type": "item.started", "item": {"type": "command_execution"}},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "完成"},
                },
                {"type": "turn.completed", "usage": {"input_tokens": 4}},
            ],
            1,
        ),
        (
            "claude",
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
                },
                {"type": "result", "result": "完成", "is_error": False},
            ],
            1,
        ),
        (
            "kimi",
            [
                {
                    "role": "assistant",
                    "content": "完成",
                    "tool_calls": [{"function": {"name": "Read"}}],
                }
            ],
            1,
        ),
        ("dsh", ["完成"], 0),
        (
            "pi",
            [
                {"type": "tool_execution_start", "toolName": "bash"},
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "完成"}],
                    },
                },
                {"type": "agent_end"},
            ],
            1,
        ),
    ],
)
async def test_five_cli_outputs_are_bounded_and_normalized(
    tmp_path: Path, kind: str, lines: list, expected_tools: int
) -> None:
    executable = tmp_path / "fake-cli"
    output = "\n".join(
        line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)
        for line in lines
    )
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write({output!r} + '\\n')\n"
        "sys.stderr.write('private reasoning must stay private')\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    events: list[CLIEvent] = []

    async def on_event(event: CLIEvent) -> None:
        events.append(event)

    result = await run_cli_agent(
        CLISpec(
            kind=kind, prompt="合成任务", workspace=tmp_path, command=str(executable)
        ),
        on_event=on_event,
    )

    assert result.answer == "完成"
    assert result.tool_attempts == expected_tools
    assert "private reasoning" not in repr(events)


@pytest.mark.asyncio
async def test_native_tool_limit_stops_run(tmp_path: Path) -> None:
    executable = tmp_path / "fake-cli"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        'print(\'{"type":"tool_execution_start","toolName":"bash"}\')\n'
        'print(\'{"type":"agent_end"}\')\n',
        encoding="utf-8",
    )
    executable.chmod(0o700)

    with pytest.raises(CLIAgentError, match="工具调用超过上限"):
        await run_cli_agent(
            CLISpec(
                kind="pi",
                prompt="合成任务",
                workspace=tmp_path,
                max_tool_attempts=0,
                command=str(executable),
            )
        )


@pytest.mark.asyncio
async def test_pi_model_error_is_not_a_successful_empty_answer(tmp_path: Path) -> None:
    executable = tmp_path / "fake-pi"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        'print(\'{"type":"message_end","message":{"role":"assistant",'
        '"stopReason":"error","errorMessage":"model unavailable"}}\')\n',
        encoding="utf-8",
    )
    executable.chmod(0o700)
    with pytest.raises(CLIAgentError, match="Pi 模型请求失败"):
        await run_cli_agent(
            CLISpec(
                kind="pi",
                prompt="合成任务",
                workspace=tmp_path,
                command=str(executable),
            )
        )
