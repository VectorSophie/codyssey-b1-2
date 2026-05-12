# Bonus: 스케줄링 알고리즘 추론 리포트

**Labels**: `analysis`, `scheduling`, `bonus`  
**Component**: agent-app-leak 전체 시나리오

---

## 목적

`agent-app-leak`의 세 가지 장애 시나리오(OOM, CPU 과점유, Deadlock)에서 관찰된  
프로세스 동작 및 시스템 로그를 바탕으로, 컨테이너 환경의 Linux 스케줄러 알고리즘을 추론한다.

---

## 관찰 데이터 요약

### 1. OOM 시나리오

```
[SafetyGuard] Process priority lowered (nice=10).
MemoryWorker: 25 MB → 50 → 75 → 100 MB  (3초 간격, 정확한 주기)
exit code: 137 (SIGKILL)
```

### 2. CPU 과점유 시나리오

```
[SafetyGuard] Process priority lowered (nice=10).
CpuWorker: 5% → 11% → 14% → 17% → 18% → 26% → 35% → 37% → 44% → 49% → 52%
exit code: 143 (SIGTERM)  — 내부 임계치 ~50% 도달
```

### 3. Deadlock 시나리오

```
PID 8183: S  (Interruptible sleep)  — 스케줄러 프로세스
PID 8184: SN (sleep + nice=10)      — 워커 프로세스
CpuWorker 동일하게 실행 → 동일한 ~50% 임계치에서 SIGTERM
```

---

## 스케줄링 알고리즘 추론

### 결론: **Linux CFS (Completely Fair Scheduler, SCHED_NORMAL)**

세 시나리오 모두에서 관찰된 동작이 CFS의 특성과 정확히 일치한다.

---

### 근거 1: nice=10 — CFS vruntime 가중치

```
[SafetyGuard] Process priority lowered (nice=10).
```

CFS는 각 태스크의 `vruntime`(가상 실행 시간)을 기준으로 다음 실행 태스크를 결정한다.  
`nice` 값은 가중치(`weight`)로 변환된다:

| nice | weight | CPU 시간 비율 |
|---|---|---|
| 0 (기본) | 1024 | 높음 (더 자주 실행) |
| 10 | 110 | 낮음 (덜 자주 실행) |

`nice=10`이면 기본 프로세스 대비 약 9.3배 더 빠르게 `vruntime`이 누적되므로  
CPU 스케줄링에서 낮은 우선순위를 받는다.

**관찰과의 연결**: OOM 시나리오에서 `time.sleep(3)` 간격이 정확하게 유지되는 것은  
CFS가 sleep에서 깨어난 태스크의 `vruntime`을 `min_vruntime`으로 보정하기 때문이다  
(보상 메커니즘 — 오래 자고 있던 프로세스는 깨어날 때 다시 우선권을 부여받음).

---

### 근거 2: CpuWorker 단계 상승 — CFS 선점 타이밍

CPU 과점유 시나리오에서 CpuWorker는 단순 스핀 루프(수학 연산 반복)로 CPU를 점유하지만,  
컨테이너가 응답 상태를 유지하는 것은 CFS의 **선점형(preemptive)** 특성 때문이다.

```
CFS target latency ≈ 6 ms (기본값)
→ 모든 태스크가 6 ms 내에 최소 1번 실행 기회를 가짐
```

nice=10이므로 경쟁 태스크가 있을 경우 양보가 더 빨리 일어나야 하지만,  
컨테이너 내 단독 프로세스 환경에서는 사실상 전체 CPU를 독점 가능하다.  
이것이 CpuWorker가 빠르게 50%까지 상승하는 이유다.

---

### 근거 3: Deadlock 프로세스의 S/SN 상태 — futex / IPC 대기

```
PID 8183: S  (Interruptible sleep)  ← IPC 대기 중
PID 8184: SN (sleep + nice=10)      ← CpuWorker 실행 + 대기 혼합
```

`S` (Interruptible sleep) 상태는 다음 상황에서 발생한다:
- **futex(FUTEX_WAIT)**: mutex/semaphore 대기
- **pipe read/write**: IPC 파이프 대기
- **System V semaphore**: `semop()` 대기

스케줄러 프로세스(8183)가 `S` 상태로 고착된 것은 IPC를 통해 워커의 응답을 기다리고 있음을 의미한다.  
IPC를 통한 순환 대기가 발생하면 두 프로세스 모두 `S` 상태를 유지하며 진행 불가 상태에 빠진다.

Deadlock 프로세스가 `CPU=0%`가 아닌 이유: 워커(8184)는 CpuWorker 쓰레드를 동시에 실행하므로  
Deadlock 상태이면서도 CPU 사용량이 관찰된다.

---

### 근거 4: SIGKILL vs SIGTERM 선택 — CFS 스케줄링과 무관한 커널 결정

| 시나리오 | 종료 신호 | 이유 |
|---|---|---|
| OOM | SIGKILL (exit 137) | 메모리 부족 — 커널이 즉시 강제 종료 |
| CPU 과점유 | SIGTERM (exit 143) | CPU 임계치 — 바이너리 Watchdog이 `kill(pid, SIGTERM)` 호출 |
| Deadlock | SIGTERM (exit 143) | CPU 임계치 위반 (동일) |

SIGKILL은 CFS 스케줄러 큐에서 즉시 제거되며 signal handler도 실행되지 않는다.  
SIGTERM은 CFS를 통해 정상적으로 전달되며, signal handler가 실행 기회를 가진다.

---

## 스케줄러 관점 비교 요약

| 시나리오 | 프로세스 상태 | CFS 동작 |
|---|---|---|
| OOM (sleep 중) | `S` (Interruptible) | 타이머 만료 시 깨움; sleep 동안 런큐에서 제거 |
| CPU Burn | `R` (Running) | 타임슬라이스 소진 후 선점; nice=10으로 낮은 가중치 |
| Deadlock (IPC 대기) | `S` / `SN` | futex/IPC wait; 상대방 wake 전까지 런큐 미복귀 |
| Healthy 모드 (Cooldown) | `S` ↔ `R` 반복 | 부하/sleep 사이클; CFS가 공정하게 교대 |

---

## 추론 결론

관찰된 모든 동작 — `nice=10` 가중치 효과, 선점형 CPU 양보, IPC 기반 Interruptible sleep, SIGKILL/SIGTERM 동작 — 은  
**Linux CFS (Completely Fair Scheduler, SCHED_NORMAL)** 의 특성과 정확히 일치한다.

실시간 스케줄러(SCHED_FIFO, SCHED_RR)였다면:
- `nice` 값이 스케줄링에 영향을 주지 않음
- 타임슬라이스 없이 FIFO 또는 라운드로빈으로 실행
- CFS vruntime 보상 메커니즘이 존재하지 않음

따라서 해당 컨테이너 환경의 스케줄링 알고리즘은 **CFS (SCHED_NORMAL)** 로 결론짓는다.
