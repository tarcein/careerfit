# CareerFit AI 설계

## 1. 전체 Architecture

CareerFit AI는 UI, 서비스, 데이터 계층을 분리한 단일 프로세스 MVP다. Streamlit은 입력과 검토만 담당하고, 문서 파싱과 AI 호출은 서비스 모듈, 영속화와 버전 관리는 SQLite 저장소가 담당한다.

```text
Streamlit UI
  -> Document Parser -> extracted_text
  -> AI Service -> Pydantic validated ExperienceData
  -> Repository -> SQLite + local uploads
  -> Review / Version / Approval workflow
```

핵심 경계는 다음과 같다.

- LLM: 문서 경험 추출과 사용자 요청을 반영한 경험 재구성
- Python: 파일 검증, 파싱, 저장, 상태 전이, 버전 관리, 데이터 검증
- SQLite: 원본 근거 불변성, 관계 무결성, 승인 버전 추적
- 사용자: AI 결과 수정 및 최종 승인

Phase 2의 `services/matching.py`와 JD 화면은 승인된 경험 저장 구조를 그대로 재사용한다. Phase 3은 같은 Verified 경험에 문항 의도를 더해 순위를 다시 계산하고, 선택한 경험으로 근거 기반 개요 버전을 만든다.

## 2. 폴더 구조

```text
CareerFit-AI/
├─ app.py                    # Streamlit 진입점과 5개 메뉴
├─ config.py                 # 경로·모델·업로드 제한
├─ models.py                 # Pydantic 핵심 데이터 모델
├─ db.py                     # SQLite 저장소와 버전 상태 전이
├─ schema.sql                # 전체 Phase를 고려한 관계형 스키마
├─ services/
│  ├─ document_parser.py     # PDF/PPTX/DOCX/TXT/MD 파싱
│  ├─ matching.py            # JD hybrid matching
│  ├─ question_matching.py   # JD + 문항 기반 재추천
│  └─ ai_service.py          # 구조화 출력, 로컬 fallback, 호출 로그
├─ prompts/
│  ├─ experience_extraction.py
│  ├─ experience_revision.py
│  ├─ jd_analysis.py
│  ├─ question_analysis.py
│  └─ essay_outline.py
├─ ui/
│  ├─ profile.py
│  ├─ experiences.py
│  ├─ jd_analyzer.py
│  └─ essay_planner.py
├─ data/                     # 런타임 DB와 업로드 파일(자동 생성)
├─ docs/ARCHITECTURE.md
└─ tests/
```

## 3. Database Schema

Phase 1의 중심 관계는 다음과 같다.

```text
users 1─1 profiles
users 1─N uploaded_files 1─N source_facts
users 1─N experiences 1─N experience_versions
experiences 1─N experience_corrections
experiences 1─N experience_preferences (target_role별)
experiences N─N uploaded_files (experience_sources)
experiences.current_version_id -> experience_versions.id
```

`source_facts`에는 UPDATE/DELETE 방지 트리거를 둔다. 수정 내용은 `experience_corrections`, 활용 지침은 `experience_preferences`, 결과 스냅샷은 `experience_versions`에 추가한다. 승인 시에만 `experiences.current_version_id`와 상태를 `Verified`로 바꾼다.

Phase 2~4 테이블(`job_descriptions`, `job_skills`, `essay_questions`, 매칭·개요·초안·팩트체크·평가)은 지금 생성해 추후 확장 시 마이그레이션을 최소화한다. 상세 컬럼과 제약은 `schema.sql`이 단일 기준이다.

## 4. 화면별 User Flow

### My Profile

기본 정보 입력 -> 저장 -> 이후 모든 분석의 기본 컨텍스트로 재사용.

### My Experiences

1. 여러 문서 업로드
2. 확장자/크기 검증 후 텍스트 추출 및 원문 파일 저장
3. OpenAI 또는 근거 보존형 로컬 추출로 경험 초안 생성
4. 경험 선택 후 원본 Evidence와 구조화 프로필 비교
5. 사실 수정, 금지 사항, 선호 강조점, 역할 구분 입력
6. 수동 새 버전 또는 AI 재구성 버전 생성
7. 이전/새 버전 비교 후 사용자 승인
8. 승인된 경험만 `Verified`

### JD Analyzer

JD 입력 -> 구조화 결과 검토·수정 -> Verified 경험 TOP3와 추천 근거 확인 -> Gap Analysis 확인.

### Essay Planner

1. JD를 선택하고 여러 자기소개서 문항과 글자 수를 저장
2. 문항 의도 분석 결과를 검토·수정
3. JD 45% + 문항 35% + Evidence 10% + 정량 결과 10%로 경험 TOP3 재추천
4. 경험을 선택해 원본 근거와 사용자 활용 지침을 반영한 개요 생성
5. 항목 순서·내용을 편집하거나 AI 수정 요청
6. 변경할 때마다 새 버전으로 저장하고 사용할 개요를 승인

### Career Dashboard

Verified 경험 역량과 누적 JD 요구 역량을 비교하고, 반복 요구 역량·Strong/Partial/Missing Gap을 표시한다. 사용자가 JD별 추천 정답 순위를 저장하면 Top1 Accuracy, Precision@3, Recall@3, MRR을 계산한다.

## 5. 핵심 데이터 모델

`ExperienceData`는 경험명, 기간, 역할, 문제·판단·행동·결과, 수치, 기술, 도메인, 키워드, 교훈, 원본 파일, Evidence, 개인/팀 역할 구분, 신뢰도를 검증한다. 모든 목록은 문자열 배열이며 신뢰도는 0~1이다.

저장 계층은 정보를 다음처럼 구분한다.

- `source_fact`: 원문에서 확인된 불변 사실
- `user_correction`: 사실관계 수정 요청
- `user_preference`: 직무별 활용 방향
- `do_not_use`: 출력에 포함하면 안 되는 정보
- `preferred_focus`: 특히 강조할 내용
- `ownership_notes`: 개인 역할과 팀 성과 구분
- `experience_profile`: 위 정보를 반영한 버전별 구조화 스냅샷

## 6. Phase 2 구현

1. JD 구조화용 Pydantic 모델과 사용자 수정 UI
2. `job_descriptions`, `job_skills` 저장
3. OpenAI embedding을 경험 승인 버전과 JD 단위로 캐시
4. cosine similarity + skill coverage + evidence 규칙 점수 계산
5. TOP3와 근거, Strong/Partial/Missing gap 표시

가중치는 `config.py` 상수로 관리한다. API 키가 없거나 embedding 호출이 실패하면 문자 n-gram 유사도를 사용하되 화면에 fallback 상태를 표시한다.

## 7. Phase 3 구현

1. 문항별 Pydantic 의도 분석과 사용자 수정
2. JD Fit 45, Question Fit 35, Evidence Quality 10, Quantitative Result 10 재추천
3. 문제해결·협업 등 문항 유형별 구조 충실도 평가
4. 지원동기는 기업·직무 관심과 경험의 연결을 우선하는 별도 점수·안내 적용
5. Verified 경험과 불변 Evidence만 사용하는 Essay Outline 생성
6. Outline 항목 추가·삭제·순서 변경·수동/AI 수정과 버전 승인

## 8. Phase 4 구현

1. 승인된 개요에서만 선택적으로 Draft 생성
2. Draft 직접 편집과 새 버전 저장
3. 원본 Evidence·승인 Experience Profile과 문장별 Fact Check
4. 근거 없는 수치·단독 수행 주장·do_not_use 위반을 Unsupported로 차단
5. JD 역량 반영률, 문항 구조, 정량 근거, 반복 경험, 키워드 과다 품질 검사
6. 누적 JD 요구 역량과 현재 경험 Gap Dashboard
7. 사용자 Ground Truth와 시스템 TOP3를 비교하는 추천 평가

사람인 API 연동은 access-key 승인 후 추가할 수 있는 외부 공고 수집 확장으로 분리한다.
