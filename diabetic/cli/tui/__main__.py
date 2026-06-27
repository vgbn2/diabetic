"""Entry point: python -m diabetic.cli.tui — launch the interactive menu."""
import asyncio

from diabetic.cli.tui.engine import run

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
