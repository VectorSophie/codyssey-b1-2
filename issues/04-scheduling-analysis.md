# Bonus: 스케줄링 알고리즘 추론 리포트

**Labels**: `analysis`, `scheduling`, `bonus`  
**Component**: agent-leak-app 전체 시나리오

---

## 목적

`agent-leak-app`의 세 가지 장애 시나리오(OOM, CPU 과점유, Deadlock)에서 관찰된 프로세스/스레드 동작을 바탕으로, 컨테이너 환경에서 동작 중인 Linux 스케줄러의 알고리즘과 동작 방식을 추론한다.

---

## 관찰 데이터 요약

### 1. OOM 시나리오 (Memory Leak)

```
nice=10  → 프로세스 스케줄링 우선순위 낮춤
RSS 증가: 22 MB → 12 MB + (N × 10 MB) 선형 패턴
2초 간격 할당 → 스케줄러 간섭 없이 일정하게 실행
```

### 2. CPU 과점유 시나리오

```
nice=10  → 우선순위 낮춤
Level 1: burn=0.20s, cycle=1.20s, CPU=16.6%
Level 2: burn=0.40s, cycle=1.40s, CPU=28.6%  → Watchdog 종료
```

burn 구간 동안 수학 연산(`math.sqrt(random.random())`) 스핀 루프:  
CPU를 양보하지 않고 단일 코어를 독점하는 패턴 관찰

### 3. Deadlock 시나리오

```
스레드 3개: 메인(Ss) + Thread-A(Sl) + Thread-B(Sl)
모든 스레드 %CPU = 0.0%
ps STAT 코드: Sl (Interruptible sleep + multi-threaded)
```

---

## 스케줄링 알고리즘 추론

### 결론: **Linux CFS (Completely Fair Scheduler)**

관찰된 동작 모두 Linux 기본 스케줄러인 CFS(SCHED_NORMAL)와 일치한다.

### 근거 1: nice 값의 영향 — CFS vruntime 가중치

```bash
os.nice(10)   # 앱이 스스로 우선순위 낮춤
```

CFS는 프로세스의 `vruntime`(가상 실행 시간)을 기준으로 다음 실행 프로세스를 선택한다.  
`nice=10`은 `weight = 110`(기본 `nice=0`의 `weight=1024` 대비 약 9.3배 낮음)으로 매핑되어,  
동일 실 시간 내에 훨씬 더 많은 `vruntime`이 누적된다.

```
nice=0  → weight=1024  → vruntime 증가 느림 (더 자주 실행)
nice=10 → weight=  110 → vruntime 증가 빠름 (덜 자주 실행)
```

관찰: OOM 시나리오에서 2초 sleep 구간이 정확하게 지켜지는 것은 CFS가 sleep 복귀 후 `vruntime`을 현재 최솟값으로 보정하기 때문이다.

### 근거 2: CPU 스핀 루프의 선점 — CFS 타임슬라이스

CPU 과점유 시나리오에서 `cpu_burn()` 함수는 `time.time()` 루프만 돌며 자발적으로 CPU를 양보하지 않는다. 그럼에도 컨테이너가 응답 상태를 유지하는 것은 CFS의 **선점형(preemptive)** 특성 때문이다.

```
CFS target latency = 6 ms (기본값)
단일 태스크일 경우 타임슬라이스 = min_granularity(= 0.75 ms) 이상
```

burn 구간 동안 다른 프로세스들은 CFS에 의해 교대로 실행 기회를 얻는다.  
`nice=10`이지만 `runqueue`에 경쟁 프로세스가 없는 컨테이너 환경에서는 사실상 독점에 가까운 CPU 점유가 발생할 수 있다.

### 근거 3: Deadlock 스레드의 Sl 상태 — futex 기반 대기

```
   7837 Sl    0.0  0.1    ← Thread-A
   7838 Sl    0.0  0.1    ← Thread-B
```

`Sl` = `S`(Interruptible sleep) + `l`(multi-threaded)

Python `threading.Lock()`은 내부적으로 Linux **futex**(Fast Userspace muTEX)를 사용한다.

```
lock_b.acquire() 호출 시:
  1. CAS(Compare-And-Swap)로 userspace에서 락 시도
  2. 실패(이미 보유됨) → futex(FUTEX_WAIT) 시스템 콜
  3. 커널이 스레드를 wait queue에 넣고 Interruptible sleep 상태로 전환
  4. 소유자가 lock_b.release() 시 futex(FUTEX_WAKE)로 깨움
```

Deadlock 상태에서는 `FUTEX_WAKE`가 영구적으로 발생하지 않으므로 두 스레드가 `FUTEX_WAIT` 상태에 영구 고착된다.  
이것이 `%CPU=0.0%`이면서 스레드가 살아있는 이유이다.

---

## 스케줄러 관점 비교 요약

| 시나리오 | 스케줄링 클래스 | 상태 | 특징 |
|---|---|---|---|
| OOM (sleep 중) | SCHED_NORMAL (CFS) | S (Interruptible sleep) | `time.sleep(2)` → CFS wait queue, 타이머 만료 시 깨움 |
| CPU Burn | SCHED_NORMAL (CFS) | R (Running) | 스핀 루프 → 타임슬라이스 소진 후 CFS 선점 |
| Deadlock (대기) | SCHED_NORMAL (CFS) | Sl (futex wait) | `futex(FUTEX_WAIT)` → 커널 wait queue에 고착 |
| 메인 스레드 | SCHED_NORMAL (CFS) | Ss | `time.sleep(5)` 루프, 타이머로 주기적 깨움 |

---

## 추론 결론

세 시나리오 모두에서 관찰된 동작(nice 가중치, 선점형 CPU, futex 기반 대기)은 모두 **Linux CFS (Completely Fair Scheduler, SCHED_NORMAL)** 의 동작 특성과 정확히 일치한다.  
실시간 스케줄러(SCHED_FIFO, SCHED_RR)였다면 `nice=10`이 무효하고, futex 대기 우선순위가 다르게 동작한다.  
따라서 해당 컨테이너 환경의 스케줄링 알고리즘은 **CFS** 로 결론짓는다.
