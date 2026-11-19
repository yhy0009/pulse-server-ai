"""Reproducible, offline synthetic server metrics. Never reads operational data."""
import argparse
import csv
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.summary import summarize

SEED = 20261114
KST = timezone(timedelta(hours=9))


def generate():
    rng = random.Random(SEED)
    start = datetime(2026, 11, 1, tzinfo=KST)
    records = []
    for hour in range(14 * 24):
        date = start + timedelta(hours=hour)
        day = hour // 24
        business = 9 <= date.hour < 19
        cpu = 27 + (23 if business else 0) + 5 * math.sin(hour / 5) + rng.gauss(0, 3)
        if date.weekday() >= 5:
            cpu -= 7
        memory = 49 + 3 * math.sin(hour / 11) + rng.gauss(0, 1.3)
        cpu_memo = "합성: 주간 부하 패턴" if business else "합성: 야간 정상 부하"
        memory_memo = "합성: 정상 메모리 사용"
        if day == 4 and 10 <= date.hour <= 15:
            cpu = 88 + rng.uniform(0, 9)
            cpu_memo = "합성 시나리오: 배치 작업과 CPU 급증"
        leak_start, restart = 6 * 24, 9 * 24 + 8
        if leak_start <= hour < restart:
            memory = 54 + (hour - leak_start) / (restart - leak_start) * 38 + rng.gauss(0, 0.7)
            memory_memo = "합성 시나리오: 메모리 사용량의 지속 증가"
        if hour == restart:
            memory = 42
            memory_memo = "합성 시나리오: 재시작 후 메모리 감소"
        for metric, value, memo in [("cpu", cpu, cpu_memo), ("memory", memory, memory_memo)]:
            records.append({
                "id": f"seed-{metric}-{hour:04d}", "date": date.isoformat(),
                "value": round(min(99.0, max(1.0, value)), 2), "memo": memo,
                "metric": metric, "host": "demo-01",
            })
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = generate()
    raw = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    (args.output / "metrics.json").write_text(raw, encoding="utf-8")
    with (args.output / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    (args.output / "summary.json").write_text(json.dumps(summarize(records), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "source": "synthetic", "seed": SEED, "host": "demo-01", "timezone": "Asia/Seoul",
        "start": records[0]["date"], "end": records[-1]["date"], "interval_minutes": 60,
        "timestamps": 336, "records": len(records), "records_per_metric": 336,
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "scenarios": [
            {"start": "2026-11-05T10:00:00+09:00", "end": "2026-11-05T15:00:00+09:00", "event": "simulated batch workload; CPU spike"},
            {"start": "2026-11-07T00:00:00+09:00", "end": "2026-11-10T07:00:00+09:00", "event": "simulated memory growth"},
            {"start": "2026-11-10T08:00:00+09:00", "event": "simulated restart; memory drops"},
        ],
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(records)} synthetic records ({len(records)//2} timestamps); seed={SEED}")


if __name__ == "__main__":
    main()
