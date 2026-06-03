# DS Vision Oracle 판정 엔진 서버

LOT 완료 시 Historian TimescaleDB에서 데이터를 조회하여 38개 Rule 기반 품질 판정을 수행하고, 결과를 MQTT로 발행하는 Local Area 판정 엔진.

## 기술 스택

| 항목 | 내용 |
|---|---|
| Language | Python 3.11+ |
| MQTT | paho-mqtt v2.x (MQTT v5.0) |
| DB 드라이버 | psycopg 3.x (비동기) |
| 설정 | pydantic-settings + python-dotenv |
| 로깅 | structlog |
| 테스트 | pytest + pytest-asyncio |

## 디렉토리 구조

```
Oracle/
├── src/
│   ├── cache/        # 장비 상태, 알람 카운터, LOT 이력, Rule 캐시 (인메모리 4종)
│   ├── db/           # Historian TSDB 조회 쿼리, Rule DB CRUD
│   ├── engine/       # 판정 엔진 (lot_rules, unit_rules, alarm_rules 등 38개 Rule)
│   ├── handlers/     # 임계값 승인 핸들러
│   ├── models/       # 이벤트 DTO, 판정 결과 모델
│   ├── mqtt/         # MQTT 클라이언트, 구독, 발행
│   └── utils/        # 재연결 백오프, 로깅
├── auth/             # 인증 서비스 (JWT 발급)
├── sql/              # Rule DB 스키마 및 시딩 SQL (8개 파일)
└── tests/            # 단위/통합 테스트
```

## 판정 흐름

```
LOT_END 수신 (MQTT)
    ↓
Historian TSDB 조회 (LOT별 INSPECTION_RESULT 일괄)
    ↓
38개 Rule 판정 (LOT-level, Unit-level, Alarm, Recipe, Status)
    ↓
등급 결정: DANGER > WARNING > NORMAL (최고 심각도 기준)
    ↓
ORACLE_ANALYSIS 발행 (ds/{eq}/oracle, QoS 2, Retained=true)
```

## 판정 등급 기준 (주요 Rule)

| Rule | 조건 | 등급 |
|---|---|---|
| R23 | 수율 < 80% | DANGER |
| R23 | 수율 80~90% | WARNING |
| R25 | LOT 강제 종료 (ABORTED) | WARNING |
| R26 | CAM_TIMEOUT 일 4회 이상 | DANGER |
| R31 | 숫자형 레시피 ID | DANGER |
| R38c | 비정상 상태 전환 (RUN→STOP 무경고) | DANGER |

## 실행 방법

```bash
cd Oracle

# 환경변수 설정
cp .env.example .env

# Oracle DB + 인증 서비스 실행
docker compose up -d

# 서버 실행
pip install -e .
python -m src.main
```

## 포트

| 서비스 | 포트 |
|---|---|
| Auth Service (JWT) | 8443 |
| Oracle DB (PostgreSQL) | 5435 |

## 테스트

```bash
pytest tests/
```
