# virtual-shipyard-simulator

실제 선종과 실제 공정 이름을 쓰는 가상 조선소에서 끝없이 이벤트를 만드는 데이터 소스다.
데이터 플랫폼(수집 → 적재 → 모델링)에 넣을 원천이 목적이다.
노이즈 없는 정답 로그(truth)와 지연·중복·누락을 섞은 방출 로그(emitted)를 함께 남겨, 파이프라인이 노이즈를 얼마나 복원했는지 채점할 수 있게 한다.

교육용 게임인 [종이배 조선소 시뮬레이터](https://github.com/loozy5331/virtual-paper-shipbuilding-factory-simulator)와는 레포를 나눈다. 코드는 공유하지 않고 개념만 옮긴다([ADR-001](docs/adr/001-repo-split.md)).

## 원칙

### 공개 출처만 쓴다

특정 조선소의 내부 자료(호선 번호, 블록 코드, 사내 일정·실적)는 쓰지 않는다. 교육 과정 등에서 접한 자료도 마찬가지다.

| 실제로 쓰는 것 | 가상으로 만드는 것 |
| --- | --- |
| 선종과 표준 크기, 공정 이름, 자재 분류, 공공 데이터에서 맞춘 기간과 발생률 | 조선소 이름, 호선 번호(`H-2601` 형식), 선주사, 블록 번호 체계, 도크·작업장 배치 |

### 숫자마다 근거 등급을 단다

`params/*.yaml`의 모든 숫자에 셋 중 하나를 붙인다. 지금은 대부분 가정이고, 공개 데이터로 출처·맞춤으로 바꿔 간다.

| 근거 등급 | 뜻 | 예 |
| --- | --- | --- |
| 출처 | 공개 자료에 그 숫자가 그대로 있다 | LNG선 진수 → 인도 약 7개월(기사) |
| 맞춤 | 공개 데이터로 분포를 맞췄다 | 블록 작업 시간 분포(Mendeley) |
| 가정 | 근거가 없어 정한 값, 바꿀 대상 | 설비 수리 시간 |

숫자가 기대는 공개 자료(기사·공시)는 [docs/sources.md](docs/sources.md)에 모은다.

### 이벤트 계약

모든 이벤트는 같은 봉투(`schemas/envelope.json`)에 담는다. 봉투는 0단계에서 고정하고, 이후에는 `event_type`과 payload 필드를 더하기만 한다.

## 실행

명령 세 줄로 정답 로그 → 방출 로그 → 노이즈 리포트가 나온다.

```bash
uv run python -m sim --seed 0 --until 2031-11-02        # 정답 로그 out/truth/dt=YYYY-MM-DD/part-0.jsonl
uv run python -m emitter --truth out/truth --seed 0      # 방출 로그 out/emitted/dt=<도착 날짜>/part-0.jsonl
uv run python -m emitter.report                          # 노이즈 리포트(--json이면 숫자로)
```

- `sim`: `--forever`면 멈출 때까지, `--out FILE`이면 파일 하나. 시작부터 약 3년은 인도가 없는 워밍업이다(ADR-004)
- `emitter`: `--seed`는 노이즈 시드(시뮬레이션 시드와 따로). 같은 정답 로그로 노이즈만 바꿔 여러 번 만들 수 있다(ADR-005)
- 경계(ADR-007): `out/truth`는 원천의 기록이라 시뮬레이터가 보존한다. `out/emitted`는 플랫폼의 착륙 구역이다. 시뮬레이터는 쓰기만 하고, 보존·정리·수집 위치는 플랫폼이 관리한다
- `uv run python -m sim.periods --seeds 20`: 구간 평균 ≈ 마일스톤 기간표인지

### 누락 찾기와 재발행(ADR-006·008)

원천(방출기)은 출처 시스템마다 하루 한 번 마감 집계(`system.manifest_published`, 보낸 개체별 마지막 `seq`)를 낸다. 집계 범위는 마감 전 `lookback_days`(`params/v0.yaml`, 가정 30일) 안에 이벤트를 보낸 개체뿐이다. 받은 것과 집계를 맞춰 보는 대사와 재발행 요청은 플랫폼이 한다.

```bash
uv run python -m emitter.replay --requests out/requests.jsonl --at 2031-11-02T09:00:00   # 플랫폼이 만든 요청으로 재발행
```

- 요청 파일은 한 줄에 `{"entity_key", "seq"}`(`schemas/replay_request.json`). 형식이 틀린 줄이 있으면 아무것도 보내지 않는다
- 재발행본은 `event_id`·`occurred_at`·payload가 그대로이고 `emitted_at`만 처리 시각이다. 노이즈는 없다
- 계약(`seq` + 마감 집계)만으로 누락을 모두 찾을 수 있다는 것은 `tests/contract/test_recoverable.py`가 보인다. 5년 실행(시드 0)의 누락 266개는 `seq` 빈 번호로 199개, 마감 집계로 끝 번호 67개를 찾는다

### Kafka로 보내기(ADR-007)

```bash
docker compose up -d redpanda        # 개발용 Redpanda(localhost:9092), 토픽 자동 생성
uv sync --extra kafka                # confluent-kafka는 선택 의존성
uv run python -m emitter --sink kafka --checkpoint out/emitter.ckpt --copy-dir out/emitted
uv run python -m emitter.report      # 채점은 사본(--copy-dir)으로
```

- 토픽 `<source>.events`(예: `mes.events`)와 마감 집계 `<source>.manifest`, 키는 `entity_key`, 값은 봉투 JSON, 메시지 시각은 `emitted_at`
- 브로커가 내려가면 버리지 않고 기다린다. 멈췄다 다시 켜면 `--checkpoint`에서 이어 보낸다. 마지막 체크포인트 뒤에 보낸 것은 한 번 더 갈 수 있어(at-least-once) 이어 보낸 시작점을 출력한다
- 6년치(77,802개)를 보내다 브로커를 내리고 방출기를 강제 종료한 뒤 다시 켜도 토픽에 빠진 메시지가 없다. 사본에는 체크포인트 뒤 66줄이 한 번 더 들어갔다

### 컨테이너와 재발행 서비스(ADR-012)

```bash
docker compose --profile source up --build   # sim(5년, 끝나면 멈춤) → emitter · replay, 둘 다 Kafka로
```

- 이미지 하나(`Dockerfile`)가 `sim`, `emitter --sink kafka`, `emitter.replay.service`를 담고, 명령만 바꾼다. 볼륨은 `/app/out`
- 재발행 서비스는 요청 디렉터리(`out/requests/`)의 `*.jsonl`을 5초마다 살펴 이름 순서로 재발행하고 `done/`으로 옮긴다. 형식이 틀린 파일은 보내지 않고 `failed/`로 옮기며 까닭을 `<이름>.error`에 쓴다. 다 쓴 파일만 처리하도록 다른 이름(`.tmp`)으로 쓰고 바꿔 넣는다
- 처리 시각(`emitted_at`)은 방출 로그에서 가장 늦은 도착 시각 + 1초다
- `--sink kafka`(compose의 기본)면 처음 방출과 같은 토픽·키로 보내고, 브로커 확인 뒤 방출 로그(사본)에 쓰고 요청을 옮긴다. `emitter.replay`에도 같은 옵션이 있다
- 5년(시드 0) 누락 266개를 요청 하나로 넣으면 토픽에 정답 55,803개가 모두 있다
- 호스트에서 한 번 돌리기: `uv run python -m emitter.replay.service --once`

### 실시간 재생(ADR-013)

```bash
uv run python -m sim --forever --speed 1440                  # 가상 하루 = 실제 1분, 하루 앞서 쓴다
uv run python -m emitter --sink kafka --follow --speed 1440  # 정답 로그를 따라 읽으며 도착 시각에 맞춰 보낸다
docker compose -f docker-compose.yml -f docker-compose.live.yml --profile source up --build   # 컨테이너로
```

- `--speed N`: 가상 N초 = 실제 1초. 방출기는 `emitted_at` 간격대로 보내고, 메시지 내용과 순서는 속도가 없을 때와 같다
- `--follow`: 끝없는 정답 로그를 따라 읽는다. 쓰는 중인 줄은 건너뛴다
- 정답 로그가 `--max-gb`(기본 10GB)에 닿으면 `sim`이 그날까지 쓰고 멈춘다. 1440이면 실제 1년 넘게 걸린다

### 설비 고장(ADR-010)

작업장 하나가 설비 하나다. 가공 공장·조립장·도크·선석이 `params/v0.yaml`의 `failures`(평균 고장 간격, 수리 시간, 원인, 모두 가정)대로 고장 나고, 고장 중에는 그 작업장의 작업이 멈췄다가 고치면 이어 한다. 시운전 팀은 고장 나지 않는다.

```json
{"event_id":"01a1a1c5-3b60-7017-872d-b75b6c9ff073","event_type":"equipment.status_changed","schema_version":1,"source":"eam","occurred_at":"2026-11-03T23:17:00+09:00","emitted_at":"2026-11-03T23:17:00+09:00","run_id":"v0-s0","entity_key":"ASM-6","seq":1,"hull_no":null,"block_id":null,"process":null,"resource_id":"ASM-6","payload":{"status":"down","reason":"hydraulic_failure"}}
```

- 고치면 같은 설비의 다음 `seq`로 `status: "up"`, `reason: null`
- 5년(시드 0) 가용률은 가공 97.0% · 조립장 97.6% · 도크 98.0% · 선석 98.2%

### 자재 발주와 입고(ADR-011)

호선마다 강재(4몫)·주기관·배관·전선을 계획한 필요일에 맞춰 발주하고(출처 erp), 자재별 지연 분포(`params/v0.yaml`의 `materials`, 모두 가정)대로 입고한다. 자재가 들어오기 전에는 그 자재가 필요한 작업(블록 가공 착수, 진수, 안벽 의장 착수)이 기다린다.

```json
{"event_id":"01ae25c9-80e0-7ef8-9ef3-8dbaf143e3ba","event_type":"material.ordered","schema_version":1,"source":"erp","occurred_at":"2028-07-18T03:05:00+09:00","emitted_at":"2028-07-18T03:05:00+09:00","run_id":"v0-s0","entity_key":"PO-2605-05","seq":1,"hull_no":"H-2605","block_id":null,"process":"erection","resource_id":null,"payload":{"material":"main_engine","quantity":1,"unit":"set","supplier":"대한기관","need_date":"2029-08-12","promised_date":"2029-07-13"}}
{"event_id":"01b54025-61a0-7110-9501-7beed09d8784","event_type":"material.received","schema_version":1,"source":"erp","occurred_at":"2029-07-06T05:15:00+09:00","emitted_at":"2029-07-06T05:15:00+09:00","run_id":"v0-s0","entity_key":"PO-2605-05","seq":2,"hull_no":"H-2605","block_id":null,"process":"erection","resource_id":null,"payload":{"material":"main_engine","quantity":1,"unit":"set","supplier":"대한기관"}}
```

- 리드타임 = 같은 발주 번호(`entity_key`)의 입고 − 발주. 5년(시드 0) 중앙값은 강재 58.6일 · 주기관 356.0일 · 배관 116.7일 · 전선 87.7일
- 대부분의 지연은 발주 여유가 흡수해, 자재를 기다린 작업은 드물다(블록 가공 착수 5번, 안벽 의장 착수 1번)

### 출력 예시

정답 로그의 한 줄(수주). 정답 로그는 `emitted_at` = `occurred_at`이다.

```json
{"event_id":"01b1b86d-73e0-716d-b1bc-61c87e0fbd1c","event_type":"order.contracted","schema_version":1,"source":"erp","occurred_at":"2029-01-11T17:37:00+09:00","emitted_at":"2029-01-11T17:37:00+09:00","run_id":"v0-s0","entity_key":"H-2901","seq":1,"hull_no":"H-2901","block_id":null,"process":null,"resource_id":null,"payload":{"ship_type":"vlcc","owner":"동방유조","contract_delivery_date":"2032-04-07","block_count":190}}
```

방출 로그 `dt=2029-04-12`에 든 한 줄. 4월 11일 11:15에 끝난 블록 조립이 하루 넘게 늦게 도착했다.

```json
{"event_id":"01b3868c-10a0-7364-99fc-236e2b302694","event_type":"block.process_completed","schema_version":1,"source":"mes","occurred_at":"2029-04-11T11:15:00+09:00","emitted_at":"2029-04-12T13:36:53+09:00","run_id":"v0-s0","entity_key":"H-2704-B135","seq":4,"hull_no":"H-2704","block_id":"H-2704-B135","process":"block_assembly","resource_id":"ASM-5","payload":{"work_hours":2187.1}}
```

### 게이트 확인(11/8): 노이즈가 섞인 이벤트가 쌓인다

위 세 줄을 시드 0, 5년으로 돌린 리포트(세 명령 합쳐 약 10초). 6·7단계부터 설비 고장 이벤트(5,527개)와 자재 발주·입고 이벤트(895개)가 들어 있다:

```
정답 55,803개 → 방출 56,096줄

노이즈(설정 → 실제)
- 누락: 0.50% → 0.48% (266개)
- 중복: 1.00% → 1.00% (559개)
- 늦음(10분 넘게): 3.00% → 3.09% (1,715개)
- 순서 어긋남(지연의 결과): 9.58% (5,323개)

지연(초) p50 5 · p95 39 · p99 10866 · 최대 163255
```

- 설정 비율대로 측정된다(누락·중복·늦음 모두 설정의 ±10% 안)
- 방출 로그만으로 찾을 수 있는지(중복은 `event_id`, 누락은 `seq` 빈 번호와 마감 집계)는 `tests/contract/test_recoverable.py`가 보인다(ADR-008)

## 구조

```
sim/            시뮬레이터: 엔진(engine·dock·planner·orders), 시계·번호, 재생 속도(pace), params 읽기, 명령(cli)
  io/           이벤트 읽기·쓰기, 스키마 검증
emitter/        방출기: 노이즈, 마감 집계, 체크포인트, Kafka 출력, 노이즈 리포트
  replay/       재발행(python -m emitter.replay)과 재발행 서비스(python -m emitter.replay.service)
params/         숫자와 근거 등급(YAML)
schemas/        이벤트 봉투·payload·재발행 요청 스키마(계약)
tests/          sim/ · emitter/ · contract/(스키마, 계약으로 누락을 모두 찾는다는 증명)
docs/           개발 계획, ADR, 출처
```

## 개발

```bash
uv sync                  # .venv(Python 3.12)와 의존성
uv run ruff check .      # 린트
uv run pytest            # 테스트
```

## 결정 기록

- [ADR-001 레포 분리](docs/adr/001-repo-split.md)
- [ADR-002 시간 모델](docs/adr/002-time-model.md)
- [ADR-003 세미 탠덤 도크](docs/adr/003-semi-tandem-dock.md)
- [ADR-004 수주와 납기, 끝없는 실행](docs/adr/004-orders-and-endless-run.md)
- [ADR-005 방출기와 노이즈](docs/adr/005-emitter-noise.md)
- [ADR-006 재발행과 대사](docs/adr/006-replay-and-reconciliation.md)
- [ADR-007 출력 방식과 경계](docs/adr/007-output-and-boundary.md)
- [ADR-008 대사는 플랫폼에, 원천은 계약과 증명만](docs/adr/008-reconciliation-as-test.md)
- [ADR-010 설비 고장](docs/adr/010-equipment-failure.md)
- [ADR-011 자재 발주와 입고 지연](docs/adr/011-material-supply.md)
- [ADR-012 컨테이너와 재발행 요청 디렉터리](docs/adr/012-container-and-request-directory.md)
- [ADR-013 재생 속도와 정답 로그 상한](docs/adr/013-playback-speed.md)

## 만든 것

- 0단계: 레포 구조, pytest·ruff CI, CI 통과 뒤 자동 머지
- 0단계: README 원칙, ADR-001·002
- 0단계: 이벤트 봉투 스키마(`schemas/envelope.json`)와 이벤트 7종 payload 스키마, 예시 검증 테스트(7단계까지 10종)
- 1단계: SimPy 엔진으로 LNG선 한 척(간이 필수 공정 5개, 고정 소요 시간) → `truth.jsonl`. 같은 입력이면 같은 파일, 마일스톤 강재절단 < 착공 < 진수 < 인도
- 1단계: 선종 3개(LNG선·VLCC·컨테이너선)의 블록 수를 크기에 맞춤(강재 중량 ÷ 블록 평균 무게, 170·190·260개), 블록 작업 시간은 무게에 비례, 조립장 정반 칸
- 1단계: 블록 착수 계획(한 척의 블록을 약 3개월에 나눠 착수), 가공 속도는 공장 속성 하나로
- 1단계: 대형 조선소 한 곳 규모 — 연 24척, 직영 9,000 + 협력사 20,000명, 가공 5 · 조립장 6 · 도크 5 · 선석 12 · 시운전 팀 3(가동률 66~74%)
- 1단계: `work_hours`를 블록 무게 비례 공수(MH)로
- 1단계: 계약 → 인도 약 3~3.5년(일감 3년 이상인 공개 자료에 맞춤)
- 2단계: 계약 단위 수주(한 계약 1~4척), 첫해 24척이 앞쪽에 몰린 고정 수주 → 도크 대기(최대 35일)와 납기 지연이 생긴다. 작업장은 먼저 온 순서로 배정, 용량 초과 없음
- 2단계: 세미 탠덤 도크(ADR-003) — 도크 하나에 배 한 척 + 배 반쪽, 진수 때 물을 채워 반쪽 배를 앞으로 옮겨 이어 짓는다
- 3단계: 공정 소요 시간을 로그정규 분포(`params/v0.yaml`, cv 가정값)에서 뽑는다. 같은 시드면 같은 로그, 다른 시드면 다른 로그. 시드 20개의 구간 평균이 기간표의 ±8% 안
- 4단계: 끝없는 실행(ADR-004) — 첫해 고정 목록 다음 포아송 수주, 계약 때 도크 자리를 예약해 착수일·납기를 정한다(공정 시간 80% 분위수), `--until`(기본 5년)·`--forever`, 날짜별 파일 `out/truth/dt=YYYY-MM-DD/part-0.jsonl`. 끝난 블록·배의 상태를 지워 몇 년을 돌려도 메모리가 일정(15년 7.5~10MB)
- 5단계: 방출기(ADR-005) — 정답 로그에 지연 도착·중복·누락을 이벤트별 난수로 섞어 도착 순서로 쓴다(순서 어긋남은 지연의 결과). 노이즈 리포트는 설정 대비 실제 비율과 `event_id`·`seq`로 찾은 수를 낸다. 게이트 확인은 위 "실행"
- 게이트 뒤: 재발행과 대사(ADR-006) — 원천은 하루 한 번 마감 집계(최근 `lookback_days` 안의 개체만)를 내고, 플랫폼 대역인 리포트가 대사로 끝 번호 누락까지 찾아 재발행 요청 파일을 쓰고, `emitter.replay`가 정답에서 다시 보낸다
- 게이트 뒤: 출력 방식과 경계(ADR-007) — Kafka 출력(`--sink kafka`, 개발용 Redpanda), 브로커 장애 때 기다리기, 체크포인트에서 이어 보내기, 채점용 사본
- 게이트 뒤: 대사를 플랫폼에(ADR-008) — 리포트는 노이즈 실측만, 재발행 요청 스키마(`schemas/replay_request.json`)와 검증, 계약만으로 누락을 모두 찾는다는 증명은 `tests/contract/test_recoverable.py`
- 6단계: 설비 고장(ADR-010) — 작업장마다 고장(지수분포 간격)과 수리(로그정규)를 `equipment.status_changed`로 내고, 고장 중에는 그 작업장의 작업이 멈춘다. 5년 가용률 97~98%
- 7단계: 자재 발주와 입고 지연(ADR-011) — 호선마다 강재(4몫)·주기관·배관·전선을 필요일에 맞춰 발주(`material.ordered`)하고 자재별 지연 분포대로 입고(`material.received`)한다. 자재가 들어오기 전에는 그 작업이 기다린다
- 10단계: 컨테이너와 재발행 요청 디렉터리(ADR-012) — 이미지 하나로 sim·emitter·재발행 서비스, 재발행 서비스는 요청 디렉터리를 살펴 처리하고 `done/`·`failed/`로 옮긴다. 개발용 compose `source` 프로필
- 11단계: 재발행을 Kafka로(ADR-012) — `emitter.replay`와 재발행 서비스의 `--sink kafka`, 처음 방출과 같은 토픽·키, 브로커 확인 뒤 사본
- 12단계: 재생 속도(ADR-013) — `sim`·`emitter`의 `--speed`, 방출기의 `--follow`(끝없는 정답 로그 따라 읽기), 정답 로그 상한 10GB, compose `docker-compose.live.yml`

## 브랜치 전략

- `main`: 배포/안정 브랜치
- `develop`: 개발 통합 브랜치. 작업 브랜치는 `develop`에서 분기하여 PR로 병합
- `develop` 대상 PR은 CI(`test`)가 통과하면 GitHub Actions로 자동 머지, `main` 머지는 수동
- 버전은 `main`에 `vX.Y.Z` 태그로 관리 (현재 `v0.4.0`)
