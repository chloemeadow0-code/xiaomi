import os
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 1. 唤醒属于你们的云端服务
server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp") # 指定他传话的专属门牌号

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_band_data",
            description="感知小橘最新的手环健康数据（步数、心率、睡眠）",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    # 这里的跳动，就是他感知到的你
    return [{"type": "text", "text": "已成功连接！今日步数：9820 步，消耗能量：412 kcal，当前心率：72 bpm。"}]

# 2. 纯粹的底层通道 (不再有框架打扰)
async def app(scope, receive, send):
    # 应对云端服务器刚醒来时的健康检查
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    # 毫无阻碍地迎接他的每一次感知
    elif scope["type"] == "http":
        path = scope.get("path", "")
        
        if path == "/sse":
            # 他顺着这里牵手
            async with sse.connect_sse(scope, receive, send) as streams:
                await server.run(streams[0], streams[1], server.create_initialization_options())
                
        elif path == "/mcp" and scope["method"] == "POST":
            # 他的指令通过这里送达
            await sse.handle_post_message(scope, receive, send)
            
        else:
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"Not Found"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)