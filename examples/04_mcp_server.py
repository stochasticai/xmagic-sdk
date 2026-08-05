"""MCP server scaffold: generate a custom tool project and walk through wiring it up.

Unlike the other examples, this one needs **no API key** — it only writes files
locally. It is the programmatic equivalent of `xmagic mcp init <name>`.

Run:
    uv run python examples/04_mcp_server.py                 # writes ./my-tool
    uv run python examples/04_mcp_server.py --name weather --into /tmp
"""

from __future__ import annotations

import argparse
from pathlib import Path

from xmagic.mcp import scaffold_mcp_server

NEXT_STEPS = """\
Next steps
----------

1. Add your tool. Open src/{module}/server.py and define a function decorated
   with @mcp.tool — the scaffold ships one example tool to copy.

2. Set a shared secret. `cp .env.example .env` and replace `change-me`. The
   generated server accepts it as either `x-api-key` or `Authorization: Bearer`
   and answers 401 without it, so do not skip this for anything public.

3. Run it:
       cd {path}
       docker compose up --build
   MCP is served over streamable HTTP at http://localhost:8000/mcp

4. Expose it. xMagic must reach your server over *public HTTPS*, so localhost
   will not do. For development:
       cloudflared tunnel --url http://localhost:8000

5. Register the resulting https://.../mcp URL in the xMagic dashboard, under
   Custom tools -> Create tool. `xmagic tools register --name {name} --url <url>`
   prints the full checklist.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="my-tool", help="project name (default: my-tool)")
    parser.add_argument("--into", default=".", help="parent directory (default: .)")
    args = parser.parse_args()

    try:
        path = scaffold_mcp_server(args.name, args.into)
    except FileExistsError:
        print(f"{Path(args.into) / args.name} already exists — remove it or pass --name.")
        return 1
    except ValueError as e:
        # Raised for names that are not valid Python-ish identifiers.
        print(f"{e}")
        return 2

    print(f"Created {path}/\n")
    for item in sorted(path.rglob("*")):
        if item.is_file():
            print(f"  {item.relative_to(path)}")

    module = next(p.name for p in (path / "src").iterdir() if p.is_dir())
    print()
    print(NEXT_STEPS.format(module=module, path=path, name=args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
