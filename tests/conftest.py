import os
import tempfile

import pytest


def pytest_collection_modifyitems(config, items):
    # Mark every async test function as asyncio so pytest-asyncio runs
    # them without requiring per-test decorators or pytest.ini config.
    for item in items:
        if "asyncio" in item.keywords:
            continue
        if hasattr(item, "obj") and __import__("asyncio").iscoroutinefunction(item.obj):
            item.add_marker(pytest.mark.asyncio)


@pytest.fixture(autouse=True)
def _isolate_guard_config_history():
    """No test may read or write the HOST's guard-config version floor.

    `build_registries` consults `~/.gyza/guard_config_history.jsonl` to refuse
    a rollback, so without this a synthetic v1 fixture is rejected on any
    machine that has installed a later version -- and the suite's result would
    depend on the developer's own host state. That is not a suite.

    FUNCTION-scoped, not session-scoped. A shared history is shared STATE: one
    test installing v3 raises the floor and the next test's v1 fixture is
    refused, which showed up as two failures that passed in isolation and
    failed in the full run. Each test gets its own floor because each test is
    supposed to be independent of the others.

    Autouse because the coupling runs through `load_config`, which any test may
    reach indirectly.
    """
    d = tempfile.mkdtemp(prefix="gyza-test-guard-history-")
    prev = os.environ.get("GYZA_GUARD_HISTORY")
    os.environ["GYZA_GUARD_HISTORY"] = os.path.join(d, "history.jsonl")
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("GYZA_GUARD_HISTORY", None)
        else:
            os.environ["GYZA_GUARD_HISTORY"] = prev
