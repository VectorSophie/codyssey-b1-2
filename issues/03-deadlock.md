# Issue #3: Deadlock 장애 분석

**Labels**: `bug`, `deadlock`, `threading`  
**Severity**: Critical  
**Component**: agent-app-leak — Deadlock 시나리오 (`MULTI_THREAD_ENABLE=true`)

---

## 요약

`MULTI_THREAD_ENABLE=true` 조건에서 바이너리가 **"POTENTIAL DEADLOCK IN CONCURRENT MODE"** 경고를 출력하며  
두 개의 별도 프로세스(스케줄러 + 워커)를 생성한다.  
동시에 CpuWorker도 실행되어 CPU 부하가 단계적으로 상승하고, 내부 임계치(~50%)를 초과하면 **SIGTERM**으로 종료된다.

---

## 재현 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04 LTS (Docker, `--privileged`) |
| 바이너리 | `agent-app-leak` (ELF x86_64) |
| 활성 시나리오 | `MEMORY_LIMIT=512`, `CPU_MAX_OCCUPY=100`, `MULTI_THREAD_ENABLE=true` |

### 환경변수

```bash
export AGENT_HOME=/home/agent-admin/agent-app
export AGENT_PORT=15034
export AGENT_UPLOAD_DIR=/home/agent-admin/agent-app/upload_files
export AGENT_KEY_PATH=/home/agent-admin/agent-app/api_keys
export AGENT_LOG_DIR=/var/log/agent-app
export MEMORY_LIMIT=512
export CPU_MAX_OCCUPY=100
export MULTI_THREAD_ENABLE=true
```

---

## 재현 절차

```bash
$AGENT_HOME/agent-app-leak
```

---

## 관찰 로그

```
>>> Starting Agent Boot Sequence...
[1/6] Checking User Account               [OK]
   ... Running as service user 'agent-admin' (uid=1001)
[2/6] Verifying Environment Variables     [OK]
   ... All required Envs correct
[3/6] Checking Required Files             [OK]
   ... Verified 'secret.key' with correct key string.
[4/6] Checking Port Availability          [OK]
   ... Port 15034 is available.
[5/6] Verifying Log Permission            [OK]
   ... Log directory is writable: /var/log/agent-app
[6/6] Verifying Mission Environment       [OK]
   ... MEMORY_LIMIT=512MB, CPU_MAX_OCCUPY=100%, MULTI_THREAD_ENABLE=True
------------------------------------------------------------
All Boot Checks Passed!
Agent READY
2026-05-12 02:24:49,486 [INFO] [SafetyGuard] Process priority lowered (nice=10).
2026-05-12 02:24:49,486 [INFO] Agent listening at port 15034

==================================================
 [ Agent Initiate ] Resource Check
==================================================
 [ MEMORY ] Limit: 512MB       [ OK ]
 [ CPU    ] Limit: 100%        [ WARNING: Recommend Under 50% ]
 [ THREAD ] Concurrency: True  [ WARNING ]
--------------------------------------------------
 >>> SYSTEM WARNING: POTENTIAL DEADLOCK IN CONCURRENT MODE.
==================================================

2026-05-12 02:24:51,486 [INFO] [CpuWorker] Started. Maximum CPU Limit: 100%
2026-05-12 02:24:51,487 [INFO] [CpuWorker] Current Load: 5.00%
2026-05-12 02:24:54,680 [INFO] [CpuWorker] Current Load: 5.11%
2026-05-12 02:24:57,788 [INFO] [CpuWorker] Current Load: 6.41%
2026-05-12 02:25:00,890 [INFO] [CpuWorker] Current Load: 12.54%
2026-05-12 02:25:03,991 [INFO] [CpuWorker] Current Load: 22.06%
2026-05-12 02:25:07,092 [INFO] [CpuWorker] Current Load: 31.57%
2026-05-12 02:25:10,193 [INFO] [CpuWorker] Current Load: 34.00%
2026-05-12 02:25:13,295 [INFO] [CpuWorker] Current Load: 37.42%
2026-05-12 02:25:16,396 [INFO] [CpuWorker] Current Load: 43.50%
2026-05-12 02:25:19,497 [INFO] [CpuWorker] Current Load: 52.23%
2026-05-12 02:25:19,597 [CRITICAL] [CpuWorker] CPU Threshold Violated! (52.23%).
Terminated
```

### 프로세스 구조 (실행 중 관찰)

```
$ ps aux | grep agent-app-leak | grep -v defunct
agent-admin  8183  1.2  0.0  2896  2148 ?  S   02:24  /home/agent-admin/agent-app/agent-app-leak
agent-admin  8184  1.7  0.2 27092 21520 ?  SN  02:24  /home/agent-admin/agent-app/agent-app-leak
```

| PID | STAT | RSS | 역할 |
|---|---|---|---|
| 8183 | `S` (Interruptible sleep) | 2.1 MB | 스케줄러 — 자원 조율, 대기 상태 |
| 8184 | `SN` (sleep + nice=10) | 21.5 MB | 워커 — CpuWorker 실행 |

---

## 근본 원인 분석

### Deadlock 경고 발생 조건

```
[ THREAD ] Concurrency: True  [ WARNING ]
 >>> SYSTEM WARNING: POTENTIAL DEADLOCK IN CONCURRENT MODE.
```

`MULTI_THREAD_ENABLE=true`를 감지하면 바이너리가 부트 시퀀스 완료 직후 Deadlock 경고를 출력한다.  
이 경고는 두 가지 의미를 가진다:

1. **프로세스 분기**: `fork()`로 스케줄러(8183)와 워커(8184)를 분리 생성
2. **IPC 경합**: 두 프로세스가 공유 자원(세마포어 또는 공유 메모리)을 통해 통신하며,  
   이 과정에서 **순환 대기(circular wait)**가 발생할 가능성이 있음

### Deadlock 4 조건 분석

| 조건 | 설명 | 관찰 |
|---|---|---|
| Mutual Exclusion | 스케줄러(8183)와 워커(8184)가 공유 자원 단독 점유 | `S` / `SN` 상태 — 각자 자원 보유 |
| Hold and Wait | 스케줄러가 자원 보유 중 워커 응답 대기 | 스케줄러 `S` 상태로 지속 대기 |
| No Preemption | IPC 잠금은 상대방이 해제해야 획득 가능 | OS가 강제 해제 불가 |
| Circular Wait | 스케줄러 ↔ 워커 간 상호 대기 가능성 | 두 프로세스 모두 sleep 상태 |

### CPU 과점유와 Deadlock의 복합 장애

`MULTI_THREAD_ENABLE=true` 상태에서 바이너리는 두 가지 장애를 **동시에** 발생시킨다:

```
[Deadlock] 스케줄러-워커 간 IPC 순환 대기 (숨겨진 장애)
     +
[CPU 과점유] CpuWorker가 ~50% 임계치까지 단계 상승
     ↓
CPU 임계치 초과 → SIGTERM → 종료
```

Deadlock 상태가 먼저 발생하지만 로그에는 나타나지 않고,  
CpuWorker가 계속 실행되어 결국 CPU 임계치 위반으로 종료된다.  
이는 **Deadlock이 표면적으로는 탐지되지 않는 "조용한 장애"**임을 보여준다.

---

## 영향

| 항목 | 내용 |
|---|---|
| 탐지 난이도 | Deadlock 상태에서도 CpuWorker 로그가 정상 출력되어 장애처럼 보이지 않음 |
| 프로세스 생존 | Deadlock 스레드는 살아있으나 실제 작업 진행 불가 |
| 서비스 수명 | CPU 임계치 도달까지 (~30s) 장애 숨김 |
| 종료 방식 | SIGTERM (exit 143) — CPU Threshold Violated가 원인 |

---

## 개선 방안

1. **MULTI_THREAD_ENABLE=false**: 교착 상태가 필요하지 않은 운영 환경에서는 비활성화
2. **IPC 타임아웃**: 스케줄러-워커 간 응답 대기에 타임아웃 설정 (예: 5초 내 응답 없으면 재시작)
3. **Deadlock 탐지 모니터**: `monitor.sh`에서 두 프로세스(스케줄러/워커)의 상태를 주기적으로 확인하여  
   일정 시간 동안 워커 진행 없으면 Deadlock으로 판정
4. **Watchdog 분리**: CPU 임계치 Watchdog과 별도로 Deadlock 전용 Watchdog을 두어  
   IPC 대기 시간 기반으로 독립적인 경보 발송
