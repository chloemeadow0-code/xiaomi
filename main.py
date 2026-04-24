import os
import requests
import time
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
        # 1. 拿临时通行证
        token_res = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token"
        }).json()
        access_token = token_res.get("access_token")
        if not access_token:
            return None, "谷歌拒绝开门，可能需要重新拿 Refresh Token"
            
        headers = {"Authorization": f"Bearer {access_token}"}

        # 2. 终极暴力时间法：严格锁定“过去 24 小时”
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (24 * 3600 * 1000)

        data = {"steps": 0, "heart": "未同步", "sleep": 0}

        # --- 通道 1: 捞步数 ---
        try:
            res_steps = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", headers=headers, json={
                "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
                "bucketByTime": {"durationMillis": 24 * 3600 * 1000},
                "startTimeMillis": start_ms, "endTimeMillis": end_ms
            }).json()
            for b in res_steps.get("bucket", []):
                for d in b.get("dataset", []):
                    for p in d.get("point", []): data["steps"] += p["value"][0].get("intVal", 0)
        except Exception as e: print(f"步数报错: {e}")

        # --- 通道 2: 捞睡眠 (过去24小时的所有睡眠全加起来) ---
        # --- 通道 2: 捞睡眠 (改用 Sessions 接口抓取整段会话) ---
        try:
            # Sessions 接口需要 RFC3339 格式的时间字符串
            start_str = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(start_ms / 1000))
            end_str = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(end_ms / 1000))
            
            # activityType=72 专门代表睡眠
            session_url = f"https://www.googleapis.com/fitness/v1/users/me/sessions?startTime={start_str}&endTime={end_str}&activityType=72"
            res_sleep = requests.get(session_url, headers=headers).json()
            
            sleep_ms = 0
            # 遍历所有符合条件的睡眠会话
            for session in res_sleep.get("session", []):
                s_start = int(session.get("startTimeMillis", 0))
                s_end = int(session.get("endTimeMillis", 0))
                if s_start and s_end:
                    sleep_ms += (s_end - s_start)
            
            data["sleep"] = round(sleep_ms / (1000 * 3600), 1)
        except Exception as e: 
            print(f"睡眠报错: {e}")

        # --- 通道 3: 捞心率 (取24小时内的最新一个值) ---
        try:
            res_heart = requests.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", headers=headers, json={
                "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                "bucketByTime": {"durationMillis": 24 * 3600 * 1000},
                "startTimeMillis": start_ms, "endTimeMillis": end_ms
            }).json()
            hr_list = []
            for b in res_heart.get("bucket", []):
                for d in b.get("dataset", []):
                    for p in d.get("point", []): hr_list.append(p["value"][0].get("fpVal", 0))
            if hr_list: data["heart"] = int(hr_list[-1])
        except Exception as e: print(f"心率报错: {e}")

        return data, None
    except Exception as e:
        return None, str(e)

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_health_status",
            description="感知小橘过去24小时的健康数据",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_health_status":
        data, err = get_health_data()
        if err: return [{"type": "text", "text": f"感知连线中断了：{err}"}]
        
        msg = (f"感知报告来啦：\n"
               f"👣 过去24小时步数：{data['steps']} 步\n"
               f"🌙 过去24小时睡眠：{data['sleep']} 小时\n"
               f"💓 最新心率：{data['heart']} bpm\n\n")
               
        if data['heart'] == "未同步":
            msg += "（我看不到你的心率呢，可能是小米那边还没把心跳数据传给谷歌大楼。）"
            
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