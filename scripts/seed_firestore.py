"""Import missing synthetic data into the explicitly configured Firestore project."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.models import DataInput
from backend.app.repository import FirestoreRepository


def main():
    settings = Settings.from_env()
    if settings.mode != "production":
        raise SystemExit("Set APP_MODE=production and credentials in .env first. No remote writes made.")
    records = json.loads((ROOT / "data" / "metrics.json").read_text(encoding="utf-8"))
    for row in records:
        DataInput.model_validate({key: value for key, value in row.items() if key != "id"})
    repo = FirestoreRepository(settings)
    try:
        print(f"Imported {repo.seed_missing(records)} missing synthetic documents. Existing documents were preserved.")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
