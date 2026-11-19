from datetime import datetime, timedelta
from statistics import mean

THRESHOLDS = {"cpu": 85.0, "memory": 80.0}


def summarize(records):
    """All numeric facts are calculated in Python, rather than invented by the LLM."""
    ordered = sorted(records, key=lambda r: (r["date"], r["id"]))
    result = {
        "source": "synthetic", "host": "demo-01", "unit": "%", "count": len(ordered),
        "period": {"start": ordered[0]["date"], "end": ordered[-1]["date"]} if ordered else None,
        "trend_method": "각 지표의 마지막 관측 시각 기준 최근 24시간 평균과 직전 24시간 평균 비교. 차이 3%p 이상 증가, -3%p 이하 감소, 그 외 유지.",
        "metrics": {},
    }
    for metric, threshold in THRESHOLDS.items():
        rows = [r for r in ordered if r["metric"] == metric]
        if not rows:
            result["metrics"][metric] = None
            continue
        end = datetime.fromisoformat(rows[-1]["date"])
        current = [r["value"] for r in rows if datetime.fromisoformat(r["date"]) > end - timedelta(hours=24)]
        previous = [r["value"] for r in rows if end - timedelta(hours=48) < datetime.fromisoformat(r["date"]) <= end - timedelta(hours=24)]
        delta = round(mean(current) - mean(previous), 2) if previous else None
        peak = max(rows, key=lambda r: r["value"])
        low = min(rows, key=lambda r: r["value"])
        exceeded = [r for r in rows if r["value"] >= threshold]
        daily = {}
        for row in rows:
            day = row["date"][:10]
            daily.setdefault(day, []).append(row["value"])
        result["metrics"][metric] = {
            "count": len(rows), "average": round(mean(r["value"] for r in rows), 2),
            "min": low["value"], "min_at": low["date"], "max": peak["value"], "max_at": peak["date"],
            "latest": rows[-1]["value"], "latest_at": rows[-1]["date"],
            "recent_24h_average": round(mean(current), 2),
            "previous_24h_average": round(mean(previous), 2) if previous else None,
            "change_pp": delta, "trend": "비교 불가" if delta is None else "증가" if delta >= 3 else "감소" if delta <= -3 else "유지",
            "threshold": threshold, "threshold_count": len(exceeded),
            "threshold_last_at": exceeded[-1]["date"] if exceeded else None,
            "daily": [{"date": day, "average": round(mean(values), 2), "max": max(values), "count": len(values)} for day, values in daily.items()],
        }
    return result
