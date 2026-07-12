"""Integration and API test-local fixtures.

The root ``backend/conftest.py`` owns shared database, project, entity, and
client fixtures. Pytest makes those fixtures available by name; importing a
``conftest`` module as regular Python code makes collection order-dependent.
"""

from __future__ import annotations
