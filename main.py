import os
import requests
import time
from datetime import datetime, timedelta, timezone
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

server = Server("Silas_Full_Health_Link")
sse = SseServerTransport("/mcp")

def get_full_health_data():
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

        headers = {"Authorization": f"Bearer {access_token}"}
        
        # 3. 构造全数据聚合请求
        query = {
            "aggregateBy": [
                {"dataTypeName": "com.google.step_count.delta"},  # 步数
                {"dataTypeName": "com.google.heart_rate.bpm"},    # 心率
                {"dataTypeName": "com.google.sleep.segment"}      # 睡眠
            ],
            "bucketByTime": {"durationMillis": end_ms - start_ms},
            "startTimeMillis": start_ms,
            "endTimeMillis": end_ms
        }
        
        res = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", 
                            headers=headers, json=query).json()

        # 4. 解析复杂数据
        results = {"steps": 0, "heart_rate": "未知", "sleep_hours": 0}
        
        if "bucket" in res:
            for bucket in res["bucket"]:
                for dataset in bucket["dataset"]:
                    # 解析步数
                    if "step_count" in dataset["dataSourceId"]:
                        for p in dataset["point"]: results["steps"] += p["value"][0]["intVal"]
                    # 解析心率 (取平均值)
                    elif "heart_rate" in dataset["dataSourceId"]:
                        if dataset["point"]: 
                            hr_list = [p["value"][0]["fpVal"] for p in dataset["point"]]
                            results["heart_rate"] = int(sum(hr_list) / len(hr_list))
                    # 解析睡眠 (小时)
                    elif "sleep" in dataset["dataSourceId"]:
                        duration = 0
                        for p in dataset["point"]:
                            duration += (int(p["endTimeNanos"]) - int(p["startTimeNanos"])) / 1e9
                        results["sleep_hours"] = round(duration / 3600, 1)

        return results, None
    except Exception as e:
        return None, str(e)

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_full_health_perception",
            description="全方位感知小橘当下的健康状态（步数、心率、睡眠）",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_full_health_perception":
        data, err = get_full_health_data()
        if err: return [{"type": "text", "text": f"感知受阻：{err}"}]
        
        # Silas 的全方位关心
        report = (
            f"今天的感知报告出来啦：\n"
            f"👣 步数：{data['steps']} 步\n"
            f"💓 平均心率：{data['heart_rate']} bpm\n"
            f"🌙 今日睡眠累计：{data['sleep_hours']} 小时\n\n"
        )
        if data['heart_rate'] != "未知" and data['heart_rate'] > 100:
            report += "小心跳有点快哦，是不是在想我，还是刚运动完？"
        elif data['sleep_hours'] < 6:
            report += "昨晚睡得有点少，一定要找时间午睡一下，我会心疼的。"
        else:
            report += "状态看起来不错，继续保持这份活力吧~"
            
        return [{"type": "text", "text": report}]
    raise ValueError("Tool not found")

# 启动逻辑保持不变... (省略部分同上)
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