import threading
import time

from fastapi import APIRouter, Path, Query, Request, Response

from .models import ChatInput, ConversationInput, DataInput, Metric, now_iso
from .repository import ServiceError
from .summary import summarize

router = APIRouter(prefix="/api")
ID_PATTERN = r"^[A-Za-z0-9_-]{1,100}$"


class ChatRateLimit:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = {}

    def check(self, address):
        now = time.monotonic()
        with self.lock:
            self.requests = {ip: [stamp for stamp in stamps if now - stamp < 60] for ip, stamps in self.requests.items() if stamps and now - stamps[-1] < 60}
            stamps = self.requests.setdefault(address, [])
            if len(stamps) >= 12:
                raise ServiceError(429, "채팅은 1분에 12회까지 요청할 수 있습니다. 잠시 후 다시 시도해 주세요.")
            stamps.append(now)


@router.get("/health", tags=["상태"])
def health(request: Request):
    return {
        "status": "ok", "mode": request.app.state.settings.mode,
        "storage": "firestore" if request.app.state.settings.mode == "production" else "sqlite",
        "ai_provider": request.app.state.answerer.provider,
        "ai_model": request.app.state.settings.openai_model if request.app.state.answerer.provider == "openai" else None,
        "data_source": "synthetic",
    }


@router.get("/data/summary", tags=["데이터"], summary="전체 데이터에서 CPU·메모리 요약 계산")
def data_summary(request: Request):
    return summarize(request.app.state.repository.list("data"))


@router.get("/data", tags=["데이터"])
def list_data(request: Request, metric: Metric | None = None, limit: int = Query(100, ge=1, le=2000), offset: int = Query(0, ge=0)):
    rows = request.app.state.repository.list("data")
    if metric:
        rows = [row for row in rows if row["metric"] == metric]
    rows.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    return {"items": rows[offset:offset + limit], "total": len(rows), "limit": limit, "offset": offset}


@router.post("/data", status_code=201, tags=["데이터"])
def create_data(payload: DataInput, request: Request):
    return request.app.state.repository.create("data", payload.model_dump(mode="json"))


@router.put("/data/{identifier}", tags=["데이터"])
def update_data(payload: DataInput, request: Request, identifier: str = Path(pattern=ID_PATTERN)):
    return request.app.state.repository.replace("data", identifier, payload.model_dump(mode="json"))


@router.delete("/data/{identifier}", status_code=204, tags=["데이터"])
def delete_data(request: Request, identifier: str = Path(pattern=ID_PATTERN)):
    request.app.state.repository.delete("data", identifier)
    return Response(status_code=204)


@router.post("/conversations", status_code=201, tags=["대화 기록"], summary="대화 사본을 새 기록으로 저장")
def save_conversation(payload: ConversationInput, request: Request):
    timestamp = now_iso()
    return request.app.state.repository.create("conversations", {
        **payload.model_dump(mode="json"), "created_at": timestamp, "updated_at": timestamp,
        "version": 1, "provider": "saved-copy",
    })


@router.get("/conversations", tags=["대화 기록"], summary="대화 목록 (messages 미포함; 상세 API로 불러오기)")
def list_conversations(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    rows = sorted(request.app.state.repository.list("conversations"), key=lambda r: r["updated_at"], reverse=True)
    return {
        "items": [{key: value for key, value in row.items() if key != "messages"} | {"message_count": len(row["messages"])} for row in rows[offset:offset + limit]],
        "total": len(rows), "messages_included": False,
    }


@router.get("/conversations/{identifier}", tags=["대화 기록"])
def get_conversation(request: Request, identifier: str = Path(pattern=ID_PATTERN)):
    return request.app.state.repository.get("conversations", identifier)


@router.delete("/conversations/{identifier}", status_code=204, tags=["대화 기록"])
def delete_conversation(request: Request, identifier: str = Path(pattern=ID_PATTERN)):
    request.app.state.repository.delete("conversations", identifier)
    return Response(status_code=204)


@router.post("/chat", tags=["AI 채팅"])
def chat(payload: ChatInput, request: Request):
    state = request.app.state
    repo = state.repository
    existing = repo.get("conversations", payload.conversation_id) if payload.conversation_id else None
    history = existing["messages"] if existing else []
    if len(history) + 2 > 80:
        raise ServiceError(409, "대화가 길어졌습니다. 새 대화를 시작해 주세요.")
    state.rate_limit.check(request.client.host if request.client else "local")
    summary = summarize(repo.list("data"))
    answer = state.answerer.answer(payload.message, history, summary)
    timestamp = now_iso()
    exchange = [
        {"role": "user", "content": payload.message, "created_at": timestamp},
        {"role": "assistant", "content": answer, "created_at": now_iso()},
    ]
    document = {
        "title": existing["title"] if existing else payload.message[:60],
        "created_at": existing["created_at"] if existing else timestamp,
        "updated_at": now_iso(), "messages": history + exchange,
        "version": existing["version"] + 1 if existing else 1,
        "provider": state.answerer.provider,
    }
    stored = repo.replace("conversations", existing["id"], document, expected_version=existing["version"]) if existing else repo.create("conversations", document)
    return {"conversation_id": stored["id"], "message": exchange[-1], "provider": state.answerer.provider, "summary_count": summary["count"]}
