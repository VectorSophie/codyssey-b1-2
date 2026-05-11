# Issue #2: CPU 과점유 장애 분석

**Labels**: `bug`, `cpu`, `performance`  
**Severity**: High  
**Component**: agent-leak-app — `run_cpu()` 시나리오

---

## 요약

`MEMORY_LIMIT=512`(최대) + `MULTI_THREAD_ENABLE=false` 조건에서 실행되는 CPU 스파이크 시나리오.  
레벨 1부터 단계적으로 CPU 부하를 증가시키며 `CPU_MAX_OCCUPY` 임계치를 초과하면 Watchdog이 SIGTERM을 발송하고 프로세스를 종료한다.

---

## 재현 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04 LTS (Docker, `--privileged`) |
| Python | 3.12 |
| 활성 시나리오 | `MEMORY_LIMIT=512`, `MULTI_THREAD_ENABLE=false` |

### 환경변수

```bash
export MEMORY_LIMIT=512
export CPU_MAX_OCCUPY=20        # 임계치: 20 %
export MULTI_THREAD_ENABLE=false
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
2026-05-11 16:04:49,165 [INFO] [SafetyGuard] Process priority lowered (nice=10).
2026-05-11 16:04:49,165 [INFO] Agent listening at port 15034
2026-05-11 16:04:49,165 [INFO] === Agent Started. CPU Spike Mode. ===
2026-05-11 16:04:49,165 [INFO] [Watchdog] CPU cap set to 20%.
2026-05-11 16:04:49,165 [INFO] [CPU] Level 1 workload starting...
2026-05-11 16:04:50,367 [INFO] [CPU] Level 1 workload completed. Duration: 0.20s, CPU: 16.6%
2026-05-11 16:04:50,367 [INFO] [CPU] Level 2 workload starting...
2026-05-11 16:04:51,767 [INFO] [CPU] Level 2 workload completed. Duration: 0.40s, CPU: 28.6%
2026-05-11 16:04:51,767 [CRITICAL] [Watchdog] CPU overoccupy detected: 28.6% > 20%
2026-05-11 16:04:51,767 [CRITICAL] [Watchdog] INITIATING EMERGENCY ABORT (SIGTERM) for PID 7812
>>> [SYSTEM] WATCHDOG: INITIATING EMERGENCY ABORT (SIGTERM) <<<
```

**소요 시간**: 부트 완료 후 약 2.6 초 만에 Watchdog 발동 (Level 2에서 임계치 초과)

---

## 근본 원인 분석

### 코드 수준 원인

```python
def cpu_burn(seconds):
    end = time.time() + seconds
    while time.time() < end:
        math.sqrt(random.random())   # 순수 CPU 연산 반복

def run_cpu():
    os.nice(10)       # 낮은 스케줄링 우선순위
    level = 1
    while True:
        burn_time = 0.2 * level   # level 1 = 0.2s, level 10 = 2.0s
        t_start = time.time()
        cpu_burn(burn_time)       # 실제 CPU 점유
        t_burn_end = time.time()
        time.sleep(1)             # 유휴 시간
        t_end = time.time()

        cpu_pct = (t_burn_end - t_start) / (t_end - t_start) * 100
        # cpu_pct = burn_time / cycle_time * 100
```

### CPU 점유율 단계별 계산

| Level | burn_time | cycle_time | CPU % | 판정 (임계치=20%) |
|---|---|---|---|---|
| 1 | 0.20 s | 1.20 s | 16.6 % | OK |
| 2 | 0.40 s | 1.40 s | 28.6 % | **EXCEEDED** |
| 3 | 0.60 s | 1.60 s | 37.5 % | — |
| 10 | 2.00 s | 3.00 s | 66.7 % | — |

- Level 1은 `16.6%`로 임계치(20%) 이내이나, Level 2에서 `28.6%`로 초과.
- `os.nice(10)`으로 프로세스 우선순위가 낮아져 있음에도, burn 구간 동안 단일 코어를 독점하는 스핀 루프 특성상 스케줄러가 양보를 강제하기 어렵다.

### 실제 CPU 소비와 측정 방식

CPU%는 `/proc/PID/stat`의 jiffie 기반 측정 대신 **burn_time / cycle_time 비율**로 계산된다.  
이 방식은 컨테이너 환경에서도 일관성이 보장되며 샘플링 오차가 없다.

---

## 영향

| 항목 | 내용 |
|---|---|
| 시스템 CPU 부하 | 단일 코어에서 burn 구간 동안 100% 점유 가능 |
| 다른 프로세스 영향 | `nice=10`으로 일부 완화되나, 저부하 시스템에서는 선점 발생 |
| 서비스 가용성 | Watchdog 발동 시 즉시 프로세스 종료 → 서비스 중단 |
| 임계치 도달 시간 | `CPU_MAX_OCCUPY=20` 기준 약 2.6 초 내 종료 |

---

## 개선 방안

1. **CPU 쓰로틀링**: `time.sleep()` 비율을 동적으로 조절하여 CPU 점유율을 목표 수준 이하로 유지
2. **cgroup CPU 쿼터**: `cpu.cfs_quota_us` / `cpu.cfs_period_us`로 OS 수준에서 CPU 상한 강제
3. **경보 임계치 이중화**: Watchdog 발동(종료) 이전에 경보 임계치(예: 70%)를 별도 설정하여 사전 알림 발송
4. **단계적 부하 조절**: 임계치 초과 감지 시 즉시 종료 대신 burn_time 축소 후 재측정하는 단계적 조절 로직 도입
