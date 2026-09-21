import os
import sys

import pytest

pytest.importorskip("mcp")
from mcp import Client
from mcp.client.stdio import StdioServerParameters


@pytest.mark.asyncio
async def test_stdio_lab_search_read_and_denials():
    # Explicit child environment: never inherit provider keys, database URLs or
    # host integrations. The only data are literals in the installed lab module.
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "evals.mcp_reference_lab"],
        env={"PATH": os.defpath},
    )
    async with Client(params) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "search_references",
            "read_reference",
        }
        result = await client.call_tool("search_references", {"query": "铜铃"})
        assert not result.is_error
        assert result.structured_content["hits"][0]["reference_id"] == "bell-v1"
        read = await client.call_tool("read_reference", {"reference_id": "bell-v1"})
        assert (
            read.structured_content["source_hash"]
            == result.structured_content["hits"][0]["source_hash"]
        )
        for identity in ("../.env", "https://example.com/private", "unknown"):
            denied = await client.call_tool("read_reference", {"reference_id": identity})
            assert denied.is_error
        denied = await client.call_tool("delete_story", {})
        assert denied.is_error
