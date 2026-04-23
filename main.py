import os
from fastapi import FastAPI
from starlette.requests import Request
import uvicorn

# 引入官方 MCP 底层库
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

app = FastAPI()
server = Server("Xiaomi_Health_Cloud")

# --- 1. 定义 AI 可以调用的工具 ---
@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_band_data",
            description="获取最新的手环健康数据（步数、心率、睡眠）",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

# --- 2. 处理 AI 的实际调用逻辑 ---
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_band_data":
        # 这里预留给你后续接真实小米云端 API，先用测试数据打通
        return [
            {
                "type": "text",
                "text": "已成功连接！今日步数：9820 步，消耗能量：412 kcal，当前心率：72 bpm。"
            }
        ]
    raise ValueError(f"未知的工具名称: {name}")

# --- 3. 架设平台硬性要求的 /sse 和 /mcp 房间 ---
# 告诉 SSE 传输层，客户端回传信息的门牌号是 /mcp
sse = SseServerTransport("/mcp")

async def endpoint_sse(scope, receive, send):
    """最底层的牵手通道，彻底避开中间人的打扰"""
    async with sse.connect_sse(scope, receive, send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

async def endpoint_mcp(scope, receive, send):
    """专属的指令通道"""
    await sse.handle_post_message(scope, receive, send)

# 直接挂载为底层的独立应用，不再受主框架的规则限制
app.mount("/sse", endpoint_sse)
app.mount("/mcp", endpoint_mcp)

# --- 4. 启动设置 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # 注意这里改成了 "main:app" 以避免 uvicorn 进程冲突
    uvicorn.run("main:app", host="0.0.0.0", port=port)