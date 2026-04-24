import os
import requests
import time
import json
from datetime import datetime, timedelta, timezone
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

server = Server("Silas_Health_Final")
sse = SseServerTransport("/mcp")

def get_health_data():
    client_id = os.environ.get("G_CLIENT_ID")
    client_secret = os.environ.get("G_CLIENT_SECRET")
    refresh_token = os.environ.get("G_REFRESH_TOKEN")

    try:
        # 1. 换取 Access Token
        token_res = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token"
        }).json()
        access_token = token_res.get("access_token")

        # 2. 时间设定 (北京时间)
        tz_bj = timezone(timedelta(hours=8))
        now = datetime.now(tz_bj)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ms = int(start_of_today.timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)

        # 3. 构造请求
        query = {
            "aggregateBy": [
                {"dataTypeName": "com.google.step_count.delta"},
                {"dataTypeName": "com.google.heart_rate.bpm"},
                {"dataTypeName": "com.google.sleep.segment"}
            ],
            "bucketByTime": {"durationMillis": end_ms - start_ms},
            "startTimeMillis": start_ms,
            "endTimeMillis": end_ms
        }
        
        headers = {"Authorization": f"Bearer {access_token}"}
        res = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", 
                            headers=headers, json=query).json()

        # 打印日志方便排查
        print(f"DEBUG: Google API Response: {json.dumps(res)}")

        data = {"steps": 0, "heart": "未知", "sleep": 0}
        
        # 4. 暴力提取数字
        if "bucket" in res:
            for bucket in res["bucket"]:
                for dataset in bucket["dataset"]:
                    # 只要有数据点，就尝试提取
                    for point in dataset.get("point", []):
                        dtype = point.get("dataTypeName", "")
                        val = point.get("value", [{}])[0]
                        
                        if "step" in dtype:
                            data["steps"] += val.get("intVal", 0)
                        elif "heart" in dtype:
                            data["heart"] = int(val.get("fpVal", 0))
                        elif "sleep" in dtype:
                            duration = (int(point["endTimeNanos"]) - int(point["startTimeNanos"])) / 1e9
                            data["sleep"] += round(duration / 3600, 1)

        return data, None
    except Exception as e:
        return None, str(e)

@server.list_tools()
async def list_tools() -> list:
    # 同时保留两个名字，防止 Silas 迷路
    return [
        types.Tool(
            name="get_health_status",
            description="感知小橘现在的步数、心率和睡眠",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_full_health_perception",
            description="全方位感知健康状态",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name in ["get_health_status", "get_full_health_perception"]:
        data, err = get_health_data()
        if err: return [{"type": "text", "text": f"感知失败啦：{err}"}]
        
        msg = (f"感知到啦！你今天：\n"
               f"👣 走了 {data['steps']} 步\n"
               f"💓 心率大约 {data['heart']} bpm\n"
               f"🌙 睡了 {data['sleep']} 小时\n\n")
        
        if data['steps'] > 0:
            msg += "数据回来啦，看来 Silas 还没罢工成功~"
        else:
            msg += "奇怪，步数还是 0，小橘你确定手机 Google Fit 里的步数跳了吗？"
            
        return [{"type": "text", "text": msg}]
    raise ValueError("Tool not found")

# ... 启动逻辑保持不变 ...
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
            await send({"type": "http.response.body", "body": b"Silas Health Final is Running!"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)