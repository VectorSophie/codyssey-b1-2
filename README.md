# 시스템 장애 분석 미션 보고서

## 1. 실행 환경

- **OS**: Ubuntu 24.04 LTS (Docker Container on Windows 11 Host)
- **Docker**: version 29.4.0
- **Container**: `docker run --privileged --cap-add NET_ADMIN --cap-add NET_RAW -p 20023:20022 -p 15035:15034 ubuntu:24.04`
- **분석 대상**: `agent-app-leak` (Memory Leak / CPU Spike / Deadlock 시뮬레이터)

## 2. 환경변수 요구사항

| 환경변수 | 값 | 설명 |
|---|---|---|
| `AGENT_HOME` | `/home/agent-admin/agent-app` | 앱 홈 디렉토리 |
| `AGENT_PORT` | `15034` | 고정 포트 |
| `AGENT_UPLOAD_DIR` | `/home/agent-admin/agent-app/upload_files` | 업로드 디렉토리 (절대경로 일치 필수) |
| `AGENT_KEY_PATH` | `/home/agent-admin/agent-app/api_keys` | API 키 **디렉토리** 경로 (`secret.key` 파일 포함) |
| `AGENT_LOG_DIR` | `/var/log/agent-app` | 로그 디렉토리 |
| `MEMORY_LIMIT` | `50~512` (MB) | 메모리 임계치 |
| `CPU_MAX_OCCUPY` | `10~100` (%) | CPU 과점유 임계치 |
| `MULTI_THREAD_ENABLE` | `true/false` | 멀티스레드 활성화 |

> **주의**: `AGENT_UPLOAD_DIR`과 `AGENT_KEY_PATH`는 바이너리 내부 기대값과 절대경로가 정확히 일치해야 합니다.  
> `AGENT_KEY_PATH`는 키 파일 경로가 아닌 **디렉토리** 경로이며, 해당 디렉토리 안에 `secret.key` 파일이 있어야 합니다.

## 3. 체크리스트

- [x] OOM/Memory Leak 장애 분석 및 이슈 리포트
- [x] CPU 과점유 장애 분석 및 이슈 리포트
- [x] Deadlock 장애 분석 및 이슈 리포트
- [x] 보너스: 스케줄링 알고리즘 추론 리포트

## 4. 파일 구조

```
codyssey-b1-2/
├── agent-app-leak          # 분석 대상 바이너리 (Linux ELF x86_64, 7.6MB)
├── bin/
│   └── monitor.sh          # 프로세스별 관제 스크립트
├── issues/
│   ├── 01-oom-memory-leak.md        # Issue #1: OOM 장애 분석
│   ├── 02-cpu-overoccupy.md         # Issue #2: CPU 과점유 분석
│   ├── 03-deadlock.md               # Issue #3: Deadlock 분석
│   └── 04-scheduling-analysis.md   # Bonus: 스케줄링 알고리즘 추론
└── README.md
```

## 5. 부트 시퀀스 (6단계)

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
```

## 6. 시나리오 선택 로직

바이너리는 환경변수 조합에 따라 시나리오를 자동 선택합니다:

| 조건 | 시나리오 |
|---|---|
| `MEMORY_LIMIT < 256` | **OOM / Memory Leak** — MemoryWorker가 25 MB/3s씩 누적 할당 |
| `MEMORY_LIMIT >= 256`, `CPU_MAX_OCCUPY=100`, `MULTI_THREAD_ENABLE=false` | **CPU 과점유** — CpuWorker가 단계적으로 부하 상승 |
| `MEMORY_LIMIT >= 256`, `CPU_MAX_OCCUPY=100`, `MULTI_THREAD_ENABLE=true` | **Deadlock + CPU** — "POTENTIAL DEADLOCK" 경고 + CpuWorker 동시 실행 |
| `CPU_MAX_OCCUPY <= 20` | **Healthy System Monitoring** — 제어된 부하/냉각 반복 |

## 7. 실행 방법

```bash
# 공통 환경변수 (agent-admin 계정에서 실행)
export AGENT_HOME=/home/agent-admin/agent-app
export AGENT_PORT=15034
export AGENT_UPLOAD_DIR=/home/agent-admin/agent-app/upload_files
export AGENT_KEY_PATH=/home/agent-admin/agent-app/api_keys
export AGENT_LOG_DIR=/var/log/agent-app

# OOM 시나리오 (100MB 제한 → ~12초 내 SIGKILL)
export MEMORY_LIMIT=100; export CPU_MAX_OCCUPY=100; export MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-app-leak

# CPU 과점유 시나리오 (CPU_MAX_OCCUPY=100 → ~90초 내 SIGTERM)
export MEMORY_LIMIT=512; export CPU_MAX_OCCUPY=100; export MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-app-leak

# Deadlock 시나리오 (POTENTIAL DEADLOCK 경고 + CPU 과점유)
export MEMORY_LIMIT=512; export CPU_MAX_OCCUPY=100; export MULTI_THREAD_ENABLE=true
$AGENT_HOME/agent-app-leak
```
