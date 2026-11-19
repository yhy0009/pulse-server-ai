import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .config import ROOT


class ServiceError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def check_size(collection, document):
    if collection == "conversations" and len(json.dumps(document, ensure_ascii=False).encode("utf-8")) > 700_000:
        raise ServiceError(413, "대화가 너무 깁니다. 새 대화를 시작해 주세요.")


class SQLiteRepository:
    """Local preview only. A seed marker prevents deleted data returning on restart."""
    def __init__(self, path: Path, seed=True):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS documents (collection TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(collection, id))")
            conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
            if seed and conn.execute("SELECT value FROM metadata WHERE key='seeded'").fetchone() is None:
                for row in json.loads((ROOT / "data" / "metrics.json").read_text(encoding="utf-8")):
                    conn.execute("INSERT OR IGNORE INTO documents VALUES (?, ?, ?)", ("data", row["id"], json.dumps(row, ensure_ascii=False)))
                conn.execute("INSERT INTO metadata VALUES ('seeded', 'true')")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def list(self, collection):
        with self.connect() as conn:
            return [json.loads(row[0]) for row in conn.execute("SELECT body FROM documents WHERE collection=?", (collection,))]

    def get(self, collection, identifier):
        with self.connect() as conn:
            row = conn.execute("SELECT body FROM documents WHERE collection=? AND id=?", (collection, identifier)).fetchone()
        if row is None:
            raise ServiceError(404, "요청한 항목을 찾을 수 없습니다.")
        return json.loads(row[0])

    def create(self, collection, document):
        check_size(collection, document)
        row = {**document, "id": uuid4().hex}
        with self.connect() as conn:
            conn.execute("INSERT INTO documents VALUES (?, ?, ?)", (collection, row["id"], json.dumps(row, ensure_ascii=False)))
        return row

    def replace(self, collection, identifier, document, expected_version=None):
        check_size(collection, document)
        row = {**document, "id": identifier}
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT body FROM documents WHERE collection=? AND id=?", (collection, identifier)).fetchone()
            if current is None:
                raise ServiceError(404, "요청한 항목을 찾을 수 없습니다.")
            if expected_version is not None and json.loads(current[0]).get("version") != expected_version:
                raise ServiceError(409, "다른 요청에서 대화가 변경되었습니다. 대화를 다시 불러와 주세요.")
            conn.execute("UPDATE documents SET body=? WHERE collection=? AND id=?", (json.dumps(row, ensure_ascii=False), collection, identifier))
        return row

    def delete(self, collection, identifier):
        with self.connect() as conn:
            result = conn.execute("DELETE FROM documents WHERE collection=? AND id=?", (collection, identifier))
            if result.rowcount == 0:
                raise ServiceError(404, "요청한 항목을 찾을 수 없습니다.")


class FirestoreRepository:
    """Production uses the assignment's data and conversations collections."""
    def __init__(self, settings):
        import firebase_admin
        from firebase_admin import credentials, firestore

        credential = credentials.Certificate(json.loads(settings.firebase_json) if settings.firebase_json else settings.firebase_path)
        # Named apps let separate test/application instances coexist safely.
        self.app = firebase_admin.initialize_app(credential, name=f"pulse-{uuid4().hex}")
        self.db = firestore.client(self.app)

    def list(self, collection):
        return [{**doc.to_dict(), "id": doc.id} for doc in self.db.collection(collection).stream(timeout=20)]

    def get(self, collection, identifier):
        doc = self.db.collection(collection).document(identifier).get(timeout=20)
        if not doc.exists:
            raise ServiceError(404, "요청한 항목을 찾을 수 없습니다.")
        return {**doc.to_dict(), "id": doc.id}

    def create(self, collection, document):
        check_size(collection, document)
        reference = self.db.collection(collection).document()
        row = {**document, "id": reference.id}
        reference.create(row, timeout=20)
        return row

    def replace(self, collection, identifier, document, expected_version=None):
        from google.cloud import firestore

        check_size(collection, document)
        reference = self.db.collection(collection).document(identifier)
        row = {**document, "id": identifier}

        @firestore.transactional
        def write(transaction):
            current = reference.get(transaction=transaction)
            if not current.exists:
                raise ServiceError(404, "요청한 항목을 찾을 수 없습니다.")
            if expected_version is not None and current.to_dict().get("version") != expected_version:
                raise ServiceError(409, "다른 요청에서 대화가 변경되었습니다. 대화를 다시 불러와 주세요.")
            transaction.set(reference, row)

        write(self.db.transaction())
        return row

    def delete(self, collection, identifier):
        from google.cloud import firestore

        reference = self.db.collection(collection).document(identifier)

        @firestore.transactional
        def remove(transaction):
            if not reference.get(transaction=transaction).exists:
                raise ServiceError(404, "요청한 항목을 찾을 수 없습니다.")
            transaction.delete(reference)

        remove(self.db.transaction())

    def seed_missing(self, records):
        """Idempotent import: existing seed documents, including edits, are preserved."""
        by_id = {row["id"]: row for row in records}
        refs = [self.db.collection("data").document(identifier) for identifier in by_id]
        missing = [doc.reference for doc in self.db.get_all(refs) if not doc.exists]
        for offset in range(0, len(missing), 200):
            batch = self.db.batch()
            for reference in missing[offset:offset + 200]:
                batch.create(reference, by_id[reference.id])
            batch.commit(timeout=30)
        return len(missing)

    def close(self):
        import firebase_admin
        self.db.close()
        firebase_admin.delete_app(self.app)
