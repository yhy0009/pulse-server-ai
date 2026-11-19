# Pulse · 서버 메트릭 AI 비서

가상 서버 `demo-01`의 CPU·메모리 관측값을 관리하고, 계산된 통계를 근거로 대화하는 FastAPI + 바닐라 HTML/CSS/JavaScript 서비스입니다. 모든 관측값은 합성 데이터입니다.

## 실행 모드

프로젝트 루트의 `.env`에서 선택합니다. API 키를 입력하는 것과 실행 모드를 선택하는 것은 별개의 설정입니다.

| `APP_MODE` | 데이터 저장 | 채팅 | 필요한 인증정보 |
| --- | --- | --- | --- |
| `demo` | 로컬 SQLite | 통계 기반 예시 답변 | 없음 |
| `local` | 로컬 SQLite | 실제 GPT API | `OPENAI_API_KEY` |
| `production` | Firebase Firestore | 실제 GPT API | OpenAI 키 + Firebase 서비스 계정 |

`local`은 Firestore 준비 전에 GPT 연동을 확인하는 개발 모드입니다. 과제 제출 환경에서는 `production`과 Firestore를 사용합니다. 인증정보가 빠져도 예시 답변으로 자동 전환하지 않습니다.

## 로컬 실행

Python 3.10 이상이 필요하며, 이 작업공간에는 설치된 `.venv`가 있습니다. 새로운 환경이라면 Python 3.12로 가상환경을 만들고 `requirements.txt`를 설치합니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

처음 설정할 때만 `.env.example`을 `.env`로 복사합니다. 이미 키를 입력한 `.env`는 덮어쓰지 않습니다. GPT를 사용하려면 `.env`에 다음 두 값을 설정합니다.

```dotenv
APP_MODE=local
OPENAI_API_KEY=your_api_key_here
```

프로젝트 루트에서 실행합니다.

```bash
.venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000
```

- 서비스: <http://127.0.0.1:8000/>
- Swagger: <http://127.0.0.1:8000/docs>
- 설정 상태: <http://127.0.0.1:8000/api/health>

`.env`를 수정했으면 서버를 재시작하고 브라우저를 새로고침합니다. 과거의 예시 답변은 대화 기록에 그대로 남습니다. 새 대화를 시작하면 현재 설정으로 질문할 수 있습니다. `/api/health`는 사용하도록 설정된 모델과 저장소를 표시하며, 실제 API 호출 성공 여부는 채팅으로 확인합니다.

## 주요 환경변수

| 변수 | 용도 |
| --- | --- |
| `APP_MODE` | `demo`, `local`, `production` 중 하나 |
| `OPENAI_API_KEY` | 백엔드 전용 OpenAI API 키 |
| `OPENAI_MODEL` | 기본값 `gpt-4.1-mini` |
| `MAX_OUTPUT_TOKENS` | 기본값 1000, 허용 범위 128~2000 |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | 서비스 계정 JSON 전체. Render 환경변수에서 사용 |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | 로컬 서비스 계정 JSON 파일 경로. JSON 전체 값과 둘 중 하나 사용 |
| `ALLOWED_ORIGINS` | 쉼표로 구분한 프론트엔드 허용 주소 |
| `API_BASE_URL` | Vercel 빌드에 전달할 공개 백엔드 주소 |

`.env`와 `.local/`은 Git 업로드 제외 대상입니다. API 키와 서비스 계정 키는 브라우저 코드나 `API_BASE_URL`에 넣지 않습니다.

## 데이터와 Firestore

2026-11-01~2026-11-14 KST, 1시간 간격 CPU 336개와 메모리 336개를 제공합니다. `data/manifest.json`에 합성 조건과 해시가 있습니다. 로컬 모드는 첫 실행에만 데이터를 넣으며 재시작으로 사용자 수정·삭제를 되돌리지 않습니다.

Firestore의 Standard 에디션 `(default)` 데이터베이스와 서비스 계정을 준비하고, `.env`를 `production`으로 바꾼 뒤 다음 명령으로 원격 데이터에 등록합니다. 기존 ID의 데이터는 덮어쓰지 않습니다.

```bash
.venv/bin/python scripts/seed_firestore.py
```

컬렉션은 `data`와 `conversations`입니다. `local`의 대화 기록은 SQLite에 저장되며 Firestore로 자동 이전되지 않습니다.

## 검증과 배포

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check frontend/app.js
```

`render.yaml`은 FastAPI를 `production`으로 실행하는 배포 구성입니다. `vercel.json`과 `scripts/build-frontend.mjs`는 프론트엔드에 `API_BASE_URL`을 전달합니다. 실제 Render·Vercel 배포 URL과 제출용 스크린샷은 아직 준비되지 않았습니다.
