# 시스템 장애 분석 미션 보고서

## 1. 실행 환경

- **OS**: Ubuntu 24.04 LTS (Docker Container on Windows 11 Host)
- **Docker**: version 29.4.0
- **Container**: `docker run --privileged --cap-add NET_ADMIN --cap-add NET_RAW -p 20023:20022 -p 15035:15034 ubuntu:24.04`
- **분석 대상**: `agent-leak-app` (Memory Leak / CPU Spike / Deadlock 시뮬레이터)

## 2. 환경변수 요구사항

| 환경변수 | 값 | 설명 |
|---|---|---|
| `AGENT_HOME` | `/home/agent-admin/agent-app` | 앱 홈 디렉토리 |
| `AGENT_PORT` | `15034` | 고정 포트 |
| `AGENT_UPLOAD_DIR` | `$AGENT_HOME/upload_files` | 업로드 디렉토리 |
| `AGENT_KEY_PATH` | `$AGENT_HOME/api_keys/t_secret.key` | API 키 파일 경로 |
| `AGENT_LOG_DIR` | `/var/log/agent-app` | 로그 디렉토리 |
| `MEMORY_LIMIT` | `50~512` (MB) | 메모리 임계치 |
| `CPU_MAX_OCCUPY` | `10~100` (%) | CPU 과점유 임계치 |
| `MULTI_THREAD_ENABLE` | `true/false` | 멀티스레드 활성화 |

## 3. 체크리스트

- [x] OOM/Memory Leak 장애 분석 및 이슈 리포트
- [x] CPU 과점유 장애 분석 및 이슈 리포트
- [x] Deadlock 장애 분석 및 이슈 리포트
- [x] 보너스: 스케줄링 알고리즘 추론 리포트

## 4. 파일 구조

```
codyssey-b1-2/
├── agent-leak-app          # 제공 시뮬레이터 바이너리 (Linux ELF x86_64)
├── bin/
│   └── monitor.sh          # 프로세스별 관제 스크립트
├── issues/
│   ├── 01-oom-memory-leak.md        # Issue #1: OOM 장애 분석
│   ├── 02-cpu-overoccupy.md         # Issue #2: CPU 과점유 분석
│   ├── 03-deadlock.md               # Issue #3: Deadlock 분석
│   └── 04-scheduling-analysis.md   # Bonus: 스케줄링 알고리즘 추론
└── README.md
```

## 5. 실행 방법

```bash
# 기본 실행 (agent-admin 계정으로)
export AGENT_HOME=/home/agent-admin/agent-app
export AGENT_PORT=15034
export AGENT_UPLOAD_DIR=$AGENT_HOME/upload_files
export AGENT_KEY_PATH=$AGENT_HOME/api_keys/t_secret.key
export AGENT_LOG_DIR=/var/log/agent-app

# OOM 시나리오 (50MB 제한)
export MEMORY_LIMIT=50
export CPU_MAX_OCCUPY=100
export MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-leak-app

# CPU 과점유 시나리오
export MEMORY_LIMIT=512
export CPU_MAX_OCCUPY=10
export MULTI_THREAD_ENABLE=false
$AGENT_HOME/agent-leak-app

# Deadlock 시나리오
export MEMORY_LIMIT=512
export CPU_MAX_OCCUPY=100
export MULTI_THREAD_ENABLE=true
$AGENT_HOME/agent-leak-app
```
