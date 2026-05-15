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

### 7.1 컨테이너 진입

```powershell
docker exec -it agent-leak-lab bash
```

### 7.2 환경변수 세팅 (공통, 한 번만)

```bash
export AGENT_HOME=/home/agent-admin/agent-app
export AGENT_PORT=15034
export AGENT_UPLOAD_DIR=/home/agent-admin/agent-app/upload_files
export AGENT_KEY_PATH=/home/agent-admin/agent-app/api_keys
export AGENT_LOG_DIR=/var/log/agent-app
```

### 7.3 시나리오별 실행

```bash
# OOM — 메모리 누수 (약 12초 내 SIGKILL, exit 137)
export MEMORY_LIMIT=100; export CPU_MAX_OCCUPY=100; export MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-app-leak

# CPU 과점유 (약 30초 내 SIGTERM, exit 143)
export MEMORY_LIMIT=512; export CPU_MAX_OCCUPY=100; export MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-app-leak

# Deadlock + CPU (약 30초 내 SIGTERM)
export MEMORY_LIMIT=512; export CPU_MAX_OCCUPY=100; export MULTI_THREAD_ENABLE=true
$AGENT_HOME/agent-app-leak

# 정상 모드 (Cooldown, 종료 없음)
export MEMORY_LIMIT=512; export CPU_MAX_OCCUPY=20; export MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-app-leak
```

### 7.4 종료 코드 확인

```bash
$AGENT_HOME/agent-app-leak
echo "exit code: $?"
# OOM      → 137 (128 + 9,  SIGKILL)
# CPU/Dead → 143 (128 + 15, SIGTERM)
```

### 7.5 실행 중 프로세스 관찰 (별도 터미널)

```bash
# 같은 컨테이너에 두 번째 터미널로 진입
docker exec -it agent-leak-lab bash

# 프로세스 상태 실시간 관찰
watch -n 1 'ps aux | grep agent-app-leak | grep -v grep'

# 스레드 포함 상세 보기 (Deadlock 확인용)
watch -n 1 'ps -eLf | grep agent-app-leak | grep -v grep'

# CPU/메모리 실시간
top -p $(pgrep -f agent-app-leak | head -1)
```

### 7.6 monitor.sh 실행

```bash
AGENT_HOME=/home/agent-admin/agent-app \
AGENT_PORT=15034 \
AGENT_LOG_DIR=/var/log/agent-app \
/home/agent-admin/agent-app/bin/monitor.sh
```

### 7.7 로그 확인

```bash
tail -f /var/log/agent-app/monitor.log      # 실시간 스트림
tail -10 /var/log/agent-app/monitor.log     # 최근 10줄
grep WARNING /var/log/agent-app/monitor.log # 경고만 필터
wc -l /var/log/agent-app/monitor.log        # 전체 줄 수
```
