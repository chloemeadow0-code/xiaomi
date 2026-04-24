#!/usr/bin/env python3
"""
Health Connect MCP Server - 部署在 Zeabur 上

流程：
  Android App 推送数据 → POST /upload
  RikkaHub 连接 MCP  → GET /sse
"""

import json
import os
import uvicorn
from datetime import datetime
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp import types
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import JSONResponse

# 内存存储（Zeabur 重启后清空，但 App 会重新推送）
health_store = {
    "sleep": [],
    "heart_rate": [],
    "last_updated": None
}

# 简单的 API Key 保护（在 Zeabur 环境变量里设置 API_KEY）
API_KEY = os.environ.get("API_KEY", "change-this-key")

mcp = Server("health-connect-mcp")


# ─── MCP Tools ────────────────────────────────────────────

@mcp.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_health_data",
            description="获取健康数据，包括睡眠和心率，来自小米手环",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="get_sleep_data",
            description="获取睡眠数据，包括深睡/浅睡/REM 各阶段",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="get_heart_rate_data",
            description="获取心率数据",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="get_last_updated",
            description="查看数据最后同步时间",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if health_store["last_updated"] is None:
        return [types.TextContent(
            type="text",
            text="⚠️ 还没有数据，请先打开手机 App 同步一次"
        )]

    if name == "get_health_data":
        result = {
            "sleep": health_store["sleep"],
            "heart_rate": health_store["heart_rate"],
            "last_updated": health_store["last_updated"]
        }
    elif name == "get_sleep_data":
        result = {
            "sleep": health_store["sleep"],
            "last_updated": health_store["last_updated"]
        }
    elif name == "get_heart_rate_data":
        result = {
            "heart_rate": health_store["heart_rate"],
            "last_updated": health_store["last_updated"]
        }
    elif name == "get_last_updated":
        result = {"last_updated": health_store["last_updated"]}
    else:
        return [types.TextContent(type="text", text=f"未知工具: {name}")]

    return [types.TextContent(
        type="text",
        text=json.dumps(result, ensure_ascii=False, indent=2)
    )]


# ─── HTTP 接口 ─────────────────────────────────────────────

async def upload(request: Request):
    """Android App 调用这个接口上传健康数据"""
    # 验证 API Key
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    data = await request.json()
    health_store["sleep"] = data.get("sleep", [])
    health_store["heart_rate"] = data.get("heart_rate", [])
    health_store["last_updated"] = datetime.now().isoformat()

    return JSONResponse({
        "status": "ok",
        "sleep_records": len(health_store["sleep"]),
        "heart_rate_records": len(health_store["heart_rate"]),
        "updated_at": health_store["last_updated"]
    })


async def status(request: Request):
    """查看服务器状态"""
    return JSONResponse({
        "status": "running",
        "last_updated": health_store["last_updated"],
        "sleep_records": len(health_store["sleep"]),
        "heart_rate_records": len(health_store["heart_rate"]),
    })


# ─── SSE / MCP ─────────────────────────────────────────────

sse = SseServerTransport("/messages/")


async def handle_sse(request: Request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp.run(
            streams[0], streams[1],
            mcp.create_initialization_options()
        )


# ─── App ───────────────────────────────────────────────────

app = Starlette(
    routes=[
        Route("/upload", upload, methods=["POST"]),
        Route("/status", status, methods=["GET"]),
        Route("/sse", handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ]
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print(f"🚀 服务器启动：http://0.0.0.0:{port}")
    print(f"📡 MCP SSE：http://0.0.0.0:{port}/sse")
    uvicorn.run(app, host="0.0.0.0", port=port)
