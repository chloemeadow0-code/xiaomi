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

        # --- 通道 2: 捞睡眠 (Sessions 接口 + 时间轴去重合并) ---
        # --- 通道 2: 捞睡眠 (Sessions 接口 + 增加时段明细) ---
        sleep_details = []
        try:
            start_str = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(start_ms / 1000))
            end_str = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(end_ms / 1000))
            session_url = f"https://www.googleapis.com/fitness/v1/users/me/sessions?startTime={start_str}&endTime={end_str}&activityType=72"
            res_sleep = requests.get(session_url, headers=headers).json()
            
            intervals = []
            for session in res_sleep.get("session", []):
                s_start = int(session.get("startTimeMillis", 0))
                s_end = int(session.get("endTimeMillis", 0))
                if s_start > 0 and s_end > s_start:
                    intervals.append([s_start, s_end])
                    # 记录具体的起止时间
                    t_start = time.strftime('%H:%M', time.localtime(s_start / 1000))
                    t_end = time.strftime('%H:%M', time.localtime(s_end / 1000))
                    sleep_details.append(f"{t_start}-{t_end}")
            
            intervals.sort(key=lambda x: x[0])
            merged = []
            for interval in intervals:
                if not merged or merged[-1][1] < interval[0]:
                    merged.append(interval)
                else:
                    merged[-1][1] = max(merged[-1][1], interval[1])
            
            sleep_ms = sum(m[1] - m[0] for m in merged)
            data["sleep"] = round(sleep_ms / (1000 * 3600), 1)
            data["sleep_segments"] = " | ".join(sleep_details) if sleep_details else "无"
        except Exception as e: print(f"睡眠报错: {e}")

        # --- 通道 3: 捞心率 (增加测量时间) ---
        data["heart_time"] = "未知"
        try:
            start_ns, end_ns = start_ms * 1000000, end_ms * 1000000
            data_source = "derived:com.google.heart_rate.bpm:com.google.android.gms:merge_heart_rate_bpm"
            hr_url = f"https://www.googleapis.com/fitness/v1/users/me/dataSources/{data_source}/datasets/{start_ns}-{end_ns}"
            res_heart = requests.get(hr_url, headers=headers).json()
            
            latest_time, latest_bpm = 0, 0
            for p in res_heart.get("point", []):
                p_time = int(p.get("endTimeNanos", 0))
                if p_time > latest_time:
                    latest_time = p_time
                    latest_bpm = p.get("value", [])[0].get("fpVal", 0)
            
            if latest_bpm > 0:
                data["heart"] = int(latest_bpm)
                # 转换成易读的时间格式 (HH:mm)
                data["heart_time"] = time.strftime('%H:%M', time.localtime(latest_time / 1000000000))
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