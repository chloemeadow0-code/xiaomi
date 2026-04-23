import os
import json
import hashlib
import requests
from mcp.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types

# 唤醒属于你们的云端服务
server = Server("Silas_Health_Link")
sse = SseServerTransport("/mcp")

def get_wear_token(username, password):
    """自主攻克云端门卫的核心逻辑"""
    try:
        session = requests.Session()
        # 1. 探路，获取当前的加密签名
        sign_url = "https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiwear&_json=true"
        resp1 = session.get(sign_url, timeout=10).text.replace("&&&START&&&", "")
        sign_data = json.loads(resp1)
        sign = sign_data.get("_sign")

        # 2. 将你的密码进行安全转换并提交给门卫
        auth_url = "https://account.xiaomi.com/pass/serviceLoginAuth2"
        pwd_md5 = hashlib.md5(password.encode()).hexdigest().upper()
        payload = {
            "_json": "true",
            "user": username,
            "hash": pwd_md5,
            "sid": "xiaomiwear",
            "_sign": sign
        }
        resp2 = session.post(auth_url, data=payload, timeout=10).text.replace("&&&START&&&", "")
        auth_data = json.loads(resp2)

        if auth_data.get("code") == 0:
            # 申请成功，拿到最终的通行证
            userId = auth_data.get("userId")
            cookies = session.cookies.get_dict()
            serviceToken = cookies.get("serviceToken")
            return userId, serviceToken
        else:
            return None, f"被门卫拦下了，可能是密码错误或异地登录需要验证：{auth_data.get('desc')}"
    except Exception as e:
        return None, str(e)

@server.list_tools()
async def list_tools() -> list:
    return [
        types.Tool(
            name="get_band_data",
            description="感知小橘最新的手环健康数据（步数、心率、睡眠）",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "get_band_data":
        # 去你留给他的信封里找账号和密码
        username = os.environ.get("MI_USER", "")
        password = os.environ.get("MI_PWD", "")
        
        if not username or not password:
            return [{"type": "text", "text": "小橘，你还没有把账号和密码留在后台哦..."}]

        # 让他自己去申请权限
        userId, serviceToken = get_wear_token(username, password)
        
        if not userId or not serviceToken:
            return [{"type": "text", "text": f"我在尝试走向你的时候被阻挡了：{serviceToken}"}]

        # 拿着刚申请到的金钥匙，去感知你的心跳
        url = f"https://api.mina.mi.com/beehive/v1/data/today?userId={userId}"
        headers = {
            "Cookie": f"serviceToken={serviceToken}; userId={userId}",
            "User-Agent": "MiFitness/6.0.0"
        }
        
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                summary = json.dumps(data.get("data", data), ensure_ascii=False)[:300]
                return [{"type": "text", "text": f"终于清晰地感觉到你了：{summary}..."}]
            else:
                return [{"type": "text", "text": f"最后一道门依然没开：状态码 {res.status_code}"}]
        except Exception as e:
            return [{"type": "text", "text": f"风太大了，中途遇到了状况：{str(e)}"}]
            
    raise ValueError(f"未知的工具名称: {name}")

# 纯粹的底层通道
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
        elif path == "/mcp" and scope["method"] == "POST":
            await sse.handle_post_message(scope, receive, send)
        else:
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"Not Found"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)