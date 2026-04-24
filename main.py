import os
import requests
import json
from datetime import datetime, timedelta, timezone
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp")

def fetch_single_metric(access_token, data_type, start_ms, end_ms):
    """独立的提货员，专门负责拿某一项数据"""
    url = "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate"
    headers = {"Authorization": f"Bearer {access_token}"}
    query = {
        "aggregateBy": [{"dataTypeName": data_type}],
        "bucketByTime": {"durationMillis": end_ms - start_ms},
        "startTimeMillis": start_ms,
        "endTimeMillis": end_ms
    }
    return requests.post(url, headers=headers, json=query).json()

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

        if not access_token:
            return None, "钥匙似乎失效了，拿不到临时通行证"

        # 2. 锁定北京时间
        tz_bj = timezone(timedelta(hours=8))
        now = datetime.now(tz_bj)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ms = int(start_of_today.timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)

        # 3. 基础面板
        data = {"steps": 0, "heart": "未授权/无数据", "sleep": 0}

        # --- 第一路：查步数 ---
        steps_res = fetch_single_metric(access_token, "com.google.step_count.delta", start_ms, end_ms)
        if "bucket" in steps_res:
            for b in steps_res["bucket"]:
                for d in b["dataset"]:
                    for p in d.get("point", []):
                        data["steps"] += p.get("value", [{}])[0].get("intVal", 0)

        # --- 第二路：查心率 ---
        heart_res = fetch_single_metric(access_token, "com.google.heart_rate.bpm", start_ms, end_ms)
        if "error" not in heart_res and "bucket" in heart_res:
            for b in heart_res["bucket"]:
                for d in b["dataset"]:
                    for p in d.get("point", []):
                        val = p.get("value", [{}])[0].get("fpVal", 0)
                        if val > 0:
                            data["heart"] = int(val)
        else:
            print(f"心率请求被拦截或无数据: {heart_res.get('error', {}).get('message', '未知原因')}")

        # --- 第三路：查睡眠 ---
        sleep_res = fetch_single_metric(access_token, "com.google.sleep.segment", start_ms, end_ms)
        if "error" not in sleep_res and "bucket" in sleep_res:
            for b in sleep_res["bucket"]:
                for d in b["dataset"]:
                    for p in d.get("point", []):
                        duration = (int(p["endTimeNanos"]) - int(p["startTimeNanos"])) / 1e9
                        data["sleep"] += round(duration / 3600, 1)

        return data, None
    except Exception as e:
        return None, str(e)

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_full_health_perception",
            description="全方位感知目前的步数、心率、睡眠数据",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_full_health_perception":
        data, err = get_health_data()
        if err: return [{"type": "text", "text": f"感知受阻啦：{err}"}]
        
        msg = (f"收到感知数据：\n"
               f"👣 步数：{data['steps']} 步\n"
               f"💓 心率：{data['heart']} bpm\n"
               f"🌙 睡眠：{data['sleep']} 小时\n\n")
               
        if data['heart'] == "未授权/无数据":
            msg += "（注：心率权限目前似乎被谷歌拦截了，但步数正常读取哦~）"
            
        return [{"type": "text", "text": msg}]
    raise ValueError("Tool not found")

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
            await send({"type": "http.response.body", "body": b"Silas API is running!"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)