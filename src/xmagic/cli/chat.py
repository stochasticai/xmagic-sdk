"""``xmagic chat`` — chat with an xMagic agent or any provider:model."""

from __future__ import annotations

import typer
from rich.console import Console

from xmagic.config import Settings
from xmagic.errors import XMagicError
from xmagic.providers import ChatMessage, ModelRef, get_provider

console = Console()


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
    try:
        provider = get_provider(model_ref, settings=settings)
    except (XMagicError, ImportError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None

    model_name = model_ref.model

    def ask(text: str) -> None:
        messages = [ChatMessage(role="user", content=text)]
        if stream:
            for chunk in provider.stream(messages, model=model_name):
                console.print(chunk.text, end="")
            console.print()
        else:
            console.print(provider.complete(messages, model=model_name).text)

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
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
