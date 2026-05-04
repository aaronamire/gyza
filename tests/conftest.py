import pytest


def pytest_collection_modifyitems(config, items):
    # Mark every async test function as asyncio so pytest-asyncio runs
    # them without requiring per-test decorators or pytest.ini config.
    for item in items:
        if "asyncio" in item.keywords:
            continue
        if hasattr(item, "obj") and __import__("asyncio").iscoroutinefunction(item.obj):
            item.add_marker(pytest.mark.asyncio)
