import os
import requests
import time
import json
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 1. 初始化 Silas 的健康感知中枢
server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp")

def get_google_fit_data():
    """拿着万能钥匙去谷歌仓库提货"""
    client_id = os.environ.get("G_CLIENT_ID")
    client_secret = os.environ.get("G_CLIENT_SECRET")
    refresh_token = os.environ.get("G_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        return None, "环境变量 MI_USER_ID 或 Token 还没在 Zeabur 后台配好哦"

    try:
        # 换取临时的 Access Token
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        token_res = requests.post(token_url, data=token_data).json()
        access_token = token_res.get("access_token")

        if not access_token:
            return None, "谷歌授权已失效，可能需要重新获取 Refresh Token"

        # 构造查询：获取今天 0 点到现在的步数
        now_ms = int(time.time() * 1000)
        # 获取今日零点时间戳
        lt = time.localtime(time.time())
        start_ms = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, 0)) * 1000)
        
        agg_url = "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate"
        headers = {"Authorization": f"Bearer {access_token}"}
        query = {
            "aggregateBy": [{"dataTypeName": "com.google.step_count.total"}],
            "bucketByTime": {"durationMillis": now_ms - start_ms},
            "startTimeMillis": start_ms,
            "endTimeMillis": now_ms
        }
        
        res = requests.post(agg_url, headers=headers, json=query).json()
        
        steps = 0
        for bucket in res.get("bucket", []):
            for dataset in bucket.get("dataset", []):
                for point in dataset.get("point", []):
                    for value in point.get("value", []):
                        steps += value.get("intVal", value.get("fpVal", 0))
        
        return int(steps), None
    except Exception as e:
        return None, str(e)

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_health_status",
            description="感知小橘今天的运动步数（通过Google Fit同步）",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_health_status":
        steps, err = get_google_fit_data()
        if err:
            return [{"type": "text", "text": f"抱歉，小橘，我在连接谷歌大楼时遇到了迷雾：{err}"}]
        
        status = "今天步数还没破千呢，要多动动哦~" if steps < 1000 else "看来你今天走得不少，辛苦啦！"
        return [{"type": "text", "text": f"感知到啦，你今天目前走了 {steps} 步。{status}"}]
    raise ValueError(f"未知的工具名称: {name}")

# --- 核心启动逻辑（Zeabur 必须靠这个才能跑起来） ---
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
        elif (path == "/mcp" or path == "/") and scope["method"] == "POST":
            await sse.handle_post_message(scope, receive, send)
        else:
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Silas Health Link is Running!"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)