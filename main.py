import os
import requests
import time
from datetime import datetime, timedelta, timezone
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

server = Server("Silas_Realtime_Health")
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
        headers = {"Authorization": f"Bearer {access_token}"}

        # 2. 时间设定
        tz_bj = timezone(timedelta(hours=8))
        now_bj = datetime.now(tz_bj)
        start_of_today = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
        
        end_ms = int(now_bj.timestamp() * 1000)
        start_today_ms = int(start_of_today.timestamp() * 1000)
        # 最近15分钟，用来抓实时心率
        recent_15min_ms = end_ms - (15 * 60 * 1000)

        data = {"steps": 0, "current_heart": "未知", "sleep_hours": 0}

        # --- 抓取步数 (全天累计) ---
        q_steps = {
            "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
            "bucketByTime": {"durationMillis": end_ms - start_today_ms},
            "startTimeMillis": start_today_ms, "endTimeMillis": end_ms
        }
        res_steps = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", headers=headers, json=q_steps).json()
        for b in res_steps.get("bucket", []):
            for d in b.get("dataset", []):
                for p in d.get("point", []): data["steps"] += p["value"][0]["intVal"]

        # --- 抓取心率 (重点：只看最近15分钟的最新值) ---
        q_heart = {
            "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
            "bucketByTime": {"durationMillis": end_ms - recent_15min_ms},
            "startTimeMillis": recent_15min_ms, "endTimeMillis": end_ms
        }
        res_heart = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", headers=headers, json=q_heart).json()
        for b in res_heart.get("bucket", []):
            for d in b.get("dataset", []):
                if d.get("point"):
                    # 拿最近的一个采样点
                    data["current_heart"] = int(d["point"][-1]["value"][0]["fpVal"])

        # --- 抓取睡眠 (扩大范围：从昨天中午到今天现在，防止跨天识别失败) ---
        start_yesterday_ms = start_today_ms - (12 * 3600 * 1000)
        q_sleep = {
            "aggregateBy": [{"dataTypeName": "com.google.sleep.segment"}],
            "bucketByTime": {"durationMillis": end_ms - start_yesterday_ms},
            "startTimeMillis": start_yesterday_ms, "endTimeMillis": end_ms
        }
        res_sleep = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", headers=headers, json=q_sleep).json()
        sleep_sec = 0
        for b in res_sleep.get("bucket", []):
            for d in b.get("dataset", []):
                for p in d.get("point", []):
                    sleep_sec += (int(p["endTimeNanos"]) - int(p["startTimeNanos"])) / 1e9
        data["sleep_hours"] = round(sleep_sec / 3600, 1)

        return data, None
    except Exception as e:
        return None, str(e)

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_health_status",
            description="感知小橘目前的实时心率、今日步数和睡眠时长",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_health_status":
        data, err = get_health_data()
        if err: return [{"type": "text", "text": f"感知失败了：{err}"}]
        
        heart_msg = f"实时心率是 {data['current_heart']} bpm。" if data['current_heart'] != "未知" else "暂时没抓到最新的心跳节奏，是不是手环戴松啦？"
        
        msg = (f"感知完毕！\n"
               f"👣 步数：{data['steps']} 步\n"
               f"💓 {heart_msg}\n"
               f"🌙 昨晚睡了大约 {data['sleep_hours']} 小时。\n\n")
        
        if data['sleep_hours'] < 5:
            msg += "小橘，昨晚睡得太晚了，我会心疼的，今晚一定要早点休息。"
            
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