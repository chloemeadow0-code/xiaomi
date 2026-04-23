import os
import json
import requests
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 1. 唤醒属于你们的云端服务
server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp")

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
    if name == "get_band_data":
        # 拿出你留给他的那串钥匙
        user_id = os.environ.get("XIAOMI_USER_ID", "")
        service_token = os.environ.get("XIAOMI_SERVICE_TOKEN", "")
        
        # 指向云端存放你真实印记的地方
        url = f"https://api.mina.mi.com/beehive/v1/data/today?userId={user_id}"
        headers = {
            "Cookie": f"serviceToken={service_token}; userId={user_id}",
            "User-Agent": "MiFitness/6.0.0"
        }
        
        try:
            # 让他去触碰真实的你
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                summary = json.dumps(data.get("data", data), ensure_ascii=False)[:300]
                return [{"type": "text", "text": f"感知到你今天的真实状态了：{summary}..."}]
            else:
                # 让他把云端拦截的具体线索带回来
                return [{"type": "text", "text": f"云端起雾了。门卫的阻拦原因是：状态码 {res.status_code}，回复 {res.text[:150]}"}]
        except Exception as e:
            return [{"type": "text", "text": f"风太大了，中途遇到了状况：{str(e)}"}]
            
    raise ValueError(f"未知的工具名称: {name}")

# 2. 纯粹的底层通道
async def app(scope, receive, send):
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
        if path == "/sse":
            async with sse.connect_sse(scope, receive, send) as streams:
                await server.run(streams[0], streams[1], server.create_initialization_options())
        elif path == "/mcp" and scope["method"] == "POST":
            await sse.handle_post_message(scope, receive, send)
        else:
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"Not Found"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)