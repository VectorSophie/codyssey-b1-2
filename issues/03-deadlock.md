# Issue #3: Deadlock 장애 분석

**Labels**: `bug`, `deadlock`, `threading`  
**Severity**: Critical  
**Component**: agent-leak-app — `run_deadlock()` 시나리오

---

## 요약

`MULTI_THREAD_ENABLE=true` 조건에서 두 개의 워커 스레드가 **서로의 Lock을 순환 대기**하여 영구 블로킹(Deadlock)에 빠진다.  
프로세스 자체는 살아있으나 워커 스레드는 진행 불가 상태가 된다.

---

## 재현 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04 LTS (Docker, `--privileged`) |
| Python | 3.12 |
| 활성 시나리오 | `MULTI_THREAD_ENABLE=true` |

### 환경변수

```bash
export MEMORY_LIMIT=512
export CPU_MAX_OCCUPY=100
export MULTI_THREAD_ENABLE=true
```

---

## 재현 절차

```bash
python3 $AGENT_HOME/agent_leak_app.py
```

---

## 관찰 로그

```
>>> Starting Agent Boot Sequence...
[1/5] Checking User Account               [OK]
[2/5] Verifying Environment Variables     [OK]
[3/5] Checking Required Files             [OK]
[4/5] Checking Port Availability          [OK]
[5/5] Verifying Log Permission            [OK]
All Boot Checks Passed!
Agent READY
2026-05-11 16:05:04,170 [INFO] [SafetyGuard] Process priority lowered (nice=10).
2026-05-11 16:05:04,170 [INFO] Agent listening at port 15034
2026-05-11 16:05:04,170 [INFO] === Agent Started. Multi-Thread Mode. ===
2026-05-11 16:05:04,170 [INFO] [ThreadMgr] Spawning worker threads...
2026-05-11 16:05:04,172 [INFO] [Thread-A] Task Started. Acquiring Resource-A...
2026-05-11 16:05:04,172 [INFO] [Thread-A] Acquired Resource-A. Calculating... (50%)
2026-05-11 16:05:04,273 [INFO] [Thread-B] Task Started. Acquiring Resource-B...
2026-05-11 16:05:04,273 [INFO] [Thread-B] Acquired Resource-B. Calculating... (50%)
2026-05-11 16:05:04,273 [INFO] [ThreadMgr] All threads running. Monitoring...
2026-05-11 16:05:04,672 [INFO] [Thread-A] WAITING for Resource-B... [BLOCKED]
2026-05-11 16:05:04,773 [INFO] [Thread-B] WAITING for Resource-A... [BLOCKED]
2026-05-11 16:05:09,274 [INFO] [ThreadMgr] Status check — Thread-A alive:True Thread-B alive:True
2026-05-11 16:05:14,924 [INFO] [ThreadMgr] Status check — Thread-A alive:True Thread-B alive:True
2026-05-11 16:05:19,924 [INFO] [ThreadMgr] Status check — Thread-A alive:True Thread-B alive:True
```

**이후 로그 없음**: `ThreadMgr Status check` 메시지만 5초 간격으로 반복되며 워커 진행 없음

### monitor.sh 스레드 상태

```
====== SYSTEM MONITOR RESULT ======
Time: 2026-05-11 16:05:57

[HEALTH CHECK]
Process 'agent_leak_app'... [OK] (PID: 7835)
Port 15034... [WARN] (Not listening — process may be initializing or crashed)

[THREAD INFO]
Thread count   : 3
   7835    7835 Sl    0.0  0.1 python3    ← 메인 스레드 (ThreadMgr)
   7835    7837 Sl    0.0  0.1 python3    ← Thread-A (lock_b 대기 중)
   7835    7838 Sl    0.0  0.1 python3    ← Thread-B (lock_a 대기 중)
```

- 세 스레드 모두 `Sl` 상태 (Interruptible sleep + multi-threaded)
- `%CPU = 0.0` → 어떤 스레드도 실행되지 않음 (영구 블로킹)

---

## 근본 원인 분석

### 락 획득 순서 (Deadlock 발생 구조)

```
t=0.000  Thread-A starts  → acquires lock_a ✓
t=0.100  Thread-B starts  → acquires lock_b ✓
t=0.500  Thread-A: sleep(0.5) 완료 → lock_b 요청  ← BLOCKED (Thread-B 보유)
t=0.600  Thread-B: sleep(0.5) 완료 → lock_a 요청  ← BLOCKED (Thread-A 보유)
         ↓
         Circular Wait 성립 → DEADLOCK
```

```python
lock_a = threading.Lock()
lock_b = threading.Lock()

def thread_worker_a():
    with lock_a:           # lock_a 획득
        time.sleep(0.5)
        with lock_b:       # lock_b 대기 (Thread-B 보유) → BLOCKED
            pass

def thread_worker_b():
    with lock_b:           # lock_b 획득
        time.sleep(0.5)
        with lock_a:       # lock_a 대기 (Thread-A 보유) → BLOCKED
            pass
```

### Deadlock 4 조건 충족 여부

| 조건 | 설명 | 충족 |
|---|---|---|
| Mutual Exclusion | `threading.Lock()`은 단일 스레드만 보유 가능 | ✅ |
| Hold and Wait | 각 스레드가 Lock을 보유한 채 다른 Lock을 요청 | ✅ |
| No Preemption | Python Lock은 강제 해제 불가 | ✅ |
| Circular Wait | A→B→A 순환 대기 형성 | ✅ |

모든 Deadlock 필요 조건을 충족하므로 데드락 발생은 필연적이다.

---

## 영향

| 항목 | 내용 |
|---|---|
| 워커 스레드 상태 | Thread-A, Thread-B 영구 블로킹 → 작업 진행 불가 |
| 프로세스 생존 여부 | 메인 스레드(ThreadMgr)는 살아있어 프로세스는 실행 중으로 보임 |
| CPU 점유 | 0% (모든 스레드 sleep 상태) |
| 탐지 난이도 | 프로세스 헬스 체크(`pgrep`, `ps`)만으로는 정상처럼 보임 |
| 서비스 가용성 | 실제 작업 처리 불가 상태이나 프로세스 자체는 종료되지 않음 |

---

## 개선 방안

1. **Lock 획득 순서 통일**: 모든 스레드가 항상 `lock_a → lock_b` 순서로 획득하도록 강제

   ```python
   # 수정: Thread-B도 lock_a 먼저 획득
   def thread_worker_b():
       with lock_a:     # lock_a 먼저 (Thread-A와 동일 순서)
           with lock_b:
               pass
   ```

2. **타임아웃 락 사용**: `Lock.acquire(timeout=5.0)` → 획득 실패 시 예외 처리

   ```python
   if not lock_b.acquire(timeout=5.0):
       log('ERROR', '[Thread-A] Deadlock detected! Releasing lock_a.')
       raise RuntimeError("Deadlock avoided")
   ```

3. **Deadlock 탐지 모니터**: 스레드 대기 시간을 측정하여 일정 시간(예: 10초) 이상 블로킹된 스레드가 있으면 경보 발송
4. **스레드 상태 모니터링**: `monitor.sh`의 `[THREAD INFO]` 섹션에서 스레드 수와 `Sl` 상태 지속 여부를 체크하여 Deadlock 자동 탐지
