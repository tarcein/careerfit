# CareerFit AI

프로젝트 원본 문서를 근거로 개인 경험 데이터베이스를 만들고, 사용자 검토와 승인 과정을 거쳐 신뢰할 수 있는 경력 정보를 축적하는 Streamlit MVP입니다.

현재 구현 범위는 Phase 4까지입니다.

- 프로필 저장
- PDF, PPTX, DOCX, TXT, MD 다중 업로드 및 텍스트 추출
- OpenAI Structured Output 기반 경험 추출
- 원본 근거 보존, 경험 수정, 직무별 활용 선호 저장
- 경험 버전 비교, 승인, 과거 버전 복원
- SQLite 영속화 및 AI 호출 로그
- JD 구조화 분석과 사용자 수정
- OpenAI embedding 또는 근거 중심 로컬 유사도
- 규칙 점수를 결합한 Verified 경험 TOP3 추천
- 추천 근거와 Strong/Partial/Missing Gap Analysis
- 이메일·비밀번호 로그인, 계정별 프로필 슬롯 및 데이터 분리
- 자기소개서 문항 의도 분석과 문항별 경험 TOP3 재추천
- 근거 기반 Essay Outline 생성·편집·버전 승인
- 승인 개요 기반 선택적 Draft 생성·편집·버전 저장
- 문장별 Verified/Needs Review/Unsupported Fact Check
- JD 반영률·문항 충족·수치·반복 경험·금지사항 품질 검사
- 누적 JD 역량 빈도·Gap·Verified 역량 Career Dashboard
- Ground Truth 기반 Top1·Precision@3·Recall@3·MRR 추천 평가

## 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run app.py
```

처음 접속하면 첫 계정을 생성합니다. 기존에 저장된 프로필과 지원 자료는 첫 계정에 자동으로 연결됩니다. 이후 가입한 계정은 별도의 `프로필 1`에서 시작하며 서로의 데이터를 볼 수 없습니다.

프로젝트 루트의 `.env` 파일에서 `OPENAI_API_KEY=` 뒤에 키를 붙여 넣으면 앱이 자동으로 읽습니다.

```dotenv
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-5.4-mini-2026-03-17
OPENAI_DRAFT_MODEL=gpt-5.4-2026-03-05
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

`.env`는 `.gitignore`에 포함되어 저장소에 커밋되지 않습니다. 일반 작업은 `OPENAI_MODEL`, 자기소개서 Draft는 `OPENAI_DRAFT_MODEL`을 사용합니다. 모델을 바꾼 후에는 Streamlit을 재시작하세요.

API 키가 없으면 문서별로 근거 문장을 보존하는 로컬 초안 추출기를 사용합니다. 실제 AI 구조화 품질을 확인하려면 API 키가 필요합니다.

업로드 제한은 파일당 200MB이며 `config.py`의 `MAX_UPLOAD_BYTES`에서 변경할 수 있습니다. 200MB를 넘기려면 Streamlit의 `server.maxUploadSize` 설정도 함께 높여야 합니다.

## Supabase 영구 저장

로컬에서는 기존 SQLite를 사용하고, `SUPABASE_DB_URL`이 설정된 환경에서는 Supabase PostgreSQL을 사용합니다. Render처럼 IPv4 기반인 환경에서는 Supabase 프로젝트의 `Connect`에서 **Session pooler(포트 5432)** 연결 문자열을 복사하세요.

```dotenv
SUPABASE_DB_URL=postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

연결 문자열은 `.env`와 Render의 Environment에만 저장하고 GitHub에는 올리지 마세요. 기존 로컬 데이터를 비어 있는 Supabase 프로젝트로 한 번 복사하려면 다음 명령을 실행합니다.

```powershell
python scripts/migrate_sqlite_to_supabase.py
```

복사가 끝난 뒤 같은 `SUPABASE_DB_URL`을 Render 환경변수에 등록하고 재배포하면 회원, 프로필, 경험, JD와 자기소개서 데이터가 재배포 후에도 유지됩니다.

## 테스트

```powershell
python -m unittest discover -s tests -v
```

상세 설계는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)를 참고하세요.
