import pytest_asyncio
from tests.fake_relay import fake_relay


@pytest_asyncio.fixture
async def relay():
    async with fake_relay() as (url, server):
        yield (url, server)
