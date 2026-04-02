"""Entry point: python -m autodev"""

import asyncio

from autodev.orchestrator import Orchestrator

if __name__ == "__main__":
    orchestrator = Orchestrator()
    asyncio.run(orchestrator.start())
