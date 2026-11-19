# Pulse 배포 구성

소스 저장소: <https://github.com/yhy0009/pulse-server-ai> (비공개)

## 실제 배포 결과

2026-11-19 배포 및 HTTP/API 검증 완료:

- 서비스: <https://pulse-server-ai.vercel.app>
- 백엔드: <https://pulse-server-ai.onrender.com>
- Swagger: <https://pulse-server-ai.onrender.com/docs>
- 검증 기록: [evidence/deployment-checks.json](evidence/deployment-checks.json)

Render는 GitHub의 `codex/deploy` 브랜치에 연결되어 자동 배포합니다. 문서만 수정할 때는 커밋 메시지에 `[skip render]`를 넣으면 실행 중인 서비스를 다시 빌드하지 않습니다.

Vercel은 `frontend` 폴더에서 공식 CLI로 배포했습니다. Vercel의 GitHub 자동 배포 연결은 아직 설정하지 않았습니다. 코드를 바꾸면 해당 폴더에서 `vercel deploy --prod`로 프론트엔드를 다시 배포합니다.

## Render 백엔드

| 항목 | 설정 |
| --- | --- |
| 서비스 | `pulse-server-ai` |
| 유형 | Python Web Service |
| 플랜 | `free` |
| 리전 | `singapore` |
| Git 브랜치 | `codex/deploy` |
| 루트 디렉터리 | 저장소 루트 |
| Python | `3.12.14` |
| 빌드 | `pip install -r requirements.txt` |
| 시작 | `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
| Health check | `/api/health` |
| 실제 백엔드 주소 | `https://pulse-server-ai.onrender.com` |

비공개 저장소에 접근할 수 있도록 Render에 해당 GitHub 저장소 읽기 권한을 연결합니다. `render.yaml`의 구성은 Render Blueprint 검증을 통과했습니다.

다음 값은 Render 서버의 환경변수로 설정합니다. 비공개 값은 소스 저장소에 포함하지 않습니다.

| 환경변수 | 값 또는 입력 위치 |
| --- | --- |
| `APP_MODE` | `production` |
| `PYTHON_VERSION` | `3.12.14` |
| `OPENAI_MODEL` | `gpt-4.1-mini` |
| `MAX_OUTPUT_TOKENS` | `1000` |
| `ALLOWED_ORIGINS` | `https://pulse-server-ai.vercel.app` |
| `OPENAI_API_KEY` | 소유자가 승인한 API 키를 Render 환경변수에 등록 |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | 소유자가 승인한 서비스 계정 JSON 전체를 Render 환경변수에 등록 |

로컬 컴퓨터의 서비스 계정 파일 경로는 Render에서 사용할 수 없습니다. 배포 환경에서는 JSON 전체를 환경변수로 전달합니다. 키를 입력한 뒤 서버를 배포해야 실제 GPT·Firestore 기능을 사용할 수 있습니다.

## Firestore

Firebase 프로젝트 `pulse-server-ai`, Standard 에디션의 `(default)` 데이터베이스를 사용합니다. 데이터베이스는 서울 리전 `asia-northeast3`의 Firestore Native 모드입니다.

초기 합성 데이터는 CPU 336개와 메모리 336개, 총 672개입니다. 2026-11-19에 `data` 컬렉션에 등록했습니다. 대화를 보내면 `conversations` 컬렉션에 기록됩니다. 로컬 SQLite 대화 기록은 자동 이전하지 않습니다.

## Vercel 프론트엔드

| 항목 | 설정 |
| --- | --- |
| 프로젝트 | `pulse-server-ai` |
| 할당된 프로덕션 도메인 | `https://pulse-server-ai.vercel.app` |
| 프로젝트 루트 | `frontend` |
| 프레임워크 | Other / 프레임워크 없음 |
| 빌드 | `node build.mjs` |
| 출력 | `dist` |
| 환경변수 | `API_BASE_URL=https://pulse-server-ai.onrender.com` |

Vercel 배포는 `READY`이며, 프로덕션 도메인의 HTML·JavaScript·CSS와 Render 주소 설정이 모두 인증 없이 HTTP 200으로 응답하는 것을 확인했습니다. CLI 업로드 소스가 `frontend`이므로 서버 빌드에서 이 폴더의 내용이 프로젝트 루트가 됩니다. 추후 GitHub 저장소 전체를 Vercel에 연결할 때는 Root Directory를 `frontend`로 지정합니다.

프론트엔드 빌드 출력에는 `index.html`, `style.css`, `app.js`, `config.js`만 포함됩니다. 테스트용 비밀값을 환경변수에 넣어도 정적 출력에 포함되지 않는 것을 검증했습니다. GPT 키와 서비스 계정 키는 Vercel에 등록하지 않습니다.

## 배포 후 검증

1. 프론트엔드의 `/config.js`에서 Render의 실제 주소가 설정되었는지 확인합니다.
2. 백엔드의 `/api/health`가 `mode=production`, `storage=firestore`, `ai_provider=openai`를 반환하는지 확인합니다.
3. 백엔드 `/api/data/summary`에서 전체 개수 672와 계산된 통계를 확인합니다. Health 응답만으로 DB 연결을 검증했다고 판단하지 않습니다.
4. 백엔드 `/docs`가 열리고, 프론트엔드 주소의 CORS 요청이 허용되는지 확인합니다.
5. 새 테스트 관측값을 추가·수정·삭제한 뒤 데이터 개수가 원래대로 돌아오는지 확인합니다.
6. 질문을 보내 실제 GPT 답변을 받고, 생성된 대화를 Firestore에서 다시 조회합니다.
7. 실제 서비스에서 채팅·데이터 관리·대화 불러오기 스크린샷을 촬영합니다.

Render의 첫 요청 지연에 대한 안내는 프론트엔드에 포함되어 있습니다.
