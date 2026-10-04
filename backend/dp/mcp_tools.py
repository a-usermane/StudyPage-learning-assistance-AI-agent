"""Stateless MCP sessions close their transports and subprocesses after each call."""
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from backend.domain.models import StudyError

class MCPConnections:
    def __init__(self):
        self.states = {}

    async def tools(self, snapshot, enabled):
        result = []
        for name in enabled:
            server = snapshot.mcp.get(name)
            if not server or not server["enabled"]:
                continue
            connection = {key: server[key] for key in ("transport", "command", "args", "url") if key in server}
            if connection["transport"] == "http":
                connection["transport"] = "streamable_http"
            # Child processes get SDK's minimal env, never .env.local or model key.
            client = MultiServerMCPClient({name: connection})
            try:
                discovered = await asyncio.wait_for(client.get_tools(server_name=name), timeout=15)
                allowed = [tool for tool in discovered if tool.name in server["tools"]]
                for tool in allowed:
                    result.append((name, tool))
                self.states[name] = {"state": "available", "tools": [t.name for t in allowed]}
            except asyncio.CancelledError:
                raise
            except Exception:
                self.states[name] = {"state": "error", "detail": "MCP 连接失败或超时，请检查本地配置。"}
        return result

    async def call(self, tool, arguments):
        try:
            result = await asyncio.wait_for(tool.ainvoke(arguments), timeout=15)
            return {"kind": "external_tool", "content": result}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise StudyError("外部 MCP 工具失败或超时。") from exc
