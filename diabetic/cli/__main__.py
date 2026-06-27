"""Entry point: python -m diabetic.cli <category> <command> [--flag value]."""
import asyncio

from diabetic.cli.dispatcher import main

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
