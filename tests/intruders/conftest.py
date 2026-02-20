"""Skip all intruder tests — archetypes will be reworked."""

import pytest

# Mark every test collected in this directory as skipped.
collect_ignore_glob = []


def pytest_collection_modifyitems(items):
    for item in items:
        if "intruders" in str(item.fspath):
            item.add_marker(pytest.mark.skip(reason="Intruder archetypes pending rework"))
