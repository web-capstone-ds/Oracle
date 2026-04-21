# Oracle 서버 작업명세서

**문서번호:** DS-ORACLE-SPEC-001 v1.1  
**작성일:** 2026-04-21  
**최종 수정:** 2026-04-21 (문서 간 교차 검증 반영)  
**프로젝트:** 반도체 후공정 비전 검사 장비 — Oracle 판정 엔진 서버  
**대외비**

| 항목 | 내용 |
| :--- | :--- |
| 장비 모델 | Genesem VELOCE-G7 Saw Singulation |
| 비전 소프트웨어 | GVisionWpf (C# WPF, HALCON + MQTTnet) |
| 현장 실측 기준 | Carsem Inc. / 2026-01-16~29 (14일) |
| 개발 언어 | Python |
| 통신 프로토콜 | MQTT v5.0 (Eclipse Mosquitto 2.x) |
| DB | PostgreSQL + TimescaleDB |
| 네트워크 환경 | 망 분리 공장 현장 로컬 Wi-Fi |

---

## 1. 개요

### 1.1 목적

Oracle 서버는 Broker에서 LOT_END 이벤트를 직접 구독하고, Historian TSDB에서 해당 LOT의 INSPECTION_RESULT를 일괄 조회하여, 실시간 Rule-based 1차 검증을 수행하는 **Local Area 내 판정 엔진**이다.

1차 검증의 핵심 임무는 두 가지이다.

- **MARGINAL 구간 감지**: EAP가 PASS로 판정한 LOT 중에서 FAIL 직전 경계 구간(수율 80~95%)에 있는 LOT를 식별하여 오퍼레이터에게 사전 경고를 전달한다.
- **장비 열화 징후 포착**: 절삭 품질(chipping, burr), 조명 상태(LIGHT_PWR_LOW), 카메라 응답(ET=30 빈도) 등 간접 지표를 통해 임계점에 도달하기 전에 경보를 발행한다.

### 1.2 개발 범위 (v1.0)

| 범위 | 상태 | 설명 |
| :--- | :--- | :--- |
| 1차 검증 (Rule-based) | **본 버전 구현 대상** | LOT_END 트리거 → 38개 Rule 판정 → ORACLE_ANALYSIS 발행 |
| 2차 검증 (EWMA+MAD / Isolation Forest) | **인터페이스만 준비** | Rule DB 스키마, 판정 등급 enum, ORACLE_ANALYSIS 페이로드 구조를 2차 검증 확장 가능하게 설계. 실제 모델 학습/추론은 미구현 |

> **설계 원칙:** 2차 검증의 존재를 코드 구조와 DB 스키마에 미리 반영하되, 1차 검증만으로 완결성 있는 판정 결과를 발행할 수 있어야 한다. R38a(Isolation Forest 점수), R38b(EWMA 이탈)는 2차 검증 모듈이 활성화될 때까지 판정에서 제외한다.

### 1.3 시스템 내 위치

```
가상 EAP 서버 (C#, MQTTnet)
        │
        │  MQTT Publish (8종 이벤트, JSON)
        ▼
   Eclipse Mosquitto Broker (로컬 Wi-Fi)
        │
        ├──→ 모바일 앱 (Flutter) ── 실시간 N:1 타일 모니터링
        ├──→ Historian 서버 (Node.js/TimescaleDB) ── 시계열 적재
        ├──→ Oracle 서버 (본 프로젝트) ← 너가 만드는 것
        │        │
        │        ├── LOT_END 직접 구독 (트리거)
        │        ├── Historian TSDB 경유 일괄 조회 (INSPECTION_RESULT)
        │        └── ORACLE_ANALYSIS 발행 (판정 결과)
        │
        └──→ MES 서버 (C#) ── 중앙 제어
```

### 1.4 데이터 흐름

```
[1차 검증 경로 — LOT 완료 즉시]
Broker (ds/{eq}/lot, QoS 2)
    → Oracle 서버 Subscribe (LOT_END 수신)
    → Historian TSDB 조회 (해당 LOT의 INSPECTION_RESULT 전량)
    → Rule DB 조회 (레시피별 현재 임계값)
    → 38개 Rule 판정 엔진
    → ORACLE_ANALYSIS 발행 (ds/{eq}/oracle, QoS 2, Retained)
    → 모바일 앱 / MES 수신

[보조 구독 경로]
Broker (ds/{eq}/alarm, QoS 2) → Oracle 서버
    → 알람 카운터 갱신 (R26/R33/R34 판정 보조)

Broker (ds/{eq}/recipe, QoS 2) → Oracle 서버
    → 레시피 전환 감지, Rule DB 캐시 갱신

Broker (ds/{eq}/status, QoS 1) → Oracle 서버
    → 장비 상태 캐시 갱신 (비정상 전환 감지 R38c)
```

### 1.5 단일 책임 원칙

Oracle은 **"판정"만** 수행한다. 데이터 적재(Historian), 실시간 모니터링(모바일), 중앙 제어(MES), 보안 전송(Dispatcher), AI 분석(AI 서버)은 다른 서버의 책임이다. Oracle에 장애가 발생해도 모바일 모니터링과 MES 제어, 데이터 적재는 독립적으로 유지된다.

---

## 2. 참조 문서

작업 시작 전 아래 문서를 반드시 참조한다.

| 우선순위 | 문서 | 참조 목적 |
| :--- | :--- | :--- |
| 1 | `명세서/DS_EAP_MQTT_API_명세서.md` v3.4 | 8종 이벤트 페이로드 필드 정의, QoS/Retained 정책, Rule 38개 판정 기준표 (§11) |
| 2 | `명세서/eap-spec-v1.md` v1.1 | 이벤트 시퀀스, 비정상 시나리오, Mock 데이터 27종 인덱스 |
| 3 | `명세서/DS_이벤트정의서.md` v1.0 | 5대분류/15소분류 이벤트 분류 체계, Oracle 연동 인터페이스 (§9) |
| 4 | `문서/오라클 2차 검증 기획안.md` v1.0 | 2차 검증 설계 전체. Rule DB 구조, 판정 3단계, 레시피별 독립 학습 |
| 5 | `문서/기획안.md` v1.0 | 7종 서버 구성, Oracle 서버 역할 정의, 데이터 흐름 |
| 6 | `명세서/Historian_작업명세서.md` v1.0 | Historian TSDB 스키마, Oracle 데이터 공급 쿼리 패턴 (§3.3) |

> **문서 간 충돌 시:** API 명세서 v3.4 > eap-spec-v1 > 이벤트 정의서 v1.0

---

## 3. 기능 요구사항

### 3.1 MQTT 구독 (Subscribe)

Oracle 서버는 판정에 필요한 이벤트만 선택적으로 구독한다.

| 토픽 패턴 | 이벤트 | QoS | Retained | 용도 |
| :--- | :--- | :--- | :--- | :--- |
| `ds/+/lot` | LOT_END | 2 | ✅ | **1차 검증 트리거**. 수율, 총 유닛 수, 소요시간 포함 |
| `ds/+/alarm` | HW_ALARM | 2 | ✅ | 알람 카운터 보조 (R26/R33/R34) |
| `ds/+/recipe` | RECIPE_CHANGED | 2 | ✅ | 레시피 전환 감지, Rule DB 캐시 갱신 |
| `ds/+/status` | STATUS_UPDATE | 1 | ✅ | 장비 상태 캐시 (비정상 전환 R38c, recipe_id/operator_id 캐시) |

> **INSPECTION_RESULT 직접 구독 안 함**: Oracle은 Historian TSDB를 경유하여 LOT 단위로 INSPECTION_RESULT를 일괄 조회한다. 이는 실시간 처리 부하에서 자유로워 복잡한 분석을 수행할 수 있도록 하기 위함이다 (이벤트 정의서 §9.1).

### 3.2 MQTT 발행 (Publish)

| 토픽 패턴 | 이벤트 | QoS | Retained | 용도 |
| :--- | :--- | :--- | :--- | :--- |
| `ds/{equipment_id}/oracle` | ORACLE_ANALYSIS | 2 | ✅ | 판정 결과 발행 (NORMAL / WARNING / DANGER) |

### 3.3 ACL 계정 정책

| 항목 | 값 |
| :--- | :--- |
| 계정 | `oracle` |
| Subscribe 허용 | `ds/+/lot`, `ds/+/alarm`, `ds/+/recipe`, `ds/+/status` |
| Publish 허용 | `ds/+/oracle` |

### 3.4 빈 페이로드 처리

ALARM_ACK 시 EAP가 `ds/{eq}/alarm` 토픽에 빈 페이로드 + Retain=true를 발행하여 retained message를 clear한다. Oracle은 빈 페이로드 수신 시 적재하지 않고 무시해야 한다.

---

## 4. 1차 검증 (Rule-based) 상세 설계

### 4.1 판정 트리거 시퀀스

```
[T+0]  LOT_END 수신 (ds/{eq}/lot, QoS 2)
         │
         ├── 페이로드 파싱: lot_id, yield_pct, total_units, lot_duration_sec, lot_status
         │
[T+1]  Historian TSDB 조회
         │   SELECT * FROM inspection_results
         │   WHERE lot_id = ? AND equipment_id = ?
         │   ORDER BY time ASC
         │
         ├── INSPECTION_RESULT 전량 로드 (PASS: summary만, FAIL: 전체)
         │
[T+2]  Rule DB 조회
         │   SELECT * FROM rule_thresholds
         │   WHERE recipe_id = ? OR recipe_id = '__default__'
         │
         ├── 레시피별 현재 임계값 로드
         │
[T+3]  38개 Rule 판정 엔진 실행
         │
         ├── LOT-level Rules: R23(yield), R24(duration), R25(Start/End 차이), R35(ABORTED 연속)
         ├── Unit-level Rules: R02~R07(PRS), R08~R12(SIDE), R13~R18(singulation), R19~R22(process)
         ├── Alarm-level Rules: R26(CAM_TIMEOUT/일), R27(WRITE_FAIL), R28~R29(VISION/LIGHT), R33~R34(AggEx/EAP_DISC)
         ├── Recipe-level Rules: R30(신규 Fail율), R31(숫자형 ID), R32(EMAP 크기)
         └── Status Rules: R38c(비정상 전환)
         │
[T+4]  판정 종합 (최고 심각도 채택)
         │
[T+5]  ORACLE_ANALYSIS 발행 (ds/{eq}/oracle, QoS 2, Retained)
```

### 4.2 판정 등급 체계

1차 검증에서는 Rule 38개 중 R38a(Isolation Forest), R38b(EWMA)를 제외한 **36개 Rule**로 판정한다. 복수 Rule이 동시에 위반될 경우 **최고 심각도**를 채택한다.

ORACLE_ANALYSIS 발행 시 `judgment` 필드는 NORMAL / WARNING / DANGER 3단계이지만, Oracle 내부에서는 수율(R23)에 한해 **5단계 세분류**를 적용하여 LOT 보고서의 정보 밀도를 높인다.

| 등급 | 조건 | 액션 |
| :--- | :--- | :--- |
| NORMAL | 모든 Rule 정상 범위 | LOT 보고서 생성, 경보 없음 |
| WARNING | 1개 이상 Rule이 WARNING 구간 진입 | LOT 보고서 + 모바일 주의 알림 + 오퍼레이터 확인 요청 |
| DANGER | 1개 이상 Rule이 CRITICAL 구간 진입 | 즉시 경보 + 작업 중단 권고 |

#### 4.2.1 수율(R23) 5단계 세분류 (API 명세서 §5.2 기반)

수율은 Oracle의 핵심 감지 대상(MARGINAL 구간)이므로 다른 Rule보다 정밀하게 분류한다. `violated_rules[].description`에 세분류 등급을 명시한다.

| 수율 구간 | 세분류 | judgment 매핑 | 조치 |
| :--- | :--- | :--- | :--- |
| ≥ 98% | EXCELLENT | NORMAL | 정상 양산. 기록 보존 |
| 95% ~ 98% | NORMAL | NORMAL | 정상. Carsem_3X3 기준 96.2% 실측 |
| 90% ~ 95% | WARNING | WARNING | 불량 패턴 분석. 오퍼레이터 확인 |
| 80% ~ 90% | MARGINAL | WARNING | **핵심 감지 대상**. 생산 중단 검토. 모바일 강조 표시 |
| < 80% | CRITICAL | DANGER | 즉시 생산 중단. 현장 점검 + 레시피 재확인 |

> **MARGINAL 감지가 Oracle 1차 검증의 본질적 목적이다.** 기획서에서 "성공적으로 완료된 Lot 중에서 성공과 실패 사이의 회색지대(MARGINAL, Fail기준 80~95% 사이)에 있는 데이터를 파악"이라고 명시하고 있다. R23 WARNING 구간(90~95%)과 MARGINAL 구간(80~90%)을 구분하여 `violated_rules`에 세분류를 기록한다.

### 4.3 Rule 38개 판정 기준표

API 명세서 v3.4 §11 기반. Carsem 실가동 로그 14일 분석 기준. 1차 검증 if-else 구현에 직접 사용한다.

#### 4.3.1 Heartbeat / 연결 상태 Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 근거 Mock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R01 | Heartbeat 간격 | ≤9s | 9~30s | >30s | 01 |
| R34 | EAP_DISCONNECTED | 0건/주 | 1건/주 | >2건/주 | 17 |

#### 4.3.2 PRS (픽앤소트) Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 근거 Mock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R02 | PRS XOffset | \|x\|≤300 | 250<\|x\|≤300 | \|x\|>300 (ET=11) | 07 |
| R03 | PRS YOffset | \|y\|≤300 | 250<\|y\|≤300 | \|y\|>300 (ET=11) | 07 |
| R04 | PRS TOffset | \|t\|≤10,000 | 8,000<\|t\|≤10,000 | \|t\|>10,000 | 07 |
| R05 | PRS ET=30 발생률 | <1% | 1~3% | >3% → CAM_TIMEOUT | 11 |
| R06 | PRS Pass율 | ≥95% | 90~95% | <90% | 07 |
| R07 | PRS ET=11 동시 슬롯 | 0개 | 1~2개 | ≥3개 동시 | 07 |

#### 4.3.3 SIDE (측면 비전) Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 근거 Mock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R08 | SIDE Pass율 | ≥96% | 90~96% | <90% | 05,06,08 |
| R09 | SIDE ET=52 비율 | <5% | 5~50% | >50% Teaching 의심 | 05 |
| R10 | SIDE ET=52 연속 | 0건 | 5~9건 | ≥10건 연속 | 15 |
| R11 | SIDE ET=12 발생 | 없음 | 산발 | 전 슬롯 ET=12 | 06 |
| R12 | SIDE ET=30 연속 | 0건 | 1~2건 | ≥3건 | 11 |

#### 4.3.4 Singulation (절삭 품질) Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 근거 Mock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R13 | chipping_top_um | <40μm | 40~50μm | >50μm (ET=12) | 06,08 |
| R14 | chipping_bottom_um | <35μm | 35~45μm | >45μm (ET=12) | 06,08 |
| R15 | burr_height_um | <5μm | 5~8μm | >8μm | 06,08 |
| R16 | blade_wear_index | <0.70 | 0.70~0.85 | >0.85 (교체 권고) | 04~08 |
| R17 | spindle_load_pct | <70% | 70~80% | >80% | 04~08 |
| R18 | cutting_water_flow_lpm | ≥1.5 L/min | 1.2~1.5 | <1.2 | 04 |

#### 4.3.5 Process (검사 성능) Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 근거 Mock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R19 | MAP 응답시간 P95 | <2,500ms | 2,500~3,000ms | >3,000ms | report |
| R20 | MAP 카메라 fps | 8~16fps | 6~8fps | <6fps | report,12 |
| R21 | MapQue 잔여 | 0개 | 15~30개 | >30개 | 12 |
| R22 | takt_time_ms | <2,000ms | 2,000~3,000ms | >3,000ms | 04~08 |

#### 4.3.6 LOT 수율/관리 Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 근거 Mock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R23 | yield_pct | ≥95% | 90~95% | <90% | 09,10 |
| R24 | lot_duration_sec | <24,000s | — | ≥24,000s → VISION_SCORE_ERR | 09,10,16 |
| R25 | LOT Start/End 차이 | 0 | 1~3 누적 | ≥5 누적 | 16 |
| R35 | 동일레시피 ABORTED | 0회 | 1회 | ≥2회 연속 | 10 |
| R36 | blade_usage_count | <20,000회 | 20,000~25,000회 | >25,000회 | 04~08 |
| R37 | inspection_duration_ms | <1,500ms | 1,500~2,000ms | >2,000ms | 04~08 |

#### 4.3.7 알람 카운터 Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 근거 Mock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R26 | CAM_TIMEOUT_ERR/일 | 0건 | 1~2건 | >3건 | 11 |
| R27 | WRITE_FAIL 발생 | 0건 | 1건 이상 | 연속 5건 이상 | 12 |
| R28 | VISION_SCORE_ERR (NULL, #4056) | 0건 | 산발 | 연속 10건 이상 | 13 |
| R29 | LIGHT_PWR_LOW | 0건 | 1건 | 연속 3건 이상 | 14 |
| R33 | AggregateException | 0건 | 1~5건/일 | >5건/일 | 16 |

#### 4.3.8 레시피 관리 Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 근거 Mock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R30 | 신규레시피 Fail율 | <10% | 10~30% | >30% 지속 | 15,19 |
| R31 | 숫자형 레시피 ID | 문자형 | — | 숫자형(446275) | 20 |
| R32 | EMAP 크기 | ≤100개 | 100~150개 | >150개 | 20 |

#### 4.3.9 상태 전환 / 2차 검증 예약 Rules

| Rule # | 파라미터 | 정상 | WARNING | CRITICAL | 비고 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| R38a | Isolation Forest 점수 | <0.5 | 0.5~0.85 | >0.85 | **v1.0 미구현** (2차 검증) |
| R38b | EWMA 이탈 | μ±2σ 이내 | 2σ~3σ 초과 | 3σ 초과 | **v1.0 미구현** (2차 검증) |
| R38c | status 비정상 전환 | 정상 패턴 | — | RUN→STOP 무경고 | 1차 검증 구현 |

### 4.4 Rule 판정 구현 전략

#### 4.4.1 LOT-level Rules (LOT_END 페이로드 직접 판정)

LOT_END 페이로드의 필드만으로 즉시 판정 가능한 Rule들이다. Historian 조회가 불필요하다.

> **주의 — LOT_END enrichment**: LOT_END 페이로드에는 `recipe_id`와 `operator_id`가 포함되어 있지 않다 (API 명세서 §5.1). Oracle은 장비별 STATUS_UPDATE 캐시에서 `recipe_id`를 추출한다. 캐시 미존재 시 Historian의 `lot_ends` 테이블에서 역조회한다 (Historian이 이미 enrichment 완료).

- **R23** (yield_pct): `lot_end.yield_pct` 직접 비교. 5단계 세분류 적용 (§4.2.1)
- **R24** (lot_duration_sec): `lot_end.lot_duration_sec` 직접 비교
- **R25** (Start/End 차이): 인메모리 장비별 LOT Start/End 카운터에서 산출
- **R35** (동일 레시피 ABORTED 연속): 인메모리 장비별 최근 ABORTED 이력에서 산출. `recipe_id`는 STATUS 캐시에서 추출

#### 4.4.2 Unit-level Rules (Historian TSDB 조회 후 집계 판정)

LOT의 INSPECTION_RESULT 전량을 Historian에서 조회한 후 집계하여 판정한다.

```python
# Historian TSDB 조회 쿼리 (Historian 작업명세서 §4.2.3 스키마 기준)
SELECT
    overall_result, fail_reason_code, fail_count,
    total_inspected_count,
    inspection_detail,        -- JSONB (PascalCase 원본, PASS시 NULL)
    singulation,              -- JSONB (PASS시 NULL)
    geometric,                -- JSONB (PASS시 NULL)
    takt_time_ms,             -- 독립 컬럼 (PASS/FAIL 모두 적재)
    inspection_duration_ms,   -- 독립 컬럼 (PASS/FAIL 모두 적재)
    algorithm_version         -- 독립 컬럼 (PASS/FAIL 모두 적재)
FROM inspection_results
WHERE lot_id = %s AND equipment_id = %s
ORDER BY time ASC;
```

집계 대상 지표:

- **PRS 분석**: `inspection_detail.prs_result[]`에서 ErrorType별 카운트, XOffset/YOffset/TOffset 분포
- **SIDE 분석**: `inspection_detail.side_result[]`에서 ErrorType별 카운트, ET=52 연속 카운트
- **Singulation 분석**: `singulation` JSONB에서 chipping_top_um, chipping_bottom_um, burr_height_um 통계
- **Process 분석**: takt_time_ms, inspection_duration_ms의 P95 산출

> **PASS drop 고려**: Historian의 PASS drop 정책에 의해 `overall_result=PASS AND fail_count=0`인 레코드는 inspection_detail/singulation이 NULL이다. PRS/SIDE/singulation 분석은 **FAIL 레코드만** 대상으로 수행한다. PASS 레코드에서는 process 그룹(takt_time_ms, inspection_duration_ms)만 분석 가능하다.

#### 4.4.3 Alarm-level Rules (인메모리 카운터 기반)

Oracle이 `ds/+/alarm`을 구독하여 장비별/hw_error_code별 카운터를 인메모리에 유지한다. LOT_END 판정 시 해당 카운터를 참조한다.

```python
# 인메모리 알람 카운터 구조
alarm_counters = {
    "DS-VIS-001": {
        "CAM_TIMEOUT_ERR": {"daily_count": 0, "last_reset": "2026-01-22T00:00:00Z"},
        "WRITE_FAIL": {"consecutive": 0},
        "VISION_SCORE_ERR": {"consecutive": 0},      # R28: NULL케이스 (#4056)
        "VISION_SCORE_ERR_AGGEX": {"daily_count": 0, "last_reset": "2026-01-22T00:00:00Z"},  # R33: AggregateException 케이스
        "LIGHT_PWR_LOW": {"consecutive": 0},
        "EAP_DISCONNECTED": {"weekly_count": 0, "last_reset": "2026-01-20T00:00:00Z"},
    }
}
```

> **R33 카운터 주의**: `AggregateException`은 독립 hw_error_code가 아니다. `hw_error_code=VISION_SCORE_ERR`이면서 `hw_error_detail`에 "AggregateException" 또는 "LotController.StartNewLot" 키워드가 포함된 경우를 별도로 카운트한다 (API 명세서 §6.4 VISION_SCORE_ERR 3케이스 구분).

> **보조 조회**: 인메모리 카운터가 초기화된 직후(서버 재시작 등)에는 Historian TSDB에서 보정 조회를 수행한다.

```sql
-- R26 보정: 당일 CAM_TIMEOUT_ERR 카운트
SELECT COUNT(*) FROM hw_alarms
WHERE equipment_id = %s
  AND hw_error_code = 'CAM_TIMEOUT_ERR'
  AND time > NOW() - INTERVAL '1 day';

-- R33 보정: 당일 AggregateException 카운트
-- VISION_SCORE_ERR 3케이스 중 LotController 케이스만 필터링 (API 명세서 §6.4)
SELECT COUNT(*) FROM hw_alarms
WHERE equipment_id = %s
  AND hw_error_code = 'VISION_SCORE_ERR'
  AND hw_error_detail LIKE '%LotController%'
  AND time > NOW() - INTERVAL '1 day';

-- R34 보정: 주간 EAP_DISCONNECTED 카운트
SELECT COUNT(*) FROM hw_alarms
WHERE equipment_id = %s
  AND hw_error_code = 'EAP_DISCONNECTED'
  AND time > NOW() - INTERVAL '7 days';
```

#### 4.4.4 Recipe-level Rules (RECIPE_CHANGED 수신 시 판정)

레시피 전환 시 `ds/+/recipe` 수신으로 트리거되며, 다음 LOT_END 판정에 반영한다.

- **R30** (신규 레시피 Fail율): Historian에서 해당 recipe_id의 LOT 이력이 없으면 "신규 레시피"로 플래그. 이후 LOT_END에서 fail율 추적
- **R31** (숫자형 레시피 ID): `recipe_id`가 정규식 `^\d+$`에 매칭되면 CRITICAL
- **R32** (EMAP 크기): 향후 EMAP 메타데이터 연동 시 구현. v1.0에서는 모니터링만

**레시피 전환 판정 기준 (API 명세서 §7.3 기반)**

| 구분 | 판정 조건 | 조치 |
| :--- | :--- | :--- |
| F-1 정상 전환 | Historian에 이력 있는 recipe_id | 즉시 양산 가능. 기존 Rule DB 임계값 로드 |
| F-2 신규 투입 | Historian에 이력 없는 recipe_id | Teaching 모니터링 50 Strip 자동 시작 (§12.2) |
| 숫자형 ID 경보 | recipe_id가 숫자형 (446275, 640022 등) | R31 CRITICAL. DS 측 확인 알림 발행 |
| EMAP 이상치 | EMAP 크기 > 100개 (정상 46개 기준) | R32 WARNING/CRITICAL. 레시피 설정 오류 의심 |
| 비정상 전환 | equipment_status ≠ IDLE | 비정상 전환 경보. LOT 진행 중 전환 불가 |

**실측 레시피 목록 (Carsem 현장 기반)**

| recipe_id | 형식 | 최초 등장 | 용도 | 비고 |
| :--- | :--- | :--- | :--- | :--- |
| Carsem_3X3 | 이름형 | 01-14 | 주력 양산 | 정상 수율 96.2%. 28 LOT 기반 |
| ATC_1X1 | 이름형 | 01-14 | 교정/검증 | Sequence=9999 더미 스트립. 양산 아님 |
| Carsem_4X6 | 이름형 | 01-16 | 신규 양산 (Teaching 미완성) | ET=52 전수 실패 1,253건 유발. 수율 68%대 |
| 446275 | 숫자형 | 01-23 | 미확인 | EMAP 181개 이상치. DS 측 확인 필요 (R31) |
| 640022 | 숫자형 | 01-23 | 미확인 | AggregateException 집중 발생 연관 (R31) |

---

## 5. ORACLE_ANALYSIS 발행 페이로드

### 5.1 페이로드 필드

API 명세서 v3.4 §9.4 기준. `equipment_status`는 포함하지 않는다 (HEARTBEAT/CONTROL_CMD/ORACLE_ANALYSIS 제외 규칙).

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :--- | :--- |
| message_id | string (UUID v4) | Y | 메시지 고유 식별자 |
| event_type | string | Y | `ORACLE_ANALYSIS` 고정값 |
| timestamp | string (ISO 8601) | Y | 분석 완료 시각 (`.fffZ` 밀리초 필수) |
| equipment_id | string | Y | 장비 ID |
| lot_id | string | Y | 분석 대상 LOT ID |
| recipe_id | string | Y | 레시피 ID (STATUS 캐시에서 추출) |
| judgment | string (enum) | Y | `NORMAL` / `WARNING` / `DANGER` |
| yield_status | object | Y | 수율 분석 결과 (§5.2) |
| ai_comment | string | Y | 판정 근거 자연어 요약 |
| threshold_proposal | object \| null | N | 임계값 변경 제안 (v1.0에서는 항상 null) |
| isolation_forest_score | float \| null | N | IF 점수 (v1.0에서는 항상 null) |
| violated_rules | array | Y | 위반된 Rule 목록 (v1.0 확장 필드) |

### 5.2 yield_status 서브오브젝트

| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| actual | float | 실측 수율 (LOT_END.yield_pct) |
| dynamic_threshold | object | `{ normal_min, normal_max, warning_min, warning_max }` |
| lot_basis | integer | 임계값 산출 기준 LOT 수 (v1.0에서는 0, 2차 검증 시 활성화) |

> **v1.0 동작**: `dynamic_threshold`는 Rule DB의 고정 임계값을 그대로 반영한다. `lot_basis=0`은 "고정 임계값 사용 중, 동적 학습 미적용"을 의미한다.

### 5.3 violated_rules 서브오브젝트 (v1.0 확장)

1차 검증의 판정 투명성을 위해 위반된 Rule 목록을 포함한다.

```json
"violated_rules": [
    {
        "rule_id": "R23",
        "parameter": "yield_pct",
        "actual_value": 91.3,
        "threshold": { "warning": 95.0, "critical": 90.0 },
        "level": "WARNING",
        "yield_grade": "WARNING",
        "description": "수율 91.3% — WARNING 구간 (90~95%)"
    },
    {
        "rule_id": "R16",
        "parameter": "blade_wear_index",
        "actual_value": 0.78,
        "threshold": { "warning": 0.70, "critical": 0.85 },
        "level": "WARNING",
        "description": "블레이드 마모 지수 0.78 — WARNING 구간 (0.70~0.85)"
    }
]
```

**violated_rules 항목 필드:**

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :--- | :--- |
| rule_id | string | Y | Rule 번호 (R01~R38c) |
| parameter | string | Y | 측정 파라미터명 |
| actual_value | float | Y | 실측값 |
| threshold | object | Y | `{ warning, critical }` 현재 적용 임계값 |
| level | string | Y | `WARNING` / `CRITICAL` — 해당 Rule의 위반 심각도 |
| yield_grade | string | N | R23 전용. 5단계 세분류 (`EXCELLENT` / `NORMAL` / `WARNING` / `MARGINAL` / `CRITICAL`) |
| description | string | Y | 자연어 설명 (템플릿 생성) |

### 5.4 ai_comment 생성 규칙

1차 검증에서는 AI 모델 없이 **템플릿 기반 자연어 생성**을 사용한다.

```python
# ai_comment 생성 예시
if judgment == "NORMAL":
    comment = f"LOT {lot_id} 정상 완료. 수율 {yield_pct}%, 전 Rule 정상 범위."
elif judgment == "WARNING":
    rules_str = ", ".join([r["rule_id"] for r in violated_rules])
    comment = f"LOT {lot_id} 주의. 수율 {yield_pct}%. 위반 Rule: {rules_str}. 오퍼레이터 확인 필요."
elif judgment == "DANGER":
    rules_str = ", ".join([r["rule_id"] for r in violated_rules])
    comment = f"LOT {lot_id} 위험. 수율 {yield_pct}%. 위반 Rule: {rules_str}. 즉시 점검 + 작업 중단 권고."
```

### 5.5 발행 예시

```json
{
    "message_id": "f1e2d3c4-b5a6-7890-abcd-ef1234567890",
    "event_type": "ORACLE_ANALYSIS",
    "timestamp": "2026-01-22T17:40:15.123Z",
    "equipment_id": "DS-VIS-001",
    "lot_id": "LOT-20260122-001",
    "recipe_id": "Carsem_3X3",
    "judgment": "NORMAL",
    "yield_status": {
        "actual": 96.2,
        "dynamic_threshold": {
            "normal_min": 95.0,
            "normal_max": 100.0,
            "warning_min": 90.0,
            "warning_max": 95.0
        },
        "lot_basis": 0
    },
    "ai_comment": "LOT LOT-20260122-001 정상 완료. 수율 96.2%, 전 Rule 정상 범위.",
    "threshold_proposal": null,
    "isolation_forest_score": null,
    "violated_rules": []
}
```

```json
{
    "message_id": "a2b3c4d5-e6f7-8901-bcde-f12345678901",
    "event_type": "ORACLE_ANALYSIS",
    "timestamp": "2026-01-27T12:30:22.456Z",
    "equipment_id": "DS-VIS-001",
    "lot_id": "LOT-20260127-003",
    "recipe_id": "Carsem_4X6",
    "judgment": "DANGER",
    "yield_status": {
        "actual": 68.5,
        "dynamic_threshold": {
            "normal_min": 95.0,
            "normal_max": 100.0,
            "warning_min": 90.0,
            "warning_max": 95.0
        },
        "lot_basis": 0
    },
    "ai_comment": "LOT LOT-20260127-003 위험. 수율 68.5% (CRITICAL <80%). 위반 Rule: R23, R09. 즉시 점검 + 작업 중단 권고.",
    "threshold_proposal": null,
    "isolation_forest_score": null,
    "violated_rules": [
        {
            "rule_id": "R23",
            "parameter": "yield_pct",
            "actual_value": 68.5,
            "threshold": { "warning": 95.0, "critical": 90.0 },
            "level": "CRITICAL",
            "yield_grade": "CRITICAL",
            "description": "수율 68.5% — CRITICAL 구간 (<80%). 즉시 생산 중단"
        },
        {
            "rule_id": "R09",
            "parameter": "side_et52_rate",
            "actual_value": 52.3,
            "threshold": { "warning": 5.0, "critical": 50.0 },
            "level": "CRITICAL",
            "description": "SIDE ET=52 비율 52.3% — Teaching 미완성 의심"
        }
    ]
}
```

> **Carsem_4X6 수율 68.5% 참고**: v1.0에서는 `__default__` 고정 임계값(WARNING: 95%, CRITICAL: 90%)이 적용되므로 68.5%는 CRITICAL → judgment=DANGER이다. 2차 검증 활성화 후에는 Carsem_4X6 전용 동적 임계값(EWMA 기반 μ=68.2%, σ=4.1%)이 적용되어 judgment가 NORMAL로 변경될 수 있다. 이것이 2차 검증의 핵심 가치(레시피별 독립 학습)이다.

---

## 6. Rule DB 스키마 설계

### 6.1 설계 원칙

- 1차 검증의 임계값을 코드 안에 하드코딩하지 않고 **DB 테이블에서 읽어오는 구조**로 설계한다.
- 2차 검증 활성화 시 오퍼레이터 승인으로 DB 값만 바뀌고, 1차 검증은 다음 LOT부터 자동으로 새 기준을 적용한다.
- 레시피별 독립 임계값을 지원하되, 레시피 미등록 시 `__default__` 폴백을 사용한다.

### 6.2 rule_thresholds 테이블

```sql
CREATE TABLE rule_thresholds (
    id                  SERIAL          PRIMARY KEY,
    recipe_id           TEXT            NOT NULL,   -- 레시피 ID 또는 '__default__'
    rule_id             TEXT            NOT NULL,   -- R01 ~ R38c
    metric              TEXT            NOT NULL,   -- yield_pct, blade_wear_index 등
    warning_threshold   DOUBLE PRECISION,           -- WARNING 경계값
    critical_threshold  DOUBLE PRECISION,           -- CRITICAL 경계값
    comparison_op       TEXT            NOT NULL DEFAULT 'gte',  -- gte/lte/abs_gte 등
    enabled             BOOLEAN         NOT NULL DEFAULT true,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    approved_by         TEXT,                       -- 승인자 ID (2차 검증 시 사용)
    lot_basis           INTEGER         NOT NULL DEFAULT 0,  -- 0=고정값, N=N LOT 학습 기반
    UNIQUE (recipe_id, rule_id)
);

-- 기본 임계값 시딩
INSERT INTO rule_thresholds (recipe_id, rule_id, metric, warning_threshold, critical_threshold, comparison_op)
VALUES
    ('__default__', 'R01', 'heartbeat_interval_sec', 9.0, 30.0, 'gte'),
    ('__default__', 'R02', 'prs_xoffset_abs', 250.0, 300.0, 'abs_gte'),
    ('__default__', 'R03', 'prs_yoffset_abs', 250.0, 300.0, 'abs_gte'),
    ('__default__', 'R04', 'prs_toffset_abs', 8000.0, 10000.0, 'abs_gte'),
    ('__default__', 'R05', 'prs_et30_rate_pct', 1.0, 3.0, 'gte'),
    ('__default__', 'R06', 'prs_pass_rate_pct', 95.0, 90.0, 'lte'),
    ('__default__', 'R07', 'prs_et11_simultaneous', 1.0, 3.0, 'gte'),
    ('__default__', 'R08', 'side_pass_rate_pct', 96.0, 90.0, 'lte'),
    ('__default__', 'R09', 'side_et52_rate_pct', 5.0, 50.0, 'gte'),
    ('__default__', 'R10', 'side_et52_consecutive', 5.0, 10.0, 'gte'),
    ('__default__', 'R13', 'chipping_top_um', 40.0, 50.0, 'gte'),
    ('__default__', 'R14', 'chipping_bottom_um', 35.0, 45.0, 'gte'),
    ('__default__', 'R15', 'burr_height_um', 5.0, 8.0, 'gte'),
    ('__default__', 'R16', 'blade_wear_index', 0.70, 0.85, 'gte'),
    ('__default__', 'R17', 'spindle_load_pct', 70.0, 80.0, 'gte'),
    ('__default__', 'R18', 'cutting_water_flow_lpm', 1.5, 1.2, 'lte'),
    ('__default__', 'R22', 'takt_time_ms', 2000.0, 3000.0, 'gte'),
    ('__default__', 'R23', 'yield_pct', 95.0, 90.0, 'lte'),
    ('__default__', 'R24', 'lot_duration_sec', NULL, 24000.0, 'gte'),
    ('__default__', 'R36', 'blade_usage_count', 20000.0, 25000.0, 'gte'),
    ('__default__', 'R37', 'inspection_duration_ms', 1500.0, 2000.0, 'gte')
ON CONFLICT (recipe_id, rule_id) DO NOTHING;
```

### 6.3 rule_change_history 테이블 (2차 검증 준비)

임계값 변경 이력을 추적한다. 2차 검증 활성화 시 오퍼레이터 승인 로그로 사용된다.

```sql
CREATE TABLE rule_change_history (
    id              SERIAL          PRIMARY KEY,
    changed_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    recipe_id       TEXT            NOT NULL,
    rule_id         TEXT            NOT NULL,
    metric          TEXT            NOT NULL,
    old_warning     DOUBLE PRECISION,
    new_warning     DOUBLE PRECISION,
    old_critical    DOUBLE PRECISION,
    new_critical    DOUBLE PRECISION,
    approved_by     TEXT,           -- 승인자 ID
    change_source   TEXT            NOT NULL DEFAULT 'manual',  -- manual / ewma_mad / isolation_forest
    ai_basis        TEXT            -- AI 근거 (2차 검증 시: "28 LOT EWMA μ=96.8%, σ=0.9%")
);
```

### 6.4 oracle_judgments 테이블 (판정 이력)

```sql
CREATE TABLE oracle_judgments (
    time            TIMESTAMPTZ     NOT NULL,
    message_id      UUID            NOT NULL,
    equipment_id    TEXT            NOT NULL,
    lot_id          TEXT            NOT NULL,
    recipe_id       TEXT            NOT NULL,
    judgment        TEXT            NOT NULL,   -- NORMAL / WARNING / DANGER
    yield_actual    DOUBLE PRECISION NOT NULL,
    violated_rules  JSONB,                      -- 위반 Rule 목록
    ai_comment      TEXT,
    analysis_source TEXT            NOT NULL DEFAULT 'rule_based',  -- rule_based / ewma_mad / composite
    payload_raw     JSONB                       -- 발행 페이로드 원본 보존
);

SELECT create_hypertable('oracle_judgments', 'time');
CREATE INDEX idx_oracle_eq_time ON oracle_judgments (equipment_id, time DESC);
CREATE INDEX idx_oracle_recipe ON oracle_judgments (recipe_id, time DESC);
CREATE INDEX idx_oracle_judgment ON oracle_judgments (judgment, time DESC);
```

---

## 7. 인메모리 캐시 설계

### 7.1 장비 상태 캐시

STATUS_UPDATE 수신 시 갱신. LOT_END 판정 시 recipe_id/operator_id 참조 및 비정상 전환 감지(R38c)에 사용한다.

```python
equipment_cache: dict[str, EquipmentState] = {}

@dataclass
class EquipmentState:
    equipment_id: str
    equipment_status: str          # RUN / IDLE / STOP
    recipe_id: str
    recipe_version: str
    operator_id: str
    lot_id: str | None
    uptime_sec: int
    current_unit_count: int | None     # v3.4 진행률
    expected_total_units: int | None   # v3.4 진행률
    current_yield_pct: float | None    # v3.4 진행률
    last_status_time: datetime
    previous_status: str | None    # R38c 비정상 전환 감지용
```

**R38c 상태 전환 판정 기준 (API 명세서 §3.3)**

| 이전 상태 | 이후 상태 | 정상 여부 | 판정 |
| :--- | :--- | :--- | :--- |
| IDLE → RUN | LOT 시작 | 정상 | — |
| RUN → IDLE | LOT_END (COMPLETED/ABORTED) | 정상 | — |
| RUN → STOP | HW_ALARM (CRITICAL) 선행 | 정상 (알람 동반) | — |
| RUN → STOP | HW_ALARM 없이 무경고 전환 | **비정상** | DANGER (R38c) |
| STOP → STOP | HW_ALARM 후 미복구 | 비정상 | WARNING |

### 7.2 알람 카운터 캐시

HW_ALARM 수신 시 갱신. LOT_END 판정 시 R26/R27/R28/R29/R33/R34에 사용한다.

```python
alarm_counters: dict[str, dict[str, AlarmCounter]] = {}

@dataclass
class AlarmCounter:
    daily_count: int = 0
    weekly_count: int = 0
    consecutive: int = 0
    last_reset_daily: datetime | None = None
    last_reset_weekly: datetime | None = None
```

### 7.3 LOT 이력 캐시

LOT Start/End 불균형(R25) 및 동일 레시피 ABORTED 연속(R35) 감지용이다.

```python
lot_history: dict[str, LotHistory] = {}

@dataclass
class LotHistory:
    equipment_id: str
    start_count: int = 0
    end_count: int = 0
    recent_aborted: list[str] = field(default_factory=list)  # 최근 ABORTED recipe_id 리스트
```

### 7.4 Rule DB 캐시

Rule DB 조회 부하를 최소화하기 위해 레시피별 임계값을 인메모리에 캐시한다.

```python
rule_cache: dict[str, dict[str, RuleThreshold]] = {}
# key: recipe_id → { rule_id → RuleThreshold }

CACHE_TTL = 300  # 5분. RECIPE_CHANGED 수신 시 즉시 무효화
```

---

## 8. MQTT 정책 필수 준수

### 8.1 구독/발행 QoS 정책

| QoS | 대상 토픽 | 이유 |
| :--- | :--- | :--- |
| QoS 1 | `ds/+/status` | 주기적 발행, 1회 누락 허용 |
| QoS 2 | `ds/+/lot`, `ds/+/alarm`, `ds/+/recipe` | 정확히 1회 전달 보장 필수 |
| QoS 2 | `ds/{eq}/oracle` (발행) | 판정 결과 누락 방지 |

### 8.2 세션 정책

```python
# paho-mqtt v2 연결 옵션
client.connect(
    host=broker_host,
    port=1883,
    clean_start=False,          # clean_start=false (세션 유지)
    properties=Properties(PacketTypes.CONNECT),
    keepalive=60,
)
# session_expiry_interval=3600 (1시간 재연결 여유)

client_id = "ds_oracle_001"
```

### 8.3 재연결 백오프

```
1s → 2s → 5s → 15s → 30s, max 60s, jitter ±20%
```

```python
BACKOFF_STEPS = [1, 2, 5, 15, 30, 60]

def get_reconnect_delay(attempt: int) -> float:
    base = BACKOFF_STEPS[min(attempt, len(BACKOFF_STEPS) - 1)]
    jitter = base * 0.2 * (random.random() * 2 - 1)  # ±20%
    return base + jitter
```

### 8.4 Retained 발행 정책

ORACLE_ANALYSIS는 `Retain=true`로 발행한다. 모바일 앱 재연결 시 마지막 판정 결과를 즉시 복원하기 위함이다.

### 8.5 Will 메시지

Oracle 서버는 Publisher이므로 Will 메시지를 설정한다. 비정상 종료 시 `ds/{eq}/oracle` 토픽에 DANGER 상태를 전파할 수 있으나, Oracle 장애는 모니터링에 직접 영향을 주지 않으므로 **Will 메시지 미설정**으로 결정한다. Historian/모바일은 Oracle 독립적으로 동작한다.

### 8.6 Graceful Shutdown

```
[SIGTERM 수신]
    │
    ├─ ① 진행 중 LOT_END 판정이 있으면 완료 대기 (최대 5초)
    │
    ├─ ② MQTT 구독 해제
    │
    ├─ ③ MQTT 클라이언트 정상 DISCONNECT
    │
    ├─ ④ DB 연결 풀 해제
    │
    └─ ⑤ 프로세스 종료
```

---

## 9. 기술 스택

| 항목 | 기술 | 이유 |
| :--- | :--- | :--- |
| 언어 | Python 3.11+ | 기획서 확정 스택 |
| MQTT 라이브러리 | paho-mqtt v2.x | Python 표준 MQTT 클라이언트. MQTT v5.0, QoS 2 지원 |
| DB 드라이버 | psycopg[binary] 3.x | PostgreSQL 비동기 지원, 커넥션 풀링 |
| 비동기 프레임워크 | asyncio | MQTT 수신 + DB 조회 비동기 처리 |
| 설정 관리 | python-dotenv + pydantic-settings | .env 파일 기반 + 타입 안전 설정 |
| 로깅 | structlog | 구조적 JSON 로깅 |
| 테스트 | pytest + pytest-asyncio | 비동기 테스트 지원 |
| 컨테이너 | Docker + Docker Compose | Historian/Broker와 동일 네트워크 |

---

## 10. 프로젝트 구조

```
oracle/
├── .env.example                    # 환경변수 템플릿
├── docker-compose.yml              # Oracle + TimescaleDB
├── Dockerfile
├── pyproject.toml                  # 의존성 관리
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── main.py                     # 엔트리포인트, MQTT 연결, Graceful Shutdown
│   ├── config.py                   # 환경변수 로드, pydantic Settings
│   │
│   ├── mqtt/
│   │   ├── __init__.py
│   │   ├── client.py               # MQTT 연결, 재연결 백오프, QoS 정책
│   │   ├── subscriber.py           # LOT_END/ALARM/RECIPE/STATUS 구독 핸들러
│   │   └── publisher.py            # ORACLE_ANALYSIS 발행
│   │
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── rule_engine.py          # 38개 Rule 판정 엔진 (메인 오케스트레이터)
│   │   ├── lot_rules.py            # LOT-level Rules (R23, R24, R25, R35)
│   │   ├── unit_rules.py           # Unit-level Rules (R02~R22, R36, R37)
│   │   ├── alarm_rules.py          # Alarm-level Rules (R26~R29, R33, R34)
│   │   ├── recipe_rules.py         # Recipe-level Rules (R30, R31, R32)
│   │   ├── status_rules.py         # Status Rules (R01, R38c)
│   │   └── comment_generator.py    # ai_comment 템플릿 생성기
│   │
│   ├── cache/
│   │   ├── __init__.py
│   │   ├── equipment_cache.py      # 장비 상태 캐시
│   │   ├── alarm_counter.py        # 알람 카운터 캐시
│   │   ├── lot_history.py          # LOT 이력 캐시
│   │   └── rule_cache.py           # Rule DB 임계값 캐시
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── pool.py                 # DB 커넥션 풀
│   │   ├── schema.sql              # Rule DB + oracle_judgments DDL
│   │   ├── seed.sql                # 기본 임계값 시딩 데이터
│   │   ├── historian_queries.py    # Historian TSDB 조회 쿼리 모듈
│   │   └── rule_db.py              # Rule DB CRUD
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── events.py               # LOT_END, HW_ALARM, RECIPE_CHANGED DTO
│   │   ├── judgment.py             # NORMAL/WARNING/DANGER enum, ViolatedRule
│   │   └── oracle_analysis.py      # ORACLE_ANALYSIS 발행 DTO
│   │
│   └── utils/
│       ├── __init__.py
│       └── backoff.py              # 재연결 백오프 + jitter
│
├── tests/
│   ├── conftest.py
│   ├── test_lot_rules.py
│   ├── test_unit_rules.py
│   ├── test_alarm_rules.py
│   ├── test_rule_engine.py         # 통합 판정 테스트 (Mock 09, 10 기준)
│   └── test_mqtt_publish.py
│
└── sql/
    ├── 01_create_rule_tables.sql
    ├── 02_seed_default_thresholds.sql
    └── 03_create_judgment_table.sql
```

---

## 11. 환경변수

```bash
# .env.example

# MQTT Broker
MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883
MQTT_CLIENT_ID=ds_oracle_001
MQTT_USERNAME=oracle
MQTT_PASSWORD=oracle_secret

# Oracle DB (Rule DB + 판정 이력)
ORACLE_DB_HOST=localhost
ORACLE_DB_PORT=5432
ORACLE_DB_NAME=oracle
ORACLE_DB_USER=oracle
ORACLE_DB_PASSWORD=oracle_secret

# Historian DB (TSDB 읽기 전용)
HISTORIAN_DB_HOST=localhost
HISTORIAN_DB_PORT=5432
HISTORIAN_DB_NAME=historian
HISTORIAN_DB_USER=oracle_reader
HISTORIAN_DB_PASSWORD=reader_secret

# Rule Cache
RULE_CACHE_TTL_SEC=300

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

---

## 12. 레시피 전환 처리

### 12.1 RECIPE_CHANGED 수신 시 동작

```
[RECIPE_CHANGED 수신]
    │
    ├─ recipe_id 추출
    │
    ├─ Rule DB 조회: 해당 recipe_id의 임계값 존재?
    │   ├── Yes → Rule 캐시 갱신
    │   └── No  → '__default__' 폴백 사용
    │          └── Historian 조회: 해당 recipe_id LOT 이력 존재?
    │              ├── Yes (기존 레시피, Rule 미등록) → '__default__' + 이력 참조
    │              └── No  (신규 레시피) → R30 신규 레시피 플래그 ON
    │
    ├─ 숫자형 ID 판정 (R31)
    │   └── regex(^\d+$) 매칭 → CRITICAL 경보 즉시 발행
    │
    ├─ equipment_status 검증
    │   └── equipment_status ≠ IDLE → 비정상 전환 경보 (R38c 보조)
    │
    └─ 장비 캐시 recipe_id 갱신
```

### 12.2 신규 레시피 Teaching 모니터링

이벤트 정의서 §E-5 기반. 신규 레시피 투입 시 최초 50 Strip의 Fail율을 추적한다.

- Teaching 50 Strip 동안 Fail율 > 30%가 지속되면 R30 CRITICAL
- 50 Strip 이내에 정상 수율 도달 시 Teaching 완료로 간주
- Teaching 미완성 시 VISION_SCORE_ERR(hw_error_detail: "SIDE ET=52 fail rate exceeded 50%") 발행 → Oracle이 수신하여 해당 레시피 플래그 갱신

### 12.3 알람-레시피 연쇄 감지 패턴

이벤트 정의서 §E-4 기반. 단일 Rule만으로는 잡히지 않는 **연쇄 열화 패턴**을 Oracle이 능동적으로 감지한다.

| 연쇄 패턴 | 선행 이벤트 | 후행 모니터링 | 조치 |
| :--- | :--- | :--- | :--- |
| 조명 열화 → SIDE 품질 저하 | LIGHT_PWR_LOW (R29) | 이후 50 Strip SIDE ET=52 비율 추적 | 비율 상승 시 WARNING 발행 |
| 카메라 타임아웃 → fps 저하 | CAM_TIMEOUT_ERR (R26) | MAP fps (R20) 연동 확인 | fps < 6 동반 시 I/O 포화 의심 DANGER |
| WRITE_FAIL → LOT_END 누락 | WRITE_FAIL 연속 (R27) | LOT Start/End 카운터 (R25) | WRITE_FAIL + Start/End 불균형 동시 → DANGER |
| AggregateException → EAP 크래시 | AggEx burst (R33) | Heartbeat 중단 (R01) + EAP_DISCONNECTED (R34) | AggEx 5건/일 + Heartbeat 중단 → DANGER |

> **구현 방식:** 연쇄 패턴은 별도 Rule 번호를 부여하지 않고, `violated_rules[].description`에 연쇄 근거를 기록한다. 연쇄 감지 시 개별 Rule보다 심각도를 1단계 상향할 수 있다.

---

## 13. 2차 검증 확장 인터페이스 (v2.0 예약)

v1.0에서는 구현하지 않되, 코드 구조에 확장 포인트를 미리 준비한다.

### 13.1 확장 포인트 목록

| 확장 포인트 | 위치 | 설명 |
| :--- | :--- | :--- |
| `engine/ewma_mad.py` | 빈 모듈 + 인터페이스 | EWMA+MAD 동적 임계값 계산. `def compute_dynamic_threshold(recipe_id, metric) -> Threshold` |
| `engine/isolation_forest.py` | 빈 모듈 + 인터페이스 | Isolation Forest 이상도 점수. `def compute_anomaly_score(features) -> float` |
| `rule_thresholds.lot_basis` | DB 컬럼 | 0=고정값, N=N LOT 학습 기반. 2차 검증 시 자동 갱신 |
| `rule_thresholds.approved_by` | DB 컬럼 | 오퍼레이터 승인자 ID. 2차 검증 시 임계값 변경 승인 추적 |
| `rule_change_history` | DB 테이블 | 임계값 변경 이력. 2차 검증 시 AI 근거 기록 |
| `oracle_analysis.threshold_proposal` | 페이로드 필드 | v1.0에서는 null. 2차 검증 시 임계값 변경 제안 포함 |
| `oracle_analysis.isolation_forest_score` | 페이로드 필드 | v1.0에서는 null. 2차 검증 시 0~1 점수 포함 |

### 13.2 레시피별 독립 학습 구조 (2차 검증 활성화 시)

| LOT 누적 | 활성 모델 | 임계값 기준 | 비고 |
| :--- | :--- | :--- | :--- |
| 0~4 LOT | 오퍼레이터 시딩값 (v1.0 Rule DB 고정값) | 엔지니어 입력 초기값 | 셋업 구간 오염 방지 |
| 5~9 LOT | EWMA+MAD | 실측 데이터 동적 계산 | 레시피별 독립 |
| 10+ LOT | EWMA+MAD + Isolation Forest | 복합 지표 이상 감지 추가 | 이상도 점수 0~1 병행 |

### 13.3 오퍼레이터 승인 구조 (2차 검증 활성화 시)

```
AI 기준 조정 제안 (threshold_proposal 필드)
        ↓
모바일 알림 (제안 근거 포함)
        ↓
오퍼레이터 수락 → Rule DB 업데이트 → rule_change_history 기록
오퍼레이터 거부 → 기존 기준 유지
```

---

## 14. Docker Compose

```yaml
version: '3.8'

services:
  oracle-db:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: oracle
      POSTGRES_USER: oracle
      POSTGRES_PASSWORD: oracle_secret
    ports:
      - "5433:5432"
    volumes:
      - oracle_db_data:/var/lib/postgresql/data
      - ./sql/01_create_rule_tables.sql:/docker-entrypoint-initdb.d/01.sql
      - ./sql/02_seed_default_thresholds.sql:/docker-entrypoint-initdb.d/02.sql
      - ./sql/03_create_judgment_table.sql:/docker-entrypoint-initdb.d/03.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U oracle"]
      interval: 5s
      timeout: 5s
      retries: 5

  oracle:
    build: .
    depends_on:
      oracle-db:
        condition: service_healthy
    env_file: .env
    environment:
      ORACLE_DB_HOST: oracle-db
      MQTT_BROKER_HOST: broker
    restart: unless-stopped

volumes:
  oracle_db_data:
```

---

## 15. Task 분해

### Task O1 — 프로젝트 초기화 + MQTT 연결

| 항목 | 내용 |
| :--- | :--- |
| 목표 | Python 프로젝트 구조 생성, paho-mqtt v2 연결, 재연결 백오프 구현 |
| 산출물 | `main.py`, `config.py`, `mqtt/client.py`, `utils/backoff.py` |
| 검증 | Broker 연결/해제/재연결 로그 확인. 백오프 1s→2s→5s→15s→30s, jitter ±20% |

### Task O2 — MQTT 구독 핸들러 (4종 이벤트)

| 항목 | 내용 |
| :--- | :--- |
| 목표 | LOT_END, HW_ALARM, RECIPE_CHANGED, STATUS_UPDATE 구독 핸들러 구현 |
| 산출물 | `mqtt/subscriber.py`, `models/events.py` |
| 검증 | Mock 09(LOT_END), 11(ALARM), 18(RECIPE), 02(STATUS) 수신 + 파싱 로그 확인 |

### Task O3 — 인메모리 캐시 4종

| 항목 | 내용 |
| :--- | :--- |
| 목표 | 장비 상태 캐시, 알람 카운터, LOT 이력, Rule DB 캐시 구현 |
| 산출물 | `cache/` 디렉토리 전체 |
| 검증 | STATUS 수신 → 캐시 갱신, ALARM 수신 → 카운터 증분, Rule DB 캐시 TTL 만료 + 갱신 |

### Task O4 — Rule DB 스키마 + 시딩

| 항목 | 내용 |
| :--- | :--- |
| 목표 | rule_thresholds, rule_change_history, oracle_judgments 테이블 생성 + 기본 임계값 시딩 |
| 산출물 | `sql/` 디렉토리 전체, `db/pool.py`, `db/rule_db.py` |
| 검증 | Docker Compose로 DB 기동 → 시딩 데이터 36개 Rule 확인 |

### Task O5 — Historian TSDB 조회 모듈

| 항목 | 내용 |
| :--- | :--- |
| 목표 | LOT별 INSPECTION_RESULT 일괄 조회, 알람 카운터 보정 조회 구현 |
| 산출물 | `db/historian_queries.py` |
| 검증 | Historian에 Mock 데이터 적재 후, LOT-20260122-001 조회 → 2,792건 반환 확인 |

### Task O6 — Rule 판정 엔진 (LOT-level + Unit-level)

| 항목 | 내용 |
| :--- | :--- |
| 목표 | LOT-level Rules(R23,R24,R25,R35) + Unit-level Rules(R02~R22,R36,R37) 구현 |
| 산출물 | `engine/lot_rules.py`, `engine/unit_rules.py`, `engine/rule_engine.py` |
| 검증 | Mock 09(정상 LOT) → NORMAL, Mock 10(ABORTED) → WARNING, Mock 05(ET=52 전수) → DANGER |

### Task O7 — Rule 판정 엔진 (Alarm + Recipe + Status)

| 항목 | 내용 |
| :--- | :--- |
| 목표 | Alarm-level Rules(R26~R29,R33,R34) + Recipe Rules(R30,R31,R32) + Status Rules(R01,R38c) 구현 |
| 산출물 | `engine/alarm_rules.py`, `engine/recipe_rules.py`, `engine/status_rules.py` |
| 검증 | 알람 카운터 기반 R26 판정, 숫자형 레시피 R31 CRITICAL, RUN→STOP 무경고 R38c CRITICAL |

### Task O8 — ORACLE_ANALYSIS 발행

| 항목 | 내용 |
| :--- | :--- |
| 목표 | 판정 결과를 ORACLE_ANALYSIS 페이로드로 직렬화하여 `ds/{eq}/oracle`에 발행 |
| 산출물 | `mqtt/publisher.py`, `models/oracle_analysis.py`, `engine/comment_generator.py` |
| 검증 | LOT_END 수신 → 판정 → ORACLE_ANALYSIS 발행. QoS 2 + Retained. Mock 23~25와 구조 호환 |

### Task O9 — 2차 검증 확장 인터페이스 스텁

| 항목 | 내용 |
| :--- | :--- |
| 목표 | EWMA+MAD, Isolation Forest 빈 모듈 + 인터페이스 생성 |
| 산출물 | `engine/ewma_mad.py`, `engine/isolation_forest.py` (스텁) |
| 검증 | import 성공, 인터페이스 시그니처 확인, rule_engine에서 호출 포인트 주석 처리 확인 |

### Task O10 — 통합 테스트 + Graceful Shutdown

| 항목 | 내용 |
| :--- | :--- |
| 목표 | 전체 파이프라인 통합 테스트, SIGTERM Graceful Shutdown 구현 |
| 산출물 | `tests/` 디렉토리 전체, main.py Shutdown 로직 |
| 검증 | Docker Compose 풀스택(Broker+Historian+EAP+Oracle) → LOT_END → ORACLE_ANALYSIS 수신 확인 |

---

## 16. 검증 체크리스트

### 16.1 MQTT 정책 준수

| 항목 | 기준 | 확인 |
| :--- | :--- | :--- |
| 구독 QoS | status → QoS 1, lot/alarm/recipe → QoS 2 | ☐ |
| 발행 QoS | oracle → QoS 2, Retained=true | ☐ |
| clean_start | `false` (재연결 시 큐 보존) | ☐ |
| 재연결 백오프 | `[1, 2, 5, 15, 30, 60]`, jitter ±20% | ☐ |
| ACL 계정 | `oracle` (Subscribe: lot/alarm/recipe/status, Publish: oracle) | ☐ |
| 빈 페이로드 처리 | ALARM_ACK retained clear 신호 무시 | ☐ |

### 16.2 1차 검증 판정 정확성

| 시나리오 | 입력 | 기대 판정 | 확인 |
| :--- | :--- | :--- | :--- |
| 정상 양산 | Mock 09 (yield 96.2%, COMPLETED) | NORMAL | ☐ |
| 수율 EXCELLENT | yield_pct = 98.5% | NORMAL (세분류 EXCELLENT) | ☐ |
| 수율 WARNING | yield_pct = 93.0% | WARNING (R23, 세분류 WARNING) | ☐ |
| 수율 MARGINAL | yield_pct = 85.0% | WARNING (R23, 세분류 MARGINAL) | ☐ |
| 수율 CRITICAL | yield_pct = 75.0% | DANGER (R23, 세분류 CRITICAL) | ☐ |
| LOT 강제 종료 | Mock 10 (ABORTED, yield 94.2%) | WARNING (R23) | ☐ |
| Teaching 미완성 | ET=52 전수 FAIL (Mock 05 기반) | DANGER (R08, R09) | ☐ |
| 칩핑 초과 | chipping_top_um = 55.0 | DANGER (R13) | ☐ |
| 블레이드 마모 | blade_wear_index = 0.75 | WARNING (R16) | ☐ |
| CAM_TIMEOUT 다발 | daily_count = 4 | DANGER (R26) | ☐ |
| 숫자형 레시피 | recipe_id = "446275" | DANGER (R31) | ☐ |
| 비정상 전환 | RUN → STOP (무경고) | DANGER (R38c) | ☐ |
| AggEx 케이스 | VISION_SCORE_ERR + LotController 키워드 5건/일 | DANGER (R33) | ☐ |
| 연쇄 패턴 | LIGHT_PWR_LOW → SIDE ET=52 비율 상승 | WARNING → DANGER (연쇄 상향) | ☐ |

### 16.3 Historian 연동 쿼리 정합성

Historian 작업명세서 §3.3 및 §12.5에서 정의한 쿼리 패턴과의 정합성을 검증한다.

| 쿼리 | 용도 | 기대 결과 | 확인 |
| :--- | :--- | :--- | :--- |
| LOT별 INSPECTION_RESULT 조회 | Unit-level Rule 판정 원시 데이터 | `WHERE lot_id='LOT-20260122-001'` → 2,792건 | ☐ |
| 레시피별 최근 N LOT 수율 시계열 | 2차 검증 EWMA 입력 (v1.0에서는 통계 참조) | `WHERE recipe_id='Carsem_3X3' ORDER BY time DESC LIMIT 28` | ☐ |
| 레시피별 LOT 3개 평균 total_units | expected_total_units 계산 참조 | `WHERE recipe_id='Carsem_3X3' LIMIT 3` → ~2,792 | ☐ |
| 레시피별 ET 분포 통계 | 2차 검증 IF 특징 벡터 (v1.0에서는 R05/R09 보조) | `GROUP BY recipe_id, error_type` | ☐ |
| 장비별 알람 카운터 (R26) | CAM_TIMEOUT_ERR 일일 카운트 보정 | `WHERE hw_error_code='CAM_TIMEOUT_ERR' AND time > NOW()-'1 day'` | ☐ |
| AggEx 카운터 (R33) | VISION_SCORE_ERR+LotController 일일 보정 | `WHERE hw_error_code='VISION_SCORE_ERR' AND hw_error_detail LIKE '%LotController%'` | ☐ |
| EAP_DISCONNECTED (R34) | 주간 카운트 보정 | `WHERE hw_error_code='EAP_DISCONNECTED' AND time > NOW()-'7 days'` | ☐ |

### 16.4 ORACLE_ANALYSIS 페이로드 정합성

| 항목 | 기준 | 확인 |
| :--- | :--- | :--- |
| timestamp | ISO 8601 UTC 밀리초 (.fffZ) | ☐ |
| message_id | UUID v4 | ☐ |
| equipment_status | 포함하지 않음 (§5.1 규칙) | ☐ |
| judgment | NORMAL / WARNING / DANGER enum | ☐ |
| violated_rules | 위반 Rule 목록 정확 | ☐ |
| threshold_proposal | v1.0에서 항상 null | ☐ |
| isolation_forest_score | v1.0에서 항상 null | ☐ |
| Retained 발행 | Retain=true 확인 | ☐ |
| Mock 23~25 구조 호환 | 기존 ORACLE_ANALYSIS Mock과 필드 호환 | ☐ |

### 16.5 데이터 컨벤션 준수

| 항목 | 기준 | 확인 |
| :--- | :--- | :--- |
| JSON 필드명 | snake_case (inspection_detail 내부만 PascalCase) | ☐ |
| Historian 조회 시 PascalCase | inspection_detail JSONB → PascalCase 원본 유지 | ☐ |
| timestamp | ISO 8601 UTC 밀리초 `.fffZ` | ☐ |
| message_id | UUID v4 (RFC 4122) | ☐ |

### 16.6 Graceful Shutdown

| 항목 | 기준 | 확인 |
| :--- | :--- | :--- |
| SIGTERM 수신 | 진행 중 판정 완료 대기 (최대 5초) | ☐ |
| MQTT 해제 | 구독 해제 → 정상 DISCONNECT | ☐ |
| DB 해제 | 커넥션 풀 정상 close | ☐ |

---

## 17. 절대 금지 사항

- ❌ **실로그 기반 Mock(01~17)의 수치 변경 금지** — Carsem 14일 실측값
- ❌ **Rule 38개 번호(R01~R38c) 재배치 금지** — 새 Rule은 R39부터 부여
- ❌ **기존 8개 토픽 패턴(`ds/{eq}/heartbeat` 등) 구조 변경 금지**
- ❌ **PascalCase ↔ snake_case 무단 변환 금지** — inspection_detail 내부는 PascalCase, 나머지 snake_case
- ❌ **`saw_process` 필드 부활 금지** (README.md 제외 정책 준수)
- ❌ **R38a/R38b를 1차 검증에서 활성화 금지** — 2차 검증 모듈 완성 전까지 판정에서 제외

---

## 18. 실측 기준값 (Carsem 현장, 참조용)

| 지표 | 실측값 | 비고 |
| :--- | :--- | :--- |
| Heartbeat 주기 | 3초 | 예외 중에도 정상 |
| STATUS 주기 | 6초 | — |
| takt_time | ~1,620ms | MAP+PRS+SIDE 합산 |
| total_units/Lot | 2,792 | 349 Strip × 8슬롯 |
| 정상 수율 (Carsem_3X3) | 96.2% | 28 LOT 학습 기반 |
| Lot 소요시간 | 82분 (정상) | 정상 40~180분, 최대 370분 |
| ABORTED 수율 (참고) | 94.2% | 656 유닛 처리 후 중단 |
| 재연결 백오프 | 1s→2s→5s→15s→30s, max 60s | jitter ±20% |

---

## 부록 A. 용어 정의

| 용어 | 설명 |
| :--- | :--- |
| MARGINAL | Pass와 Fail 사이의 회색지대 (수율 80~95%). Oracle 1차 검증의 핵심 감지 대상 |
| Rule DB | 레시피별 판정 임계값을 저장하는 DB 테이블. 코드 수정 없이 기준 변경 가능 |
| Teaching | 신규 레시피 등록 시 비전 알고리즘 학습 과정. 최초 50 Strip 모니터링 |
| EWMA | Exponentially Weighted Moving Average. 지수가중이동평균 (2차 검증) |
| MAD | Median Absolute Deviation. 중앙값 절대 편차 (2차 검증) |
| Isolation Forest | 복합 지표 기반 이상 감지 비지도 학습 모델 (2차 검증) |
| 시딩값 | 오퍼레이터가 레시피 최초 투입 시 입력하는 예상 정상 범위 초기값 |

---

## 부록 B. 개정 이력

| 버전 | 일자 | 변경 내용 |
| :--- | :--- | :--- |
| v1.0 | 2026-04-21 | 최초 작성. 1차 Rule-based 검증 구현 명세. 2차 검증 인터페이스 예약 |
| v1.1 | 2026-04-21 | 문서 간 교차 검증 반영: ① R23 수율 5단계 세분류(EXCELLENT/MARGINAL) 추가 (API §5.2) ② LOT_END enrichment 전략 명시 (recipe_id 미포함) ③ R33 AggregateException hw_error_detail 키워드 필터 정정 (API §6.4) ④ 장비 상태 캐시에 v3.4 진행률 3필드 + R38c 상태 전환 규칙 추가 ⑤ 레시피 전환 판정 기준표 + 실측 레시피 목록 추가 (API §7.3) ⑥ 알람-레시피 연쇄 감지 패턴 추가 (이벤트 정의서 §E-4) ⑦ Historian 조회 쿼리 geometric 컬럼 추가 + process 독립 컬럼 정정 ⑧ WARNING 예시 judgment=DANGER로 정정 (yield 68.5% < 90% CRITICAL) |

---

*문서번호: DS-ORACLE-SPEC-001 v1.1*
*최종 수정: 2026-04-21*
