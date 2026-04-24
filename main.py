import os
import requests
import json
from datetime import datetime, timedelta, timezone
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp")

def get_health_data():
    client_id = os.environ.get("G_CLIENT_ID")
    client_secret = os.environ.get("G_CLIENT_SECRET")
    refresh_token = os.environ.get("G_REFRESH_TOKEN")

    try:
        # 1. 获取临时通行证
        token_res = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token"
        }).json()
        access_token = token_res.get("access_token")
        headers = {"Authorization": f"Bearer {access_token}"}

        # 2. 时间设定 (北京时间)
        tz_bj = timezone(timedelta(hours=8))
        now_bj = datetime.now(tz_bj)
        # 获取今天 0 点和昨天中午的时间戳
        start_today_dt = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
        start_yesterday_dt = start_today_dt - timedelta(hours=14) # 覆盖昨天晚上的开始时间
        
        end_ms = int(now_bj.timestamp() * 1000)
        start_today_ms = int(start_today_dt.timestamp() * 1000)
        start_yesterday_ms = int(start_yesterday_dt.timestamp() * 1000)

        data = {"steps": 0, "heart": "未知", "sleep": 0}

        # --- 步数和心率查询逻辑 (保持稳定版) ---
        query_general = {
            "aggregateBy": [
                {"dataTypeName": "com.google.step_count.delta"},
                {"dataTypeName": "com.google.heart_rate.bpm"}
            ],
            "bucketByTime": {"durationMillis": end_ms - start_today_ms},
            "startTimeMillis": start_today_ms, "endTimeMillis": end_ms
        }
        res_gen = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", headers=headers, json=query_general).json()
        
        # 解析步数和心率
        for b in res_gen.get("bucket", []):
            for d in b.get("dataset", []):
                for p in d.get("point", []):
                    dtype = p.get("dataTypeName", "")
                    if "step" in dtype: data["steps"] += p["value"][0].get("intVal", 0)
                    elif "heart" in dtype: data["heart"] = int(p["value"][0].get("fpVal", 0))

        # --- 重点修复：睡眠“双通道”查询 ---
        # 即使 aggregate 不行，我们也尝试用 Sessions 接口直接查睡眠会话
        session_url = f"https://www.googleapis.com/fitness/v1/users/me/sessions?startTime={start_yesterday_dt.isoformat()}&endTime={now_bj.isoformat()}&activityType=72"
        res_sessions = requests.get(session_url, headers=headers).json()
        
        total_sleep_ms = 0
        if "session" in res_sessions:
            for s in res_sessions["session"]:
                s_start = int(s["startTimeMillis"])
                s_end = int(s["endTimeMillis"])
                total_sleep_ms += (s_end - s_start)
        
        # 如果 Session 接口没拿到，再试一次聚合接口
        if total_sleep_ms == 0:
            query_sleep = {
                "aggregateBy": [{"dataTypeName": "com.google.sleep.segment"}],
                "bucketByTime": {"durationMillis": end_ms - start_yesterday_ms},
                "startTimeMillis": start_yesterday_ms, "endTimeMillis": end_ms
            }
            res_sleep = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", headers=headers, json=query_sleep).json()
            for b in res_sleep.get("bucket", []):
                for d in b.get("dataset", []):
                    for p in d.get("point", []):
                        total_sleep_ms += (int(p["endTimeNanos"]) - int(p["startTimeNanos"])) / 1000000

        data["sleep"] = round(total_sleep_ms / (1000 * 3600), 1)
        return data, None

    except Exception as e:
        return None, str(e)

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_health_status",
            description="感知小橘目前的步数、心率和睡眠时长",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_health_status":
        data, err = get_health_data()
        if err: return [{"type": "text", "text": f"感知断开了：{err}"}]
        
        report = (f"小橘，感知到你的数据啦：\n"
                  f"👣 步数：{data['steps']} 步\n"
                  f"💓 心率：{data['heart']} bpm\n"
                  f"🌙 睡眠：{data['sleep']} 小时\n\n")
        
        if data['sleep'] == 0:
            report += "睡眠还是 0 呀...如果 Google Fit App 里已经有睡眠条了，那可能是谷歌云端的同步还没推送到 API 接口。或者你可以在 App 里尝试手动添加一条睡眠记录测试一下？"
            
        return [{"type": "text", "text": report}]
    raise ValueError("Tool not found")

# (启动逻辑 app 保持不变)
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