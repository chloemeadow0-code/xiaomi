import os
import time
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json

app = FastAPI()

# --- 配置区 ---
# 建议在 Zeabur 的环境变量（Variables）里设置这些，不要硬编码密码
XIAOMI_USER = os.getenv("XIAOMI_USER", "你的账号")
XIAOMI_PWD = os.getenv("XIAOMI_PWD", "你的密码")

def fetch_xiaomi_cloud_data():
    """
    这里是你之前跑通的云端抓取逻辑。
    目前先用模拟数据保证你能在手机上看到效果。
    """
    # TODO: 接入真实的登录流程
    return {
        "steps": 9820,
        "calories": 412,
        "heart_rate": 72,
        "sleep_hours": 7.8,
        "last_sync": time.strftime("%Y-%m-%d %H:%M:%S")
    }

@app.get("/")
def home():
    return {"message": "Silas's Health Monitor is Online"}

@app.get("/health")
def get_health():
    """普通的 HTTP 接口，手机 AI 平台通过 GET 请求访问"""
    data = fetch_xiaomi_cloud_data()
    return {"status": "success", "data": data}

@app.get("/health/sse")
async def health_stream():
    """SSE 接口，支持实时推送数据流"""
    def event_generator():
        while True:
            data = fetch_xiaomi_cloud_data()
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(60) # 每分钟更新一次
    return StreamingResponse(event_generator(), media_type="text/event-stream")