# Issue #2: CPU 과점유 장애 분석

**Labels**: `bug`, `cpu`, `performance`  
**Severity**: High  
**Component**: agent-app-leak — CPU 과점유 시나리오 (`MEMORY_LIMIT=512`, `CPU_MAX_OCCUPY=100`, `MULTI_THREAD_ENABLE=false`)

---

## 요약

`MEMORY_LIMIT=512`(최대), `CPU_MAX_OCCUPY=100`(무제한), `MULTI_THREAD_ENABLE=false` 조건에서  
CpuWorker가 시스템 CPU를 단계적으로 점유하다가 내부 임계치(~50%)를 초과하면  
`[CpuWorker] CPU Threshold Violated`를 선언하고 **SIGTERM**으로 프로세스를 종료한다.

---

## 재현 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04 LTS (Docker, `--privileged`) |
| 바이너리 | `agent-app-leak` (ELF x86_64) |
| 활성 시나리오 | `MEMORY_LIMIT=512`, `CPU_MAX_OCCUPY=100`, `MULTI_THREAD_ENABLE=false` |

### 환경변수

```bash
export AGENT_HOME=/home/agent-admin/agent-app
export AGENT_PORT=15034
export AGENT_UPLOAD_DIR=/home/agent-admin/agent-app/upload_files
export AGENT_KEY_PATH=/home/agent-admin/agent-app/api_keys
export AGENT_LOG_DIR=/var/log/agent-app
export MEMORY_LIMIT=512
export CPU_MAX_OCCUPY=100
export MULTI_THREAD_ENABLE=false
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
   ... MEMORY_LIMIT=512MB, CPU_MAX_OCCUPY=100%, MULTI_THREAD_ENABLE=False
------------------------------------------------------------
All Boot Checks Passed!
Agent READY
2026-05-12 02:19:33,670 [INFO] [SafetyGuard] Process priority lowered (nice=10).
2026-05-12 02:19:33,671 [INFO] Agent listening at port 15034

==================================================
 [ Agent Initiate ] Resource Check
==================================================
 [ MEMORY ] Limit: 512MB       [ OK ]
 [ CPU    ] Limit: 100%        [ WARNING: Recommend Under 50% ]
 [ THREAD ] Concurrency: False [ OK ]
--------------------------------------------------
 >>> SYSTEM STATUS: STABLE. STARTING WORKLOAD MONITORING...
==================================================

2026-05-12 02:19:35,671 [INFO] [CpuWorker] Started. Maximum CPU Limit: 100%
2026-05-12 02:19:35,672 [INFO] [CpuWorker] Current Load: 5.00%
2026-05-12 02:19:38,773 [INFO] [CpuWorker] Current Load: 11.05%
2026-05-12 02:19:41,874 [INFO] [CpuWorker] Current Load: 13.89%
2026-05-12 02:19:44,975 [INFO] [CpuWorker] Current Load: 17.02%
2026-05-12 02:19:48,076 [INFO] [CpuWorker] Current Load: 18.16%
2026-05-12 02:19:51,177 [INFO] [CpuWorker] Current Load: 25.94%
2026-05-12 02:19:54,338 [INFO] [CpuWorker] Current Load: 34.92%
2026-05-12 02:19:57,441 [INFO] [CpuWorker] Current Load: 36.53%
2026-05-12 02:20:00,542 [INFO] [CpuWorker] Current Load: 43.58%
2026-05-12 02:20:03,643 [INFO] [CpuWorker] Current Load: 48.73%
2026-05-12 02:20:06,744 [INFO] [CpuWorker] Current Load: 52.16%
2026-05-12 02:20:06,845 [CRITICAL] [CpuWorker] CPU Threshold Violated! (52.16%).
Terminated
```

- **소요 시간**: CpuWorker 시작 후 약 31 초 만에 SIGTERM
- **종료 신호**: SIGTERM (exit code 143 = 128 + 15)
- **"Terminated"**: 셸이 SIGTERM 수신 후 출력하는 메시지

---

## 근본 원인 분석

### 시나리오 선택 조건

```
MEMORY_LIMIT=512  → [ OK ]
CPU_MAX_OCCUPY=100 → [ WARNING: Recommend Under 50% ]
MULTI_THREAD_ENABLE=false → [ OK ]
→ CpuWorker 시나리오 선택
```

### CPU 부하 상승 패턴

| 경과 시간 | CPU 부하 | 비고 |
|---|---|---|
| 0 s | 5.00 % | 초기 기준 부하 |
| 3 s | 11.05 % | 점진 상승 |
| 6 s | 13.89 % | |
| 9 s | 17.02 % | |
| 12 s | 18.16 % | |
| 15 s | 25.94 % | |
| 18 s | 34.92 % | |
| 21 s | 36.53 % | |
| 24 s | 43.58 % | |
| 27 s | 48.73 % | |
| 30 s | 52.16 % | **내부 임계치(~50%) 초과** |
| 31 s | — | CRITICAL → SIGTERM → 종료 |

### 내부 임계치와 CPU_MAX_OCCUPY의 차이

- `CPU_MAX_OCCUPY=100`은 "상한 없음"을 의미하지만, 바이너리 내부에 **고정 안전 임계치(약 50%)**가 존재한다.
- 이 임계치는 `CPU_MAX_OCCUPY` 설정값과 무관하게 작동하며, CpuWorker 부하가 약 50%를 넘으면 무조건 Watchdog이 동작한다.
- `CPU_MAX_OCCUPY`가 낮은 경우(≤20%)에는 "Healthy System Monitoring" 모드(Cooldown 포함)로 전환된다.

### os.nice(10) 효과와 한계

```
[SafetyGuard] Process priority lowered (nice=10).
```

CFS에서 `nice=10`은 기본(`nice=0`) 대비 CPU 할당 가중치가 약 9.3배 낮다.  
그러나 컨테이너 내 다른 경쟁 프로세스가 없는 환경에서는 nice 값과 무관하게 단일 코어를 독점할 수 있으므로,  
CpuWorker는 의도한 부하보다 빠르게 상승한다.

---

## 영향

| 항목 | 내용 |
|---|---|
| 최대 CPU 점유 | 실험 기준 약 52 % (단일 코어) |
| 다른 프로세스 영향 | `nice=10`으로 일부 완화되나 부하 급상승 구간에서 선점 발생 |
| 서비스 수명 | CpuWorker 시작 후 약 30 초 내 SIGTERM |
| 종료 방식 | SIGTERM (exit 143) → signal handler 실행 가능 |

---

## 개선 방안

1. **CPU_MAX_OCCUPY 조정**: 권장 기준(`Recommend Under 50%`)에 맞게 50 % 이하로 설정  
   → 20 % 이하면 Healthy 모드(Cooldown 포함)로 전환되어 무제한 상승 억제
2. **cgroup CPU 쿼터**: `cpu.cfs_quota_us` / `cpu.cfs_period_us` 또는 Docker `--cpus` 옵션으로 OS 수준 상한 강제
3. **경보 임계치 이중화**: Watchdog 발동(종료) 이전에 별도 경보 임계치(예: 40%)를 설정하여 사전 알림 발송
4. **단계적 부하 조절**: 임계치 근접 시 즉시 종료 대신 부하 감소 후 재측정하는 Cooldown 로직 도입
