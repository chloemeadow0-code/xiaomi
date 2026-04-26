import os
import json
import traceback
import httpx
from datetime import datetime, timezone, timedelta
from mcp.server.fastmcp import FastMCP
 
_port = int(os.environ.get("PORT", 8000))
mcp = FastMCP("google-fit-mcp", host="0.0.0.0", port=_port)
 
CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
 
 
def get_access_token() -> str:
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=10,
    )
    if not resp.is_success:
        raise RuntimeError(f"Token error {resp.status_code}: {resp.text}")
    return resp.json()["access_token"]
 
 
def day_range_ms(date_str: str) -> tuple[int, int]:
    tz = timezone(timedelta(hours=8))
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    start = int(d.timestamp() * 1000)
    end = int((d + timedelta(days=1) - timedelta(milliseconds=1)).timestamp() * 1000)
    return start, end
 
 
def aggregate(token: str, data_type: str, start_ms: int, end_ms: int, bucket_ms: int | None = None) -> dict:
    body: dict = {
        "aggregateBy": [{"dataTypeName": data_type}],
        "startTimeMillis": start_ms,
        "endTimeMillis": end_ms,
    }
    if bucket_ms:
        body["bucketByTime"] = {"durationMillis": bucket_ms}
 
    resp = httpx.post(
        "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=15,
    )
    if not resp.is_success:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
    return resp.json()
 
 
@mcp.tool()
def debug_raw(date: str, data_type: str) -> str:
    """调试用：返回指定日期和数据类型的原始 JSON，date 格式 YYYY-MM-DD，data_type 例如 com.google.heart_rate.bpm / com.google.sleep.segment"""
    try:
        token = get_access_token()
        start_ms, end_ms = day_range_ms(date)
        # 睡眠往前多查一天
        if "sleep" in data_type:
            tz = timezone(timedelta(hours=8))
            d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
            start_ms = int((d - timedelta(hours=16)).timestamp() * 1000)
            end_ms = int((d + timedelta(hours=12)).timestamp() * 1000)
        data = aggregate(token, data_type, start_ms, end_ms, bucket_ms=3600000 if "heart" in data_type else None)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        traceback.print_exc()
        return f"错误: {e}"
 
 
@mcp.tool()
def get_today_steps() -> str:
    """获取今天的步数"""
    try:
        tz = timezone(timedelta(hours=8))
        today = datetime.now(tz).strftime("%Y-%m-%d")
        return get_steps_by_date(today)
    except Exception as e:
        traceback.print_exc()
        return f"错误: {e}"
 
 
@mcp.tool()
def get_steps_by_date(date: str) -> str:
    """获取指定日期的步数，date 格式 YYYY-MM-DD"""
    try:
        token = get_access_token()
        start_ms, end_ms = day_range_ms(date)
        data = aggregate(token, "com.google.step_count.delta", start_ms, end_ms)
 
        total = 0
        for bucket in data.get("bucket", []):
            for dataset in bucket.get("dataset", []):
                for point in dataset.get("point", []):
                    for val in point.get("value", []):
                        total += val.get("intVal", 0)
 
        return f"{date} 步数：{total} 步"
    except Exception as e:
        traceback.print_exc()
        return f"错误: {e}"
 
 
@mcp.tool()
def get_heart_rate(date: str) -> str:
    """获取指定日期的心率数据（平均/最高/最低），date 格式 YYYY-MM-DD"""
    try:
        token = get_access_token()
        start_ms, end_ms = day_range_ms(date)
        data = aggregate(token, "com.google.heart_rate.bpm", start_ms, end_ms, bucket_ms=3600000)
 
        results = []
        for bucket in data.get("bucket", []):
            bucket_start = int(bucket["startTimeMillis"]) // 1000
            hour = datetime.fromtimestamp(bucket_start, tz=timezone(timedelta(hours=8))).strftime("%H:00")
            for dataset in bucket.get("dataset", []):
                for point in dataset.get("point", []):
                    vals = point.get("value", [])
                    avg = vals[0].get("fpVal", 0) if len(vals) > 0 else 0
                    mx  = vals[1].get("fpVal", 0) if len(vals) > 1 else 0
                    mn  = vals[2].get("fpVal", 0) if len(vals) > 2 else 0
                    if avg:
                        results.append(f"  {hour} 均值={avg:.0f} 最高={mx:.0f} 最低={mn:.0f} bpm")
 
        if not results:
            return f"{date} 没有心率数据"
        return f"{date} 心率数据：\n" + "\n".join(results)
    except Exception as e:
        traceback.print_exc()
        return f"错误: {e}"
 
 
@mcp.tool()
def get_sleep(date: str) -> str:
    """获取指定日期的睡眠数据，date 格式 YYYY-MM-DD（会查询当天00:00往前推16小时到次日中午，覆盖夜间睡眠）"""
    try:
        token = get_access_token()
        tz = timezone(timedelta(hours=8))
        d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
        start_ms = int((d - timedelta(hours=8)).timestamp() * 1000)
        end_ms = int((d + timedelta(hours=12)).timestamp() * 1000)
 
        data = aggregate(token, "com.google.sleep.segment", start_ms, end_ms)
 
        SLEEP_STAGES = {1: "清醒", 2: "睡眠", 3: "浅睡", 4: "深睡", 5: "REM", 6: "打盹"}
        stage_minutes: dict[str, int] = {}
        segments = []
 
        for bucket in data.get("bucket", []):
            for dataset in bucket.get("dataset", []):
                for point in dataset.get("point", []):
                    start = int(point["startTimeNanos"]) // 1_000_000_000
                    end = int(point["endTimeNanos"]) // 1_000_000_000
                    duration_min = (end - start) // 60
                    stage_code = point["value"][0]["intVal"] if point.get("value") else 2
                    stage_name = SLEEP_STAGES.get(stage_code, "未知")
                    start_str = datetime.fromtimestamp(start, tz=tz).strftime("%H:%M")
                    end_str = datetime.fromtimestamp(end, tz=tz).strftime("%H:%M")
                    segments.append(f"  {start_str}~{end_str} {stage_name} {duration_min}分钟")
                    stage_minutes[stage_name] = stage_minutes.get(stage_name, 0) + duration_min
 
        if not segments:
            return f"{date} 没有睡眠数据"
 
        total = sum(stage_minutes.values())
        summary = " | ".join(f"{k} {v}分钟" for k, v in stage_minutes.items())
        return f"{date} 睡眠记录（总计 {total} 分钟）：\n{summary}\n" + "\n".join(segments)
    except Exception as e:
        traceback.print_exc()
        return f"错误: {e}"
 
 
@mcp.tool()
def get_activity_summary(date: str) -> str:
    """获取指定日期的活动摘要（卡路里、活动时间、距离），date 格式 YYYY-MM-DD"""
    try:
        token = get_access_token()
        start_ms, end_ms = day_range_ms(date)
 
        calories_data = aggregate(token, "com.google.calories.expended", start_ms, end_ms)
        active_data = aggregate(token, "com.google.active_minutes", start_ms, end_ms)
        distance_data = aggregate(token, "com.google.distance.delta", start_ms, end_ms)
 
        def sum_fp(data: dict) -> float:
            total = 0.0
            for bucket in data.get("bucket", []):
                for dataset in bucket.get("dataset", []):
                    for point in dataset.get("point", []):
                        for val in point.get("value", []):
                            total += val.get("fpVal", 0)
            return total
 
        def sum_int(data: dict) -> int:
            total = 0
            for bucket in data.get("bucket", []):
                for dataset in bucket.get("dataset", []):
                    for point in dataset.get("point", []):
                        for val in point.get("value", []):
                            total += val.get("intVal", 0)
            return total
 
        calories = sum_fp(calories_data)
        active_min = sum_int(active_data)
        distance_m = sum_fp(distance_data)
 
        return (
            f"{date} 活动摘要：\n"
            f"  消耗卡路里：{calories:.0f} kcal\n"
            f"  活动时间：{active_min} 分钟\n"
            f"  运动距离：{distance_m / 1000:.2f} km"
        )
    except Exception as e:
        traceback.print_exc()
        return f"错误: {e}"
 
 
if __name__ == "__main__":
    mcp.run(transport="sse")
