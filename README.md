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
└── README.md
```

> 장애 이슈 보고서는 GitHub Issues로 등록됨 (#1 OOM, #2 CPU, #3 Deadlock, #4 Scheduling Analysis)

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
| `MEMORY_LIMIT >= 256`, `CPU_MAX_OCCUPY=100`, `MULTI_THREAD_ENABLE=false` | **CPU 과점유** — CpuWorker가 단계적으로 부하 상승, SIGTERM (exit 143) |
| `MEMORY_LIMIT >= 256`, `CPU_MAX_OCCUPY <= 20`, `MULTI_THREAD_ENABLE=true` | **Deadlock** — "POTENTIAL DEADLOCK" 경고, 스케줄러 IPC 대기 고착 |
| `MEMORY_LIMIT >= 256`, `CPU_MAX_OCCUPY <= 20`, `MULTI_THREAD_ENABLE=false` | **Healthy System Monitoring** — 제어된 부하/냉각 반복 |

## 7. 실행 방법

### 7.1 컨테이너 진입 및 계정 전환

```powershell
# Windows에서 컨테이너 진입
docker exec -it agent-leak-lab bash
```

컨테이너 진입 후 기본 사용자는 `root`다. `agent-app-leak`은 root 실행을 금지하며, root로 실행하면 1단계에서 즉시 전체 FAIL 처리된다.

```
[1/6] Checking User Account    [FAIL]
   >>> Error: Running as 'root' is forbidden.
```

반드시 `agent-admin`으로 전환한 뒤 실행한다:

```bash
su - agent-admin
```

> **주의**: `su - agent-admin` 전환 후에는 `sudo -u agent-admin bash -c "..."` 형태를 사용하면 안 된다.
> `sudo`는 실행 시 새로운 환경을 만들기 때문에 이전에 export한 환경변수가 모두 초기화된다.
> 계정 전환 후에는 export와 실행을 현재 셸에서 직접 실행한다.

### 7.2 환경변수 세팅 (계정 전환 후, 한 번만)

```bash
export AGENT_HOME=/home/agent-admin/agent-app
export AGENT_PORT=15034
export AGENT_UPLOAD_DIR=/home/agent-admin/agent-app/upload_files
export AGENT_KEY_PATH=/home/agent-admin/agent-app/api_keys
export AGENT_LOG_DIR=/var/log/agent-app
```

### 7.3 시나리오별 실행

공통 환경변수(7.2)를 export한 상태에서 아래 명령을 순서대로 실행한다.

```bash
# OOM — 메모리 누수 (약 12초 내 SIGKILL, exit 137)
export MEMORY_LIMIT=100 CPU_MAX_OCCUPY=100 MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-app-leak
echo "exit: $?"

# CPU 과점유 (약 34초 내 SIGTERM, exit 143)
export MEMORY_LIMIT=512 CPU_MAX_OCCUPY=100 MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-app-leak
echo "exit: $?"

# Deadlock (POTENTIAL DEADLOCK 경고 + 스케줄러 IPC 대기 고착, Ctrl+C로 수동 종료)
export MEMORY_LIMIT=512 CPU_MAX_OCCUPY=20 MULTI_THREAD_ENABLE=true
$AGENT_HOME/agent-app-leak

# 정상 모드 (Cooldown 반복, 종료 없음)
export MEMORY_LIMIT=512 CPU_MAX_OCCUPY=20 MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-app-leak
```

### 7.4 실행 중 프로세스 관찰 (별도 터미널)

```bash
# Windows에서 두 번째 터미널로 컨테이너 진입
docker exec -it agent-leak-lab bash

# 프로세스 상태 실시간 관찰
watch -n 1 'ps aux | grep agent-app-leak | grep -v grep'

# 스레드 포함 상세 보기 (Deadlock 확인용)
watch -n 1 'ps -eLf | grep agent-app-leak | grep -v grep'

# CPU/메모리 실시간
top -p $(pgrep -f agent-app-leak | head -1)
```

### 7.5 monitor.sh 단발 실행 (agent-admin 셸에서)

```bash
/home/agent-admin/agent-app/bin/monitor.sh
```

### 7.6 crontab으로 monitor.sh 자동화 (매 1분마다)

`agent-admin` 셸에서 아래 명령으로 crontab을 편집한다.

```bash
crontab -e
```

편집기가 열리면 아래 줄을 추가하고 저장한다 (vi 기준: `i` 입력 → 내용 붙여넣기 → `Esc` → `:wq`):

```
* * * * * AGENT_PORT=15034 AGENT_LOG_DIR=/var/log/agent-app /home/agent-admin/agent-app/bin/monitor.sh >> /var/log/agent-app/monitor-cron.log 2>&1
```

> cron 환경은 셸에서 export한 환경변수를 상속하지 않는다. 위처럼 `KEY=VALUE command` 형태로 crontab 줄 앞에 직접 지정해야 한다.

설정 확인:

```bash
crontab -l           # 등록된 crontab 목록 출력
```

### 7.7 자동화된 monitor.sh 로그 확인

```bash
# cron이 직접 기록하는 에러/stdout (monitor.sh가 프로세스를 찾지 못했을 때 등)
tail -f /var/log/agent-app/monitor-cron.log

# monitor.sh 내부에서 LOG_FILE로 기록하는 한 줄 요약 (정상 수집 시)
tail -f /var/log/agent-app/monitor.log

# 최근 10줄
tail -10 /var/log/agent-app/monitor.log

# 경고만 필터
grep WARNING /var/log/agent-app/monitor.log

# 전체 줄 수 (매분 1줄 누적)
wc -l /var/log/agent-app/monitor.log
```
