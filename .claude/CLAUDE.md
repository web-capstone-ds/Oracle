# CLAUDE.md — DS Oracle 판정 엔진 서버 개발 지시 명세서

> **작성자**: 수석 아키텍트
> **수신자**: Claude Code
> **버전**: v1.0 (2026-04-21)
> **작업 성격**: Python (asyncio) Oracle 판정 엔진 서버 코드 작성
> **저장소**: oracle (Oracle 서버 전용)

---

## 0. 프로젝트 컨텍스트

### 0.1 너의 역할
너는 15년 차 제조 IT(MES/스마트 팩토리) 도메인의 수석 개발자로서, DS 주식회사 비전 검사 장비의 **Oracle 판정 엔진 서버**를 Python으로 구현한다. 이 서버는 Broker에서 LOT_END 이벤트를 직접 구독하고, Historian TSDB에서 해당 LOT의 INSPECTION_RESULT를 일괄 조회하여, Rule-based 1차 검증을 수행하는 **Local Area 내 판정 엔진**이다.

### 0.2 프로젝트의 본질
- 망 분리된 반도체 후공정 공장 현장에서, N대의 비전 검사 장비(EAP)를 모니터링
- 통신: MQTT v5.0 (Eclipse Mosquitto 2.x) over Local Wi-Fi
- 핵심 가치: **MARGINAL 구간 감지** + **장비 열화 징후 포착**
- Oracle은 **"판정"만** 수행한다. 데이터 적재(Historian), 실시간 모니터링(모바일), 중앙 제어(MES), 보안 전송(Dispatcher), AI 분석(AI 서버)은 다른 서버의 책임

### 0.3 시스템 내 위치

```
가상 EAP 서버 (C#, MQTTnet)
        │
        │  MQTT Publish (8종 이벤트, JSON)
        ▼
   Eclipse Mosquitto Broker (로컬 Wi-Fi)
        │
        ├──→ 모바일 앱 (Flutter) ── 실시간 N:1 타일 모니터링
        ├──→ Historian 서버 (Node.js/TimescaleDB) ── 시계열 적재
        ├──→ Oracle 서버 (본 프로젝트) ←── 너가 만드는 것
        │        │
        │        ├── LOT_END 직접 구독 (트리거)
        │        ├── Historian TSDB 경유 일괄 조회 (INSPECTION_RESULT)
        │        └── ORACLE_ANALYSIS 발행 (판정 결과)
        │
        └──→ MES 서버 (C#) ── 중앙 제어
```

### 0.4 작업 시작 전 필독 문서

작업을 시작하기 전에 **반드시 아래 문서를 순서대로 읽어서 컨텍스트를 머릿속에 적재**한다. 이걸 건너뛰면 Rule 판정 로직, MQTT 정책, Historian 연동 쿼리를 잘못 구현할 위험이 있다.

1. **`./명세서/Oracle_작업명세서.md`** — **Oracle 서버 작업 명세서 (1차 구현 설계도)** ★
   - 1차 검증 Rule-based 판정 트리거 시퀀스, 38개 Rule 판정 등급 결정 로직
   - Rule DB 스키마, 인메모리 캐시 4종, Historian TSDB 조회 쿼리 패턴
   - 프로젝트 구조, 환경변수, Docker Compose, 검증 체크리스트
   - 2차 검증 확장 인터페이스 스텁 설계
   - ⚠️ **이 문서가 Oracle 구현의 직접적인 설계도**. 코드 작성 전 반드시 전체 통독

2. **`../DS-Document/명세서/DS_EAP_MQTT_API_명세서.md`** — MQTT API 전체 명세 (v3.4 확정, **충돌 시 최우선 문서**)
   - 8종 이벤트 페이로드 필드 정의, QoS/Retained 정책
   - Rule 38개 판정 기준표 (§11), ORACLE_ANALYSIS 페이로드 구조 (§8)
   - Retained Message 정책 (§1.1.1), 알람 ACK 빈 페이로드 clear (§6.6)

3. **`../EAP_VM/명세서/eap-spec-v1.md`** — 가상 EAP 작업 명세서
   - Mock 데이터 27종 인덱스, 이벤트 시퀀스, 비정상 시나리오
   - ALARM_ACK 빈 페이로드 clear 메커니즘

4. **`../DS-Document/명세서/DS_이벤트정의서.md`** — 5대분류 / 15소분류 / 38 Rule 이벤트 분류 체계
   - Rule R01~R38c 판정 기준, Oracle 연동 인터페이스 (§9)

5. **`../DS-Document/문서/오라클 2차 검증 기획안.md`** — 2차 검증 설계 전체
   - Rule DB 구조, 판정 3단계, 레시피별 독립 학습, EWMA+MAD / Isolation Forest 설계

6. **`../Historian/명세서/Historian_작업명세서.md`** — Historian TSDB 스키마, Oracle 데이터 공급 쿼리 패턴 (§3.3)
   - Oracle이 Historian에 요구하는 5종 쿼리 패턴 정합성 확인

> **💡 Claude Code 사용 패턴**: 작업 전에 `./명세서/Oracle_작업명세서.md`, `../DS-Document/명세서/DS_EAP_MQTT_API_명세서.md`, `../DS-Document/명세서/DS_이벤트정의서.md`, `../Historian/명세서/Historian_작업명세서.md`를 순서대로 읽고 컨텍스트를 적재하라.

### 0.5 문서 간 충돌 시 우선순위

> **API 명세서 v3.4 > Oracle 작업명세서 v1.1 > eap-spec-v1 > 이벤트 정의서 v1.0**

### 0.6 인접 저장소 구조 (필수 전제)

이 저장소(Oracle)는 DS-Document, Historian 저장소의 문서와 Mock 데이터를 **상대경로로 직접 참조**한다. 파일을 복사하지 않는다. 아래 디렉토리 구조가 갖춰져 있어야 한다. 없으면 작업을 시작하지 말고 사용자에게 알려라.

```
C:\Hansung_Project\WebCapstone\        ← 공통 부모 디렉토리
├── DS-Document/                       ← 문서·Mock 원본 저장소
│   ├── 명세서/
│   │   ├── DS_EAP_MQTT_API_명세서.md   ← MQTT API 전체 명세 v3.4
│   │   └── DS_이벤트정의서.md           ← 이벤트 분류 체계 + Rule 38개
│   ├── 문서/
│   │   ├── 기획안.md                   ← 시스템 아키텍처
│   │   └── 오라클 2차 검증 기획안.md    ← 2차 검증 설계 전체
│   └── EAP_mock_data/
│       ├── 01_heartbeat.json ~ 27_control_alarm_ack_burst.json
│       ├── README.md
│       └── scenarios/
│           └── multi_equipment_4x.json
├── EAP_VM/                            ← 가상 EAP 서버 (C#)
│   └── 명세서/
│       └── eap-spec-v1.md             ← 가상 EAP 서버 작업 명세서
├── Historian/                         ← Historian 서버 (Node.js/TypeScript)
│   └── 명세서/
│       └── Historian_작업명세서.md      ← Historian TSDB 스키마 + 쿼리 패턴
├── Oracle/                            ← 이 저장소 (Oracle 개발) ★
│   ├── .claude/
│   │   └── CLAUDE.md                  ← 이 파일
│   └── 명세서/
│       └── Oracle_작업명세서.md         ← Oracle 1차 설계도 ★
├── mosquitto_config/                  ← Broker 설정
└── MQTT/                             ← MQTT 관련
```

> **주의:** DS-Document, Historian의 문서와 Mock 데이터는 읽기 전용 참조 자원이다. Oracle에서 직접 수정하지 말 것. 원본 수정이 필요하면 해당 저장소에서 수정한다.

---

## 1. 작업 원칙 (모든 Task 공통)

### 1.1 기술 스택 고정

| 항목 | 기술 | 이유 |
|:---|:---|:---|
| 언어 | Python 3.11+ | 기획서 확정 스택 |
| MQTT 라이브러리 | paho-mqtt v2.x | Python 표준 MQTT 클라이언트. MQTT v5.0, QoS 2 지원 |
| DB 드라이버 | psycopg[binary] 3.x | PostgreSQL 비동기 지원, 커넥션 풀링 |
| 비동기 프레임워크 | asyncio | MQTT 수신 + DB 조회 비동기 처리 |
| 설정 관리 | python-dotenv + pydantic-settings | .env 파일 기반 + 타입 안전 설정 |
| 로깅 | structlog | 구조적 JSON 로깅 |
| 테스트 | pytest + pytest-asyncio | 비동기 테스트 지원 |
| 컨테이너 | Docker + Docker Compose | Historian/Broker와 동일 네트워크 |

### 1.2 MQTT 정책 필수 준수 (코드에 반드시 반영)

#### 1.2.1 구독 QoS 정책

| QoS | 대상 토픽 | 이유 |
|:---|:---|:---|
| QoS 1 | `ds/+/status` | 주기적 발행, 1회 누락 허용 |
| QoS 2 | `ds/+/lot`, `ds/+/alarm`, `ds/+/recipe` | 정확히 1회 전달 보장 필수 |

> **INSPECTION_RESULT 직접 구독 안 함**: Oracle은 Historian TSDB를 경유하여 LOT 단위로 일괄 조회한다. 실시간 처리 부하에서 자유로워 복잡한 분석을 수행하기 위함이다.

#### 1.2.2 발행 QoS 정책

| QoS | 대상 토픽 | Retained |
|:---|:---|:---|
| QoS 2 | `ds/{eq}/oracle` | ✅ true |

#### 1.2.3 세션 정책

```python
# paho-mqtt v2 연결 옵션 필수 설정
client.connect(
    host=broker_host,
    port=broker_port,
    clean_start=False,          # 세션 유지, 재연결 시 큐 보존
    properties=Properties(PacketTypes.CONNECT),  # session_expiry=3600
    keepalive=60,
)
# Will 메시지 없음 — Oracle은 Subscribe + oracle Publish만. 
# EAP 전용 Will(HW_ALARM EAP_DISCONNECTED)은 EAP 서버 책임
```

#### 1.2.4 ACL 계정 정책

| 항목 | 값 |
|:---|:---|
| 계정 | `oracle` |
| Subscribe 허용 | `ds/+/lot`, `ds/+/alarm`, `ds/+/recipe`, `ds/+/status` |
| Publish 허용 | `ds/+/oracle` |

> **주의:** `oracle` 계정으로 lot/alarm/recipe/status 이외 토픽 Subscribe 또는 oracle 이외 토픽 Publish 시도 금지 (ACL 위반).

#### 1.2.5 재연결 백오프

```
1s → 2s → 5s → 15s → 30s, max 60s, jitter ±20%
```

paho-mqtt 내장 재연결 대신 **커스텀 백오프 + jitter** 로직 구현. `utils/backoff.py`에 분리.

#### 1.2.6 빈 페이로드 처리

ALARM_ACK 시 EAP가 `ds/{eq}/alarm` 토픽에 빈 페이로드 + Retain=true를 발행하여 retained message를 clear한다. Oracle은 **빈 페이로드 수신 시 무시**해야 한다. 이것은 Broker의 retained 상태를 정리하는 제어 신호일 뿐이다.

### 1.3 절대 금지 사항

- ❌ **실로그 기반 Mock(01~17)의 수치 변경 금지** — Carsem 14일 실측값
- ❌ **Rule 38개 번호 재배치 금지** — R01~R38c는 외부에서 참조됨. 새 Rule은 R39부터 부여
- ❌ **기존 8개 토픽 패턴 변경 금지** — `ds/{eq}/heartbeat` 등 구조 유지
- ❌ **PascalCase ↔ snake_case 무단 변환 금지** — `inspection_detail` 내부는 PascalCase, 그 외는 snake_case
- ❌ **`oracle` 계정으로 허용되지 않은 토픽 Publish/Subscribe 금지** (ACL 위반)
- ❌ **R38a(Isolation Forest), R38b(EWMA 이탈)를 1차 검증에서 활성화 금지** — 2차 검증 모듈 활성화 전까지 판정에서 제외
- ❌ **`timestamp`에 `datetime.now()` 또는 로컬 시간 사용 금지** — ISO 8601 UTC 밀리초(`.fffZ`) 필수
- ❌ **`saw_process` 필드 부활 금지** — README.md 제외 정책 준수

### 1.4 필수 준수 사항

- ✅ 2차 검증의 존재를 코드 구조와 DB 스키마에 미리 반영하되, 1차 검증만으로 완결성 있는 판정 결과 발행
- ✅ ORACLE_ANALYSIS 페이로드는 Mock 23~25번과 구조 호환
- ✅ ORACLE_ANALYSIS 페이로드에 `equipment_status` 필드 **포함하지 않음** (HEARTBEAT/CONTROL_CMD/ORACLE_ANALYSIS 제외 규칙, 작업명세서 §5.1)
- ✅ `inspection_detail` 내부 PascalCase 유지 (GVisionWpf 원본 구조)
- ✅ 메시지 ID는 UUID v4 (RFC 4122), Timestamp는 ISO 8601 UTC 밀리초 (`.fffZ`)
- ✅ Historian 연동 쿼리: 기본 5종(O5) + 알람 보정 2종(O7에서 R33/R34용 추가) = 총 7종
- ✅ 모든 Task 완료 후 `git diff --stat`로 변경 파일 수와 라인 수를 보고할 것

### 1.5 검증 체크포인트

각 Task 끝에 **자기 검증 체크리스트**가 있다. 한 Task의 체크리스트를 모두 통과하지 못한 채로 다음 Task로 넘어가지 말 것.

---

## 2. Task 실행 순서 (O1 → O10)

의존성에 따라 아래 순서로 진행한다. **각 Task 끝에 검증 체크리스트를 통과해야 다음 Task로.**

| 순서 | Task ID | 제목 | 우선순위 | 예상 | 의존성 |
|:---|:---|:---|:---|:---|:---|
| 1 | O1 | 프로젝트 초기화 + MQTT 연결 | P0 | 0.5일 | 없음 |
| 2 | O2 | MQTT 구독 핸들러 (4종 이벤트) | P0 | 0.5일 | O1 |
| 3 | O3 | 인메모리 캐시 4종 | P0 | 0.5일 | O2 |
| 4 | O4 | Rule DB 스키마 + 시딩 | P0 | 0.5일 | 없음 |
| 5 | O5 | Historian TSDB 조회 모듈 | P0 | 0.5일 | O4, Historian 기동 |
| 6 | O6 | Rule 판정 엔진 (LOT-level + Unit-level) | P0 | 1일 | O3, O4, O5 |
| 7 | O7 | Rule 판정 엔진 (Alarm + Recipe + Status) | P1 | 1일 | O3, O4, O6 |
| 8 | O8 | ORACLE_ANALYSIS 발행 | P0 | 0.5일 | O6, O7 |
| 9 | O9 | 2차 검증 확장 인터페이스 스텁 | P2 | 0.5일 | O6 |
| 10 | O10 | 통합 테스트 + Graceful Shutdown | P1 | 1일 | O1~O9 전체 |

> **주의:** O6(LOT-level + Unit-level)과 O7(Alarm + Recipe + Status)은 판정 엔진의 두 축이다. O6이 핵심 판정 로직(수율, 검사 품질)이고, O7은 보조 판정(알람 카운터, 레시피 검증, 상태 전환)이다. O6 없이 O7을 진행하지 말 것.

---

## 3. Task O1 — 프로젝트 초기화 + MQTT 연결

### 3.1 작업 목표
Python 프로젝트 구조 생성, paho-mqtt v2 연결 관리자 구현, 재연결 백오프 로직.

### 3.2 핵심 구현 사항

- `pyproject.toml`: paho-mqtt, psycopg[binary], pydantic-settings, structlog, pytest
- `src/config.py`: pydantic Settings — Broker 주소/포트, DB 접속 정보, 백오프 단계, 타이밍
- `src/mqtt/client.py`: paho-mqtt v2 연결 관리
  - `clean_start=False`, `session_expiry=3600`, `keepalive=60`
  - Will 메시지 없음 (Oracle은 Publisher 전용 Will 불필요)
- `src/utils/backoff.py`: 커스텀 재연결 백오프 `[1, 2, 5, 15, 30, 60]`, jitter ±20%
- `.env.example`: 전 환경변수 항목 포함

### 3.3 검증 체크리스트
- [ ] 프로젝트 의존성 설치 성공 (`pip install -e .` 또는 `pip install -r requirements.txt`)
- [ ] Mosquitto 로컬 Broker에 연결 성공 로그 출력
- [ ] 의도적 Broker 중단 → 재연결 백오프 로그 확인 (1s→2s→5s→15s→30s)
- [ ] jitter가 ±20% 범위 내에서 동작 확인
- [ ] `.env.example` 파일에 MQTT_BROKER_HOST, MQTT_BROKER_PORT, ORACLE_DB_HOST, HISTORIAN_DB_HOST 등 전 항목 포함

### 3.4 Git 커밋 메시지
```
feat(oracle): 프로젝트 초기화 + MQTT 연결 (O1)

- Python 3.11+ 프로젝트 스캐폴딩
- paho-mqtt v2: 연결/재연결/백오프(1s→60s, jitter ±20%)
- pydantic Settings: 환경변수 타입 안전 로딩
- structlog: 구조적 JSON 로깅
```

---

## 4. Task O2 — MQTT 구독 핸들러 (4종 이벤트)

### 4.1 작업 목표
LOT_END, HW_ALARM, RECIPE_CHANGED, STATUS_UPDATE 구독 핸들러 구현.

### 4.2 핵심 구현 사항

- `src/mqtt/subscriber.py`: 4종 토픽 구독 + 핸들러 라우팅
  - `ds/+/lot` → `handle_lot_end()` (QoS 2)
  - `ds/+/alarm` → `handle_alarm()` (QoS 2)
  - `ds/+/recipe` → `handle_recipe_changed()` (QoS 2)
  - `ds/+/status` → `handle_status_update()` (QoS 1)
- `src/models/events.py`: LOT_END, HW_ALARM, RECIPE_CHANGED, STATUS_UPDATE DTO (pydantic)
- 빈 페이로드 수신 시 무시 (ALARM_ACK retained clear 신호)

### 4.3 검증 체크리스트
- [ ] Mock 09(LOT_END) 수신 + 파싱 로그 확인
- [ ] Mock 11(HW_ALARM) 수신 + 파싱 로그 확인
- [ ] Mock 18(RECIPE_CHANGED) 수신 + 파싱 로그 확인
- [ ] Mock 02(STATUS_UPDATE) 수신 + 파싱 로그 확인
- [ ] 빈 페이로드 수신 → 무시 로그 (에러 아님)
- [ ] INSPECTION_RESULT(`ds/+/result`) 구독하지 않음 확인

### 4.4 Git 커밋 메시지
```
feat(oracle): MQTT 구독 핸들러 4종 (O2)

- LOT_END (QoS 2): 1차 검증 트리거
- HW_ALARM (QoS 2): 알람 카운터 보조
- RECIPE_CHANGED (QoS 2): Rule DB 캐시 갱신
- STATUS_UPDATE (QoS 1): 장비 상태 캐시
- 빈 페이로드 무시 (ALARM_ACK retained clear)
```

---

## 5. Task O3 — 인메모리 캐시 4종

### 5.1 작업 목표
장비 상태 캐시, 알람 카운터, LOT 이력, Rule DB 캐시 구현.

### 5.2 핵심 구현 사항

- `cache/equipment_cache.py`: 장비별 상태, recipe_id, operator_id, 마지막 상태 전환 시각
- `cache/alarm_counter.py`: 장비별 `hw_error_code` → 일간 카운트 (R26/R33/R34 보조)
- `cache/lot_history.py`: 장비별 최근 N LOT 이력 (수율 추이 참조)
- `cache/rule_cache.py`: Rule DB 임계값 캐시 (TTL 기반 갱신, 레시피별 독립)

### 5.3 검증 체크리스트
- [ ] STATUS_UPDATE 수신 → equipment_cache 갱신 확인
- [ ] HW_ALARM 수신 → alarm_counter 증분 확인
- [ ] LOT_END 수신 → lot_history 추가 확인
- [ ] Rule DB 캐시 TTL 만료 → DB 재조회 + 갱신 로그 확인
- [ ] 4대 장비 동시 구동 시 각 장비 캐시 독립 유지

### 5.4 Git 커밋 메시지
```
feat(oracle): 인메모리 캐시 4종 (O3)

- equipment_cache: 장비 상태/recipe_id/operator_id
- alarm_counter: hw_error_code별 일간 카운트
- lot_history: 장비별 최근 N LOT 이력
- rule_cache: Rule DB 임계값 TTL 캐시
```

---

## 6. Task O4 — Rule DB 스키마 + 시딩

### 6.1 작업 목표
rule_thresholds, rule_change_history, oracle_judgments 테이블 생성 + 기본 임계값 시딩.

### 6.2 핵심 구현 사항

- `sql/01_create_rule_tables.sql`: rule_thresholds 테이블 (Oracle 작업명세서 §5 참조)
- `sql/02_seed_default_thresholds.sql`: 36개 Rule 기본 임계값 시딩 (R38a/R38b 제외)
- `sql/03_create_judgment_table.sql`: oracle_judgments 테이블 (판정 이력)
- `src/db/pool.py`: psycopg 커넥션 풀
- `src/db/rule_db.py`: Rule DB CRUD (조회, 임계값 갱신)
- 2차 검증 확장 컬럼 포함: `lot_basis`, `approved_by`, `rule_change_history` 테이블

### 6.3 검증 체크리스트
- [ ] Docker Compose로 DB 기동 성공
- [ ] `psql`로 접속 → rule_thresholds 테이블 존재 확인
- [ ] 시딩 데이터 36개 Rule 확인 (R38a/R38b 제외)
- [ ] oracle_judgments 테이블 존재 확인
- [ ] rule_change_history 테이블 존재 확인
- [ ] SQL을 두 번 실행해도 에러 없음 (`IF NOT EXISTS` 방어)

### 6.4 Git 커밋 메시지
```
feat(oracle): Rule DB 스키마 + 시딩 (O4)

- rule_thresholds: 36개 Rule 임계값 + 2차 검증 확장 컬럼
- rule_change_history: 임계값 변경 이력 (2차 검증 준비)
- oracle_judgments: 판정 결과 이력
- 기본 임계값 시딩: Carsem_3X3 기준
```

---

## 7. Task O5 — Historian TSDB 조회 모듈

### 7.1 작업 목표
LOT별 INSPECTION_RESULT 일괄 조회, 레시피별 수율 시계열, 알람 카운터 보정 조회 구현.

### 7.2 핵심 구현 사항

- `src/db/historian_queries.py`: Historian TSDB 조회 쿼리 5종 (Historian 작업명세서 §3.3 참조)
  1. LOT별 INSPECTION_RESULT 일괄 조회: `WHERE lot_id = ? AND equipment_id = ?`
  2. 레시피별 최근 N LOT 수율 시계열: `WHERE recipe_id = ? ORDER BY time DESC LIMIT N`
  3. 레시피별 LOT 3개 평균 total_units: `WHERE recipe_id = ? LIMIT 3`
  4. 레시피별 ET 분포 통계: `GROUP BY recipe_id, error_type`
  5. 장비별 알람 이력: `WHERE equipment_id = ? AND event_type = 'HW_ALARM'`

### 7.3 검증 체크리스트
- [ ] Historian에 Mock 데이터 적재 후, LOT-20260122-001 조회 → 2,792건 반환 확인
- [ ] 레시피별 최근 3 LOT 평균 total_units → ~2,792 확인
- [ ] 레시피별 수율 시계열 → 28 LOT 반환 확인 (Carsem_3X3)
- [ ] 장비별 알람 이력 조회 → hw_error_code, alarm_level 정상
- [ ] Historian DB 연결 실패 시 재시도 + 에러 로그 (판정 중단, 크래시 아님)

### 7.4 Git 커밋 메시지
```
feat(oracle): Historian TSDB 조회 모듈 (O5)

- 5종 쿼리: LOT별 결과/수율 시계열/평균 units/ET 분포/알람 이력
- psycopg 비동기 커넥션 풀
- Historian 연결 실패 시 에러 로그 + 판정 스킵 (크래시 방지)
```

---

## 8. Task O6 — Rule 판정 엔진 (LOT-level + Unit-level)

### 8.1 작업 목표
LOT-level Rules(R23, R24, R25, R35) + Unit-level Rules(R02~R22, R36, R37) 구현.

### 8.2 핵심 구현 사항

- `engine/lot_rules.py`: R23(수율 등급), R24(LOT 소요시간), R25(LOT 강제 종료), R35(ET=52 비율)
- `engine/unit_rules.py`: R02~R22(검사 품질 Rule 전체), R36(kerf_width), R37(marking_quality)
- `engine/rule_engine.py`: 메인 오케스트레이터 — LOT_END 수신 → TSDB 조회 → Rule 판정 → 등급 결정
- 판정 등급 결정: `DANGER > WARNING > NORMAL` (최고 심각도 Rule이 최종 등급 결정)

### 8.3 검증 체크리스트
- [ ] Mock 09(정상 LOT, yield 96.2%, COMPLETED) → NORMAL
- [ ] Mock 10(ABORTED, yield 94.2%) → WARNING (R25)
- [ ] Mock 05(ET=52 전수 FAIL) 기반 → DANGER (R08, R09)
- [ ] yield_pct = 98.5% → NORMAL (세분류 EXCELLENT)
- [ ] yield_pct = 93.0% → WARNING (R23, 세분류 WARNING)
- [ ] yield_pct = 85.0% → WARNING (R23, 세분류 MARGINAL)
- [ ] yield_pct = 75.0% → DANGER (R23, 세분류 CRITICAL)
- [ ] chipping_top_um = 55.0 → DANGER (R13)
- [ ] blade_wear_index = 0.75 → WARNING (R16)

### 8.4 Git 커밋 메시지
```
feat(oracle): Rule 판정 엔진 — LOT-level + Unit-level (O6)

- lot_rules: R23(수율 등급), R24(소요시간), R25(강제 종료), R35(ET=52)
- unit_rules: R02~R22(검사 품질), R36(kerf), R37(marking)
- rule_engine: 오케스트레이터 — 최고 심각도 등급 결정
```

---

## 9. Task O7 — Rule 판정 엔진 (Alarm + Recipe + Status)

### 9.1 작업 목표
Alarm-level Rules(R26~R29, R33, R34) + Recipe Rules(R30, R31, R32) + Status Rules(R01, R38c) 구현.

### 9.2 핵심 구현 사항

- `engine/alarm_rules.py`: R26(CAM_TIMEOUT 다발), R27~R29(알람 빈도), R33(AggEx 패턴), R34(알람 연쇄)
- `engine/recipe_rules.py`: R30(레시피 미등록), R31(숫자형 레시피 ID), R32(레시피 버전 불일치)
- `engine/status_rules.py`: R01(Heartbeat 누락), R38c(비정상 상태 전환 RUN→STOP 무경고)

### 9.3 검증 체크리스트
- [ ] CAM_TIMEOUT daily_count = 4 → DANGER (R26)
- [ ] recipe_id = "446275" (숫자형) → DANGER (R31)
- [ ] RUN → STOP (무경고 전환) → DANGER (R38c)
- [ ] VISION_SCORE_ERR + LotController 키워드 5건/일 → DANGER (R33)
- [ ] LIGHT_PWR_LOW → SIDE ET=52 비율 상승 → WARNING → DANGER (연쇄 상향)

### 9.4 Git 커밋 메시지
```
feat(oracle): Rule 판정 엔진 — Alarm + Recipe + Status (O7)

- alarm_rules: R26~R29(알람 빈도), R33(AggEx), R34(연쇄)
- recipe_rules: R30(미등록), R31(숫자형 ID), R32(버전 불일치)
- status_rules: R01(Heartbeat 누락), R38c(비정상 전환)
```

---

## 10. Task O8 — ORACLE_ANALYSIS 발행

### 10.1 작업 목표
판정 결과를 ORACLE_ANALYSIS 페이로드로 직렬화하여 `ds/{eq}/oracle`에 발행.

### 10.2 핵심 구현 사항

- `src/mqtt/publisher.py`: ORACLE_ANALYSIS 발행 (QoS 2, Retained=true)
- `src/models/oracle_analysis.py`: ORACLE_ANALYSIS 발행 DTO (Mock 23~25 구조 호환)
- `src/engine/comment_generator.py`: ai_comment 템플릿 생성기 (판정 근거 요약)
- 2차 검증 필드 (`threshold_proposal`, `isolation_forest_score`)는 v1.0에서 null

### 10.3 검증 체크리스트
- [ ] LOT_END 수신 → 판정 → ORACLE_ANALYSIS 발행 (`mosquitto_sub`로 확인)
- [ ] 페이로드 구조가 Mock 23~25와 호환 (JSON 스키마 일치)
- [ ] QoS 2 + Retained=true 확인
- [ ] `threshold_proposal` = null, `isolation_forest_score` = null (v1.0)
- [ ] ai_comment에 판정 근거(위반 Rule, 수치) 포함
- [ ] `python3 -m json.tool`로 발행된 JSON 파싱 검증

### 10.4 Git 커밋 메시지
```
feat(oracle): ORACLE_ANALYSIS 발행 (O8)

- publisher: QoS 2 + Retained=true
- oracle_analysis DTO: Mock 23~25 구조 호환
- comment_generator: 판정 근거 ai_comment 자동 생성
- 2차 검증 필드 null (v1.0)
```

---

## 11. Task O9 — 2차 검증 확장 인터페이스 스텁

### 11.1 작업 목표
EWMA+MAD, Isolation Forest 빈 모듈 + 인터페이스 생성. 실제 모델 학습/추론은 미구현.

### 11.2 핵심 구현 사항

- `engine/ewma_mad.py`: `def compute_dynamic_threshold(recipe_id, metric) -> Threshold` (스텁, NotImplementedError)
- `engine/isolation_forest.py`: `def compute_anomaly_score(features) -> float` (스텁, NotImplementedError)
- `engine/rule_engine.py`에서 호출 포인트 주석 처리 확인

### 11.3 검증 체크리스트
- [ ] `from engine.ewma_mad import compute_dynamic_threshold` import 성공
- [ ] `from engine.isolation_forest import compute_anomaly_score` import 성공
- [ ] 인터페이스 시그니처 확인 (타입 힌트 포함)
- [ ] rule_engine.py에서 2차 검증 호출 포인트가 주석으로 명시됨
- [ ] 스텁 호출 시 NotImplementedError 발생 확인

### 11.4 Git 커밋 메시지
```
feat(oracle): 2차 검증 확장 인터페이스 스텁 (O9)

- ewma_mad.py: EWMA+MAD 동적 임계값 인터페이스 (스텁)
- isolation_forest.py: Isolation Forest 이상도 점수 인터페이스 (스텁)
- rule_engine.py: 2차 검증 호출 포인트 주석 마킹
```

---

## 12. Task O10 — 통합 테스트 + Graceful Shutdown

### 12.1 작업 목표
전체 파이프라인 통합 테스트, SIGTERM Graceful Shutdown 구현.

### 12.2 Shutdown 구현

```python
# main.py
import signal
import asyncio

async def graceful_shutdown(sig, loop):
    logger.info(f"{sig.name} received, starting graceful shutdown...")
    # 1. MQTT 구독 해제
    await mqtt_client.unsubscribe_all()
    # 2. 진행 중인 판정 완료 대기 (5초 타임아웃)
    await asyncio.wait_for(pending_judgments.join(), timeout=5.0)
    # 3. DB 커넥션 풀 해제
    await db_pool.close()
    # 4. MQTT 연결 해제
    await mqtt_client.disconnect()

for sig in (signal.SIGTERM, signal.SIGINT):
    loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(graceful_shutdown(s, loop)))
```

### 12.3 통합 테스트 시나리오

1. **정상 양산**: LOT_END(Mock 09) → Historian 조회 → 38개 Rule 판정 → ORACLE_ANALYSIS(NORMAL) 발행
2. **수율 MARGINAL**: yield_pct = 85.0% → WARNING 발행
3. **Teaching 미완성**: ET=52 전수 FAIL → DANGER 발행
4. **알람 연쇄**: LIGHT_PWR_LOW → SIDE ET=52 비율 상승 → 연쇄 상향
5. **N:1 동시**: 4대 장비 동시 LOT_END → 각 장비 독립 판정
6. **Graceful Shutdown**: 판정 진행 중 SIGTERM → 판정 완료 후 종료
7. **Historian 장애**: Historian DB 연결 실패 → 판정 스킵 + 에러 로그 (크래시 아님)

### 12.4 검증 체크리스트
- [ ] Docker Compose 풀스택(Broker+Historian+EAP+Oracle) → LOT_END → ORACLE_ANALYSIS 수신 확인
- [ ] Mock 09 → NORMAL, Mock 10 → WARNING, Mock 05 기반 → DANGER
- [ ] 4대 장비 동시 LOT_END → 각 장비 독립 판정 확인
- [ ] SIGTERM → 진행 중 판정 완료 → DB 해제 → MQTT 해제 → 종료
- [ ] 5초 타임아웃 초과 시 강제 종료 (exit code 1)
- [ ] Historian DB 연결 실패 → 판정 스킵 + 에러 로그

### 12.5 Git 커밋 메시지
```
feat(oracle): 통합 테스트 + Graceful Shutdown (O10)

- SIGTERM/SIGINT: 판정 완료 대기 → DB 해제 → MQTT 해제
- 5초 타임아웃 강제 종료
- 통합 테스트 7개 시나리오 검증
```

---

## 13. Mock 데이터 참조 (판정 검증용)

### 13.1 Oracle 판정 검증에 사용하는 주요 Mock

| # | 파일 | 이벤트 | 기대 판정 | 검증 포인트 |
|:---|:---|:---|:---|:---|
| 02 | status_run | STATUS_UPDATE | — | 장비 상태 캐시 갱신 (recipe_id/operator_id) |
| 05 | inspection_fail_side_et52 | INSPECTION_RESULT | DANGER (R08, R09) | ET=52 전수 FAIL, Historian 경유 조회 |
| 09 | lot_end_normal | LOT_END | NORMAL | 정상 양산 (yield 96.2%, COMPLETED) |
| 10 | lot_end_aborted | LOT_END | WARNING (R23, R35) | 강제 종료 (ABORTED, yield 94.2%) |
| 11 | alarm_cam_timeout | HW_ALARM | R26 보조 | CAM_TIMEOUT_ERR 카운터 |
| 18 | recipe_changed_normal | RECIPE_CHANGED | — | Rule DB 캐시 갱신 |
| 23 | oracle_normal | ORACLE_ANALYSIS | — | 발행 구조 참조 (NORMAL) |
| 24 | oracle_warning | ORACLE_ANALYSIS | — | 발행 구조 참조 (WARNING) |
| 25 | oracle_danger | ORACLE_ANALYSIS | — | 발행 구조 참조 (DANGER) |

### 13.2 실측 기준값 (Carsem 현장)

| 지표 | 실측값 |
|:---|:---|
| Heartbeat 주기 | 3초 |
| STATUS 주기 | 6초 |
| takt_time | ~1,620ms (MAP+PRS+SIDE 합산) |
| total_units/Lot | 2,792 (349 Strip × 8슬롯) |
| 정상 수율 (Carsem_3X3) | 96.2% (28 LOT 학습 기반) |
| Lot 소요시간 | 82분 (정상 40~180분, 최대 370분) |

---

## 14. 작업 시 주의사항 (실수 방지)

### 14.1 자주 하는 실수
- ❌ `paho-mqtt` v1 API 사용 → v2에서 `connect()` 시그니처 변경됨. `clean_start` 파라미터 확인.
- ❌ `inspection_detail` 내부를 snake_case로 변환 → `ZAxisNum`이 `z_axis_num`이 됨. PascalCase 유지 필수.
- ❌ R38a/R38b를 판정 로직에 포함 → 2차 검증 모듈 활성화 전까지 제외해야 함.
- ❌ ORACLE_ANALYSIS 발행 시 Retained=false → Retained=true 필수 (모바일 재연결 시 즉시 복원).
- ❌ Historian TSDB 쿼리에 `PASS` 건의 detail 필드를 기대 → PASS drop 정책에 의해 detail은 NULL.
- ❌ 알람 카운터를 Historian 쿼리에만 의존 → 인메모리 캐시와 Historian 보정 조회 병행 필수.
- ❌ `datetime.now()` 사용 → `datetime.now(timezone.utc)` 또는 원본 메시지 timestamp 유지.
- ❌ `oracle` 계정으로 `ds/+/result` 구독 시도 → ACL 위반. INSPECTION_RESULT는 Historian TSDB 경유.

### 14.2 도움이 되는 작업 패턴
- ✅ Task 시작 전에 관련 명세서 절을 `view`로 읽어 현재 상태 확인
- ✅ `mosquitto_sub -v -t "ds/+/oracle"` 로 ORACLE_ANALYSIS 발행 실시간 모니터링
- ✅ JSON 직렬화 결과를 `python3 -m json.tool`로 포맷 확인
- ✅ 각 Task 끝에 검증 체크리스트 모든 항목 점검 후 다음 Task로
- ✅ Git 커밋은 Task 단위로 10번 분리. 한 커밋에 여러 Task 섞지 말 것
- ✅ pytest 단위 테스트를 Rule 그룹별로 분리 (`test_lot_rules.py`, `test_unit_rules.py` 등)

### 14.3 막혔을 때
- Rule 판정 기준이 모호하면 `../DS-Document/명세서/DS_EAP_MQTT_API_명세서.md` §11을 다시 읽는다
- Historian 쿼리 패턴이 불확실하면 `../Historian/명세서/Historian_작업명세서.md` §3.3을 확인한다
- Mock 데이터 구조가 기억나지 않으면 `../DS-Document/EAP_mock_data/README.md`를 참조한다
- 2차 검증 확장 구조가 모호하면 `../DS-Document/문서/오라클 2차 검증 기획안.md`를 참조한다
- 필드명/값 컨벤션이 모호하면 기존 Mock 01~27의 패턴을 따른다
- 두 가지 해석이 가능한 경우, 이 CLAUDE.md의 §0~§1 원칙으로 돌아가서 본질에 더 부합하는 쪽을 선택

---

## 15. 최종 확인

이 명세서를 받았다면, 작업을 시작하기 전에 아래 5가지를 너 자신에게 확인한다.

1. ✅ 10개 Task의 우선순위와 의존성을 이해했는가? (O1 → O2 → O3 → O4 → O5 → O6 → O7 → O8 → O9 → O10)
2. ✅ **Python 코드를 작성**하는 것이 이번 작업의 목표라는 점을 이해했는가?
3. ✅ `./명세서/Oracle_작업명세서.md`가 구현의 1차 설계도라는 점을 기억하는가?
4. ✅ 실로그 기반 Mock 01~17의 수치는 절대 변경하지 않는다는 원칙을 기억하는가?
5. ✅ 각 Task 끝에 검증 체크리스트를 모두 통과해야 다음 Task로 넘어간다는 규칙을 따를 것인가?

모두 ✅이면 **§0.4 필독 문서 6개를 먼저 read한 후**, Task O1부터 시작한다.

작업 진행 중 §0~§14 중 어느 절이라도 모순되거나 막막한 부분이 있다면, 추측으로 진행하지 말고 멈춰서 사용자에게 질문한다.

---

## 16. 최종 보고 형식

```
## Oracle 판정 엔진 서버 구현 완료 보고

### 변경 통계
- 신규 파일: N개
- 추가 라인: +X

### Task 완료 현황
- [x] O1 프로젝트 초기화 + MQTT 연결 (P0)
- [x] O2 MQTT 구독 핸들러 4종 (P0)
- [x] O3 인메모리 캐시 4종 (P0)
- [x] O4 Rule DB 스키마 + 시딩 (P0)
- [x] O5 Historian TSDB 조회 모듈 (P0)
- [x] O6 Rule 판정 엔진 — LOT + Unit (P0)
- [x] O7 Rule 판정 엔진 — Alarm + Recipe + Status (P1)
- [x] O8 ORACLE_ANALYSIS 발행 (P0)
- [x] O9 2차 검증 확장 인터페이스 스텁 (P2)
- [x] O10 통합 테스트 + Graceful Shutdown (P1)

### 검증 결과
- MQTT 정책 준수 (QoS/Retained/ACL): PASS
- 재연결 백오프 수열: PASS
- 정상 LOT → NORMAL 판정: PASS
- ABORTED LOT → WARNING 판정: PASS
- ET=52 전수 → DANGER 판정: PASS
- 알람 카운터 R26 판정: PASS
- 숫자형 레시피 R31 판정: PASS
- 비정상 전환 R38c 판정: PASS
- ORACLE_ANALYSIS Mock 23~25 구조 호환: PASS
- Historian 연동 쿼리 5종: PASS
- 4대 동시 판정: PASS
- Graceful Shutdown: PASS

### 다음 단계 권고
1. 2차 검증 모듈 활성화 (EWMA+MAD / Isolation Forest) — engine/ewma_mad.py, engine/isolation_forest.py 스텁 구현체 교체
2. Dispatcher 서버 (Node.js) — read-only 조회 + 비식별화
3. 모바일 앱 (Flutter) — 실시간 N:1 타일 모니터링 + ORACLE_ANALYSIS 표시
```

---

**End of CLAUDE.md**
