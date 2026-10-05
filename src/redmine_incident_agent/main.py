from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from .agent import build_agent
from .config import Settings
from .dispatcher import Dispatcher
from .redmine import RedmineClient


async def async_main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    settings = Settings.from_env()
    redmine = RedmineClient(settings)
    try:
        agent = build_agent(settings)
        stats = await Dispatcher(settings, redmine, agent).run_once()
        logging.getLogger(__name__).info("run completed: %s", stats)
    finally:
        await redmine.close()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
