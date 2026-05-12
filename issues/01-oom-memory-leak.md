# Issue #1: OOM / Memory Leak 장애 분석

**Labels**: `bug`, `memory`, `oom`  
**Severity**: Critical  
**Component**: agent-app-leak — OOM 시나리오 (`MEMORY_LIMIT < 256`)

---

## 요약

`MEMORY_LIMIT`을 256 MB 미만으로 설정하면 MemoryWorker가 25 MB/3초씩 실제 힙 메모리를 할당한다.  
메모리가 임계치에 도달하면 `[MemoryGuard]`가 CRITICAL 로그를 남기고 **SIGKILL**로 프로세스를 강제 종료한다.

---

## 재현 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04 LTS (Docker, `--privileged`) |
| 바이너리 | `agent-app-leak` (ELF x86_64) |
| 활성 시나리오 | `MEMORY_LIMIT=100`, `MULTI_THREAD_ENABLE=false` |

### 환경변수

```bash
export AGENT_HOME=/home/agent-admin/agent-app
export AGENT_PORT=15034
export AGENT_UPLOAD_DIR=/home/agent-admin/agent-app/upload_files
export AGENT_KEY_PATH=/home/agent-admin/agent-app/api_keys
export AGENT_LOG_DIR=/var/log/agent-app
export MEMORY_LIMIT=100
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
   ... MEMORY_LIMIT=100MB, CPU_MAX_OCCUPY=100%, MULTI_THREAD_ENABLE=False
------------------------------------------------------------
All Boot Checks Passed!
Agent READY
2026-05-12 02:15:13,536 [INFO] [SafetyGuard] Process priority lowered (nice=10).
2026-05-12 02:15:13,537 [INFO] Agent listening at port 15034

==================================================
 [ Agent Initiate ] Resource Check
==================================================
 [ MEMORY ] Limit: 100MB      [ WARNING: Recommend Over 256MB ]
 [ CPU    ] Limit: 100%       [ WARNING: Recommend Under 50% ]
 [ THREAD ] Concurrency: False [ OK ]
--------------------------------------------------
 >>> SYSTEM STATUS: STABLE. STARTING WORKLOAD MONITORING...
==================================================

2026-05-12 02:15:15,556 [INFO] [MemoryWorker] Current Heap: 25MB
2026-05-12 02:15:18,590 [INFO] [MemoryWorker] Current Heap: 50MB
2026-05-12 02:15:21,676 [INFO] [MemoryWorker] Current Heap: 75MB
2026-05-12 02:15:24,697 [INFO] [MemoryWorker] Current Heap: 100MB
2026-05-12 02:15:24,697 [CRITICAL] [MemoryGuard] Memory limit exceeded (100MB >= 100MB) / (Recommend Over 256MB)
2026-05-12 02:15:24,697 [CRITICAL] [MemoryGuard] Self-terminating process 8021 to prevent system instability.
Killed
```

- **소요 시간**: 부트 완료 후 약 11 초 (4 step × 3s)
- **종료 신호**: SIGKILL (exit code 137 = 128 + 9)
- **"Killed"**: 셸이 SIGKILL 수신 후 출력하는 메시지 — OS가 프로세스를 강제 종료했음을 의미

---

## 근본 원인 분석

### 시나리오 선택 조건

```
MEMORY_LIMIT=100 → "WARNING: Recommend Over 256MB"
→ MemoryWorker 시나리오 선택
```

### 메모리 증가 패턴

```
step 1: Heap 25 MB  (기준 할당)
step 2: Heap 50 MB  (+25 MB)
step 3: Heap 75 MB  (+25 MB)
step 4: Heap 100 MB (+25 MB) → MEMORY_LIMIT 도달
```

- **할당 주기**: 3초마다 25 MB씩 실제 힙 메모리 할당 (해제 없음 → 메모리 누수)
- **감시**: MemoryGuard가 현재 힙 크기와 `MEMORY_LIMIT`을 비교
- **종료 방식**: `SIGKILL` — 자가 종료가 아닌 OS 수준의 강제 종료

### 왜 SIGKILL인가

`[MemoryGuard]`는 로그에 "Self-terminating"이라 기록하지만 실제로는 SIGKILL을 사용한다.  
SIGTERM은 프로세스가 종료 거부 가능하지만 SIGKILL은 커널이 즉시 강제 종료하므로,  
메모리 제한 초과 상황에서 안전한 종료를 보장하기 위해 SIGKILL을 선택한 것으로 판단된다.

---

## 영향

| 항목 | 내용 |
|---|---|
| 프로세스 수명 | `MEMORY_LIMIT × (3s / 25MB)` — 100 MB 기준 약 12초 |
| 종료 방식 | SIGKILL (exit 137) → 정상 종료 루틴(atexit, signal handler) 실행 불가 |
| 서비스 가용성 | 프로세스 즉시 종료 → 서비스 중단 |
| 데이터 무결성 | SIGKILL 특성상 버퍼 미플러시 가능 → 로그/데이터 손실 위험 |

---

## 개선 방안

1. **MEMORY_LIMIT 최솟값 상향**: 권장 기준(`Recommend Over 256MB`)에 맞게 256 MB 이상으로 설정
2. **단계적 경보**: 임계치 80% 도달 시 WARN 경보 발송 → 운영자 개입 유도
3. **SIGTERM 우선 사용**: SIGKILL 전 SIGTERM → 정상 종료 루틴 실행 기회 부여
4. **cgroup memory.limit_in_bytes**: OS 수준에서 메모리 상한 강제 (Docker `--memory` 옵션)
5. **프로세스 재시작 정책**: systemd `Restart=on-failure`로 자동 재기동 구성
