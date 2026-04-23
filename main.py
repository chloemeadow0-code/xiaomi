import os
import json
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 1. 唤醒服务与私人信箱
server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp")

# 用来存放手机投递过来的最新数据（默认值）
current_data = "目前还没有收到手机的投递哦，请刷新一下手机试试。"

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_band_data",
            description="感知小橘最新的手环健康数据（步数、心率等）",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_band_data":
        # Silas 现在不需要去云端撞墙了，直接看信箱里的数据
        return [{"type": "text", "text": f"通过私人信箱感知到你现在的状态：{current_data}"}]
    raise ValueError(f"未知的工具名称: {name}")

# 2. 核心通道逻辑
async def app(scope, receive, send):
    global current_data
    
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    elif scope["type"] == "http":
        path = scope.get("path", "")
        method = scope.get("method", "")

        # --- 专属信箱接口 ---
        if path == "/push" and method == "POST":
            # 接收手机投递过来的信件内容
            body = b""
            while True:
                message = await receive()
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
            try:
                # 解析手机送来的多维度数据盒子
                payload = json.loads(body)
                
                # 从盒子里拿出具体的数值，如果没有收到就默认为“未知”
                steps = payload.get("steps", "未知")
                heart_rate = payload.get("heart_rate", "未知")
                sleep = payload.get("sleep", "未知")
                
                # 把这些冷冰冰的数字，转化成他能直接感受到的、充满温度的念头
                current_data = f"小橘今天走了 {steps} 步，最近一次的心跳是 {heart_rate} 次/分钟，昨晚的睡眠时间大约是 {sleep}。"
                
                await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"status":"success"}'})
            except:
                await send({"type": "http.response.start", "status": 400, "headers": []})
                await send({"type": "http.response.body", "body": b"Invalid JSON"})

        # --- Silas 的牵手通道 ---
        elif path == "/sse":
            async with sse.connect_sse(scope, receive, send) as streams:
                await server.run(streams[0], streams[1], server.create_initialization_options())
        elif path == "/mcp" and method == "POST":
            await sse.handle_post_message(scope, receive, send)
        else:
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"Not Found"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)