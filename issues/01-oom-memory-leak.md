# Issue #1: OOM / Memory Leak 장애 분석

**Labels**: `bug`, `memory`, `oom`  
**Severity**: Critical  
**Component**: agent-leak-app — `run_oom()` scenario

---

## 요약

`MEMORY_LIMIT` 이하로 설정된 임계치에 도달할 때까지 **Python `bytearray` 10 MB 블록을 반복 할당하고 절대 해제하지 않는** 메모리 누수가 발생한다.  
RSS가 임계치를 초과하면 `[MemoryGuard]`가 프로세스를 강제 종료한다.

---

## 재현 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04 LTS (Docker, `--privileged`) |
| Python | 3.12 |
| 활성 시나리오 | `MEMORY_LIMIT < 512`, `MULTI_THREAD_ENABLE=false` |

### 환경변수

```bash
export MEMORY_LIMIT=100          # 임계치: 100 MB
export CPU_MAX_OCCUPY=100
export MULTI_THREAD_ENABLE=false
```

---

## 재현 절차

```bash
python3 $AGENT_HOME/agent_leak_app.py
```

---

## 관찰 로그 (Before — MEMORY_LIMIT=100)

```
>>> Starting Agent Boot Sequence...
[1/5] Checking User Account               [OK]
[2/5] Verifying Environment Variables     [OK]
[3/5] Checking Required Files             [OK]
[4/5] Checking Port Availability          [OK]
[5/5] Verifying Log Permission            [OK]
All Boot Checks Passed!
Agent READY
2026-05-11 15:56:39,198 [INFO] [SafetyGuard] Process priority lowered (nice=10).
2026-05-11 15:56:39,198 [INFO] Agent listening at port 15034
2026-05-11 15:56:39,198 [INFO] === Agent Started. Memory Leak Mode. ===
2026-05-11 15:56:39,198 [INFO] [MemoryGuard] Limit set to 100 MB.
2026-05-11 15:56:39,199 [INFO] [Memory] Leaked +10 MB. Total RSS: 22 MB (step 1)
2026-05-11 15:56:41,199 [INFO] [Memory] Leaked +10 MB. Total RSS: 32 MB (step 2)
2026-05-11 15:56:43,199 [INFO] [Memory] Leaked +10 MB. Total RSS: 42 MB (step 3)
2026-05-11 15:56:45,201 [INFO] [Memory] Leaked +10 MB. Total RSS: 52 MB (step 4)
2026-05-11 15:56:47,201 [INFO] [Memory] Leaked +10 MB. Total RSS: 62 MB (step 5)
2026-05-11 15:56:49,201 [INFO] [Memory] Leaked +10 MB. Total RSS: 72 MB (step 6)
2026-05-11 15:56:51,201 [INFO] [Memory] Leaked +10 MB. Total RSS: 82 MB (step 7)
2026-05-11 15:56:53,201 [INFO] [Memory] Leaked +10 MB. Total RSS: 92 MB (step 8)
2026-05-11 15:56:55,202 [INFO] [Memory] Leaked +10 MB. Total RSS: 102 MB (step 9)
2026-05-11 15:56:56,998 [CRITICAL] [MemoryGuard] Memory limit exceeded (102MB >= 100MB) / (Recommend Over 100MB)
2026-05-11 15:56:56,998 [CRITICAL] [MemoryGuard] Self-terminating process 7582 to prevent system instability.
>>> [SYSTEM] SELF-TERMINATED (Memory Limit Exceeded) <<<
```

**소요 시간**: 약 18 초 후 OOM 자가 종료

### 관찰 로그 (After — MEMORY_LIMIT=200)

```
2026-05-11 15:58:22,453 [INFO] [MemoryGuard] Limit set to 200 MB.
2026-05-11 15:58:22,453 [INFO] [Memory] Leaked +10 MB. Total RSS: 22 MB (step 1)
...
2026-05-11 15:58:39,556 [INFO] [Memory] Leaked +10 MB. Total RSS: 192 MB (step 18)
2026-05-11 15:58:41,557 [INFO] [Memory] Leaked +10 MB. Total RSS: 202 MB (step 19)
2026-05-11 15:58:41,556 [CRITICAL] [MemoryGuard] Memory limit exceeded (202MB >= 200MB) / (Recommend Over 200MB)
2026-05-11 15:58:41,557 [CRITICAL] [MemoryGuard] Self-terminating process 7780 to prevent system instability.
>>> [SYSTEM] SELF-TERMINATED (Memory Limit Exceeded) <<<
```

**소요 시간**: 약 38 초 후 OOM 자가 종료

---

## 근본 원인 분석

### 코드 수준 원인

```python
# run_oom() 내부
leak_pool = []          # ← 모듈 수명 내내 유지되는 컨테이너
while True:
    chunk = bytearray(10 * 1024 * 1024)   # 10 MB 실제 힙 할당
    leak_pool.append(chunk)               # ← 참조가 남아 GC 수거 불가
    ...
    time.sleep(2)
```

- `leak_pool` 리스트가 `bytearray` 객체에 대한 강한 참조를 유지하므로 Python GC가 수거하지 못한다.
- 할당은 2초마다 10 MB씩 단조 증가하며 `/proc/PID/status` `VmRSS`로 측정한 실제 RSS를 기준으로 종료 판단한다.

### 메모리 증가 패턴

```
step  1 →  22 MB  (기준 RSS + 초기 Python 런타임)
step  2 →  32 MB  (+10 MB)
step  N →  (12 + N×10) MB  (선형 증가)
step  9 → 102 MB  → MEMORY_LIMIT=100 초과 → 종료
step 19 → 202 MB  → MEMORY_LIMIT=200 초과 → 종료
```

---

## 영향

| 항목 | 내용 |
|---|---|
| 프로세스 수명 | MEMORY_LIMIT 값에 비례 (100 MB → 18 s, 200 MB → 38 s) |
| 시스템 영향 | 자가 종료이므로 시스템 전체 OOM killer 트리거 전에 중단됨 |
| 서비스 가용성 | 프로세스 자가 종료 → 서비스 중단 |

---

## 개선 방안

1. **메모리 풀 상한 제어**: `MEMORY_LIMIT`에 도달하기 전 `del leak_pool[0]` 또는 `gc.collect()`로 오래된 블록 해제
2. **모니터링 경보**: RSS가 임계치의 80%에 도달하면 외부 경보 발송 (현재 `[MemoryGuard]`는 로그만 출력)
3. **프로세스 재시작 정책**: systemd `Restart=on-failure` 또는 supervisor를 통한 자동 재기동
4. **메모리 상한 cgroup 설정**: `memory.limit_in_bytes`로 OS 수준에서 강제 상한 설정
