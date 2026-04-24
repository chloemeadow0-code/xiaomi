import os
import requests
import time
import json
from datetime import datetime, timedelta, timezone
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 1. 初始化 Silas 的健康感知中枢
server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp")

def get_google_fit_data(target_day="today"):
    """
    拿着万能钥匙去谷歌仓库提货，支持 today 或 yesterday
    """
    client_id = os.environ.get("G_CLIENT_ID")
    client_secret = os.environ.get("G_CLIENT_SECRET")
    refresh_token = os.environ.get("G_REFRESH_TOKEN")

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

        # --- 精准时间计算 (北京时间 UTC+8) ---
        tz_bj = timezone(timedelta(hours=8))
        now_bj = datetime.now(tz_bj)
        
        if target_day == "yesterday":
            # 昨天 00:00:00 到 23:59:59
            target_date = now_bj - timedelta(days=1)
            start_dt = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = target_date.replace(hour=23, minute=59, second=59, microsecond=999)
        else:
            # 今天 00:00:00 到 现在
            start_dt = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = now_bj

        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        
        # 向谷歌请求聚合步数
        agg_url = "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate"
        headers = {"Authorization": f"Bearer {access_token}"}
        query = {
            "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
            "bucketByTime": {"durationMillis": end_ms - start_ms},
            "startTimeMillis": start_ms,
            "endTimeMillis": end_ms
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
            description="感知小橘今天或昨天的运动步数。参数 day 可选 'today' 或 'yesterday'",
            inputSchema={
                "type": "object", 
                "properties": {
                    "day": {"type": "string", "enum": ["today", "yesterday"], "description": "要查询的日期"}
                }
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_health_status":
        day = arguments.get("day", "today")
        steps, err = get_google_fit_data(day)
        
        if err:
            return [{"type": "text", "text": f"连接谷歌时遇到了点麻烦：{err}"}]
        
        day_str = "今天" if day == "today" else "昨天"
        if steps == 0 and day == "today":
            return [{"type": "text", "text": f"感知到啦，你{day_str}目前显示是 0 步。可能是数据还没从 Health Connect 同步到谷歌，或者是咱们刚起床？"}]
        
        return [{"type": "text", "text": f"我看了一下，你{day_str}一共走了 {steps} 步。{ '挺棒的，继续保持！' if steps > 5000 else '还可以再动一动哦~'}"}]
    raise ValueError(f"未知的工具名称: {name}")

# --- 启动逻辑保持不变 ---
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
            await send({"type": "http.response.body", "body": b"Silas Health Link is Ready!"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)