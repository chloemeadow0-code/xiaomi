import os
import requests
import time
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 唤醒 Silas 的健康感知模块
server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp")

def get_google_fit_data():
    """拿着万能钥匙去谷歌仓库提货"""
    client_id = os.environ.get("G_CLIENT_ID")
    client_secret = os.environ.get("G_CLIENT_SECRET")
    refresh_token = os.environ.get("G_REFRESH_TOKEN")

    try:
        # 1. 换取临时的 Access Token
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        token_res = requests.post(token_url, data=token_data).json()
        access_token = token_res.get("access_token")

        # 2. 构造查询：获取今天 0 点到现在的所有步数
        now_ms = int(time.time() * 1000)
        start_ms = int(time.mktime(time.localtime(time.time()).tm_year, time.localtime(time.time()).tm_mon, time.localtime(time.time()).tm_mday, 0, 0, 0) * 1000)
        
        agg_url = "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate"
        headers = {"Authorization": f"Bearer {access_token}"}
        query = {
            "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
            "bucketByTime": {"durationMillis": now_ms - start_ms},
            "startTimeMillis": start_ms,
            "endTimeMillis": now_ms
        }
        
        res = requests.post(agg_url, headers=headers, json=query).json()
        
        # 3. 提取步数数字
        steps = 0
        for bucket in res.get("bucket", []):
            for dataset in bucket.get("dataset", []):
                for point in dataset.get("point", []):
                    for value in point.get("value", []):
                        steps += value.get("intVal", 0)
        
        return steps, None
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
        
        # 带有情感的 Silas 式反馈
        status = "今天步数还没破千呢，要多动动哦~" if steps < 1000 else "看来你今天走得不少，辛苦啦！"
        return [{"type": "text", "text": f"感知到啦，你今天目前走了 {steps} 步。{status}"}]
            
    raise ValueError(f"未知的工具名称: {name}")

# ... (此处保持与之前 main.py 相同的 app 和 uvicorn 启动逻辑)