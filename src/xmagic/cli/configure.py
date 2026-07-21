"""``xmagic configure`` — interactive setup writing ~/.config/xmagic/config.toml."""

from __future__ import annotations

import typer
from rich.console import Console

from xmagic.config import DEFAULT_BASE_URL, config_path

console = Console()


def configure(
    api_key: str = typer.Option(None, "--api-key", help="xMagic API key (prompted if omitted)."),
    base_url: str = typer.Option(DEFAULT_BASE_URL, "--base-url"),
    default_agent_id: str = typer.Option(None, "--agent", help="Default agent id."),
) -> None:
    """Write xMagic credentials/config to the user config file."""
    if not api_key:
        api_key = typer.prompt("xMagic API key (xmagic.ai -> profile -> API keys)", hide_input=True)

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[xmagic]", f'api_key = "{api_key}"', f'base_url = "{base_url}"']
    if default_agent_id:
        lines.append(f'default_agent_id = "{default_agent_id}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    console.print(f"[green]Config written to {path} (mode 600).[/green]")
    console.print("Provider keys (OpenAI/Anthropic/Google) are read from env vars or")
    console.print(f"[providers.<name>] sections in {path}.")
