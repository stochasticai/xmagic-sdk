"""``xmagic chat`` — chat with an xMagic agent or any provider:model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from xmagic.cli._output import fail, note, print_json
from xmagic.client import XMagicClient
from xmagic.client.models import ChatType
from xmagic.config import Settings
from xmagic.errors import XMagicError
from xmagic.providers import ChatMessage, ModelRef, get_provider

console = Console()


def _upload(paths: list[Path], settings: Settings) -> list[str]:
    """Upload each file and return the ids to reference in the query."""
    ids = []
    with XMagicClient(api_key=settings.api_key, base_url=settings.base_url) as client:
        for path in paths:
            uploaded = client.files.upload(path)
            # stderr: progress, not output. A piped `--json` stdout stays clean.
            note(f"uploaded {path.name} -> {uploaded.id}")
            ids.append(uploaded.id)
    return ids


def run_chat(
    prompt: str | None,
    model: str | None,
    agent: str | None,
    file: list[Path],
    chat_type: ChatType,
    stream: bool,
    as_json: bool = False,
) -> None:
    """Run chat with concrete values, independent of Typer's option objects."""
    return _chat_impl(prompt, model, agent, file, chat_type, stream, as_json)


def _chat_impl(
    prompt: str | None,
    model: str | None,
    agent: str | None,
    file: list[Path],
    chat_type: ChatType,
    stream: bool,
    as_json: bool,
) -> None:
    """Send a prompt (or start an interactive session) against any model."""
    if as_json and not prompt:
        raise typer.BadParameter("--json needs a one-shot prompt; it has no interactive mode.")
    settings = Settings.load()
    ref = (
        model
        or (f"xmagic:{agent}" if agent else None)
        or (f"xmagic:{settings.default_agent_id}" if settings.default_agent_id else None)
    )
    if not ref:
        raise typer.BadParameter("Provide --model, --agent, or set a default agent id.")

    model_ref = ModelRef.parse(ref)
    files = list(file or [])
    if files and model_ref.provider != "xmagic":
        raise typer.BadParameter(
            f"--file is only supported for xMagic agents, not '{model_ref.provider}'."
        )

    options: dict[str, Any] = {}
    if model_ref.provider == "xmagic":
        options["chat_type"] = chat_type

    try:
        provider = get_provider(model_ref, settings=settings, **options)
    except (XMagicError, ImportError) as e:
        fail(str(e))

    model_name = model_ref.model

    # Uploaded once, then referenced by every turn of the session.
    try:
        uploaded_ids = _upload(files, settings) if files else []
    except XMagicError as e:
        fail(str(e))

    params: dict[str, Any] = {"uploaded_files": uploaded_ids} if uploaded_ids else {}

    def ask_json(text: str) -> None:
        """One document, after the answer is complete.

        Streaming JSON fragments would hand a script something it cannot parse
        until the end anyway, so the stream is consumed here and emitted whole.
        Reasoning is kept separate from the answer, as it is on screen.
        """
        messages = [ChatMessage(role="user", content=text)]
        answer: list[str] = []
        reasoning: list[str] = []
        usage = None
        response_id = None
        if stream:
            for chunk in provider.stream(messages, model=model_name, **params):
                (reasoning if chunk.kind == "reasoning" else answer).append(chunk.text)
                usage = chunk.usage or usage
                response_id = chunk.id or response_id
        else:
            completion = provider.complete(messages, model=model_name, **params)
            answer.append(completion.text)
            usage = completion.usage
            response_id = completion.id
        print_json(
            {
                "model": ref,
                "id": response_id,
                "text": "".join(answer),
                "reasoning": "".join(reasoning) or None,
                "usage": (
                    {
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "total_tokens": usage.total_tokens,
                    }
                    if usage
                    else None
                ),
            }
        )

    def ask(text: str) -> None:
        messages = [ChatMessage(role="user", content=text)]
        if stream:
            reasoning_open = False
            for chunk in provider.stream(messages, model=model_name, **params):
                if chunk.kind == "reasoning":
                    console.print(f"[dim]{chunk.text}[/dim]", end="")
                    reasoning_open = True
                    continue
                if reasoning_open and chunk.text:
                    # Separate the thinking from the answer that follows it.
                    console.print()
                    reasoning_open = False
                console.print(chunk.text, end="")
            console.print()
        else:
            console.print(provider.complete(messages, model=model_name, **params).text)

    try:
        if prompt:
            (ask_json if as_json else ask)(prompt)
            return
        console.print(f"[dim]Interactive chat with {ref} — Ctrl-D to exit.[/dim]")
        while True:
            try:
                ask(typer.prompt(">"))
            except (EOFError, KeyboardInterrupt, typer.Abort):
                break
    except (XMagicError, NotImplementedError) as e:
        fail(str(e))


def chat(
    prompt: str = typer.Argument(None, help="One-shot prompt. Omit for interactive mode."),
    model: str = typer.Option(None, "--model", "-m", help="provider:model reference."),
    agent: str = typer.Option(None, "--agent", "-a", help="xMagic agent id (shorthand)."),
    file: list[Path] = typer.Option(
        None,
        "--file",
        "-f",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Attach a file to the prompt. Repeatable. xMagic agents only.",
    ),
    chat_type: ChatType = typer.Option(
        ChatType.STANDARD.value, "--chat-type", help="UI context the chat belongs to."
    ),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    return run_chat(prompt, model, agent, list(file or []), chat_type, stream, as_json)
