"""``xmagic chat`` — chat with an xMagic agent or any provider:model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape

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
            console.print(f"[dim]uploaded {path.name} -> {uploaded.id}[/dim]")
            ids.append(uploaded.id)
    return ids


def chat(
    prompt: str = typer.Argument(None, help="One-shot prompt. Omit for interactive mode."),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="provider:model ref, e.g. xmagic:<agent_id>, openai:gpt-4o, "
        "anthropic:claude-sonnet-5, google:gemini-2.5-pro.",
    ),
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
        ChatType.STANDARD.value,
        "--chat-type",
        help="UI context the chat belongs to. xMagic agents only.",
    ),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
) -> None:
    """Send a prompt (or start an interactive session) against any model."""
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
        # `escape`, because error text is data. Without it Rich reads bracketed
        # content as markup and silently drops it -- "[providers.openai] api_key"
        # rendered as " api_key", pointing at nothing.
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1) from None

    model_name = model_ref.model

    # Uploaded once, then referenced by every turn of the session.
    try:
        uploaded_ids = _upload(files, settings) if files else []
    except XMagicError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    params: dict[str, Any] = {"uploaded_files": uploaded_ids} if uploaded_ids else {}

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
            ask(prompt)
            return
        console.print(f"[dim]Interactive chat with {ref} — Ctrl-D to exit.[/dim]")
        while True:
            try:
                ask(typer.prompt(">"))
            except (EOFError, KeyboardInterrupt, typer.Abort):
                break
    except (XMagicError, NotImplementedError) as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1) from None
