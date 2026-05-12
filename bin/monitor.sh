#!/bin/bash
# monitor.sh - Per-process monitoring for agent-app-leak
# Tracks process-level CPU/MEM and system-level DISK/FIREWALL
# Log format: [YYYY-MM-DD HH:MM:SS] PROCESS:agent-app-leak CPU:X% MEM:XMB(X%) DISK:XG FIREWALL:active|inactive

APP_NAME="${AGENT_APP_NAME:-agent-app-leak}"
APP_PORT="${AGENT_PORT:-15034}"
LOG_DIR="${AGENT_LOG_DIR:-/var/log/agent-app}"
LOG_FILE="${LOG_DIR}/monitor.log"
MAX_LOG_SIZE=$((10 * 1024 * 1024))
MAX_LOG_FILES=10
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

# --- Log rotation ---
rotate_log() {
    [ -f "$LOG_FILE" ] || return
    local size
    size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    [ "$size" -le "$MAX_LOG_SIZE" ] && return
    [ -f "${LOG_FILE}.${MAX_LOG_FILES}" ] && rm -f "${LOG_FILE}.${MAX_LOG_FILES}"
    for i in $(seq $((MAX_LOG_FILES - 1)) -1 1); do
        [ -f "${LOG_FILE}.${i}" ] && mv "${LOG_FILE}.${i}" "${LOG_FILE}.$((i + 1))"
    done
    mv "$LOG_FILE" "${LOG_FILE}.1"
}

echo "====== SYSTEM MONITOR RESULT ======"
echo "Time: ${TIMESTAMP}"
echo ""

# ---- [HEALTH CHECK] ----
echo "[HEALTH CHECK]"
PID=$(pgrep -f "$APP_NAME" | head -1)
if [ -z "$PID" ]; then
    echo "Process '${APP_NAME}'... [FAIL] (Not running)"
    echo ""
    echo "[INFO] Process not found — skipping resource collection."
    echo "===================================="
    exit 1
fi
echo "Process '${APP_NAME}'... [OK] (PID: ${PID})"

if ss -tulnp 2>/dev/null | grep -qE ":${APP_PORT}[[:space:]]|:${APP_PORT}$"; then
    echo "Port ${APP_PORT}... [OK]"
else
    echo "Port ${APP_PORT}... [WARN] (Not listening — process may be initializing or crashed)"
fi
echo ""

# ---- [PROCESS RESOURCE] ----
echo "[PROCESS RESOURCE MONITORING]"

# Per-process CPU and MEM via ps
PROC_CPU=$(ps -p "$PID" -o %cpu= 2>/dev/null | tr -d ' ')
PROC_MEM_MB=$(ps -p "$PID" -o rss= 2>/dev/null | awk '{printf "%.0f", $1/1024}')
PROC_MEM_PCT=$(ps -p "$PID" -o %mem= 2>/dev/null | tr -d ' ')

# System-wide disk (root partition, available GB)
DISK_AVAIL=$(df / | awk 'NR==2 {printf "%.0f", $4/1024/1024}')
DISK_USED_PCT=$(df / | awk 'NR==2 {gsub(/%/,""); print $5}')

# Firewall status
FIREWALL_STATUS="inactive"
if command -v ufw &>/dev/null; then
    ufw status 2>/dev/null | grep -qi "active" && FIREWALL_STATUS="active"
fi

echo "CPU (process)  : ${PROC_CPU}%"
echo "MEM (process)  : ${PROC_MEM_MB}MB (${PROC_MEM_PCT}%)"
echo "DISK (avail)   : ${DISK_AVAIL}G  (used: ${DISK_USED_PCT}%)"
echo "Firewall       : ${FIREWALL_STATUS}"
echo ""

# ---- Thread state (for deadlock detection) ----
THREAD_COUNT=$(ps -p "$PID" -L --no-headers 2>/dev/null | wc -l)
echo "[THREAD INFO]"
echo "Thread count   : ${THREAD_COUNT}"
ps -p "$PID" -L -o pid,tid,stat,pcpu,pmem --no-headers 2>/dev/null | head -10
echo ""

# ---- Warnings ----
awk "BEGIN {exit !(${PROC_CPU} > 80)}"  && echo "[WARNING] Process CPU  > 80%  (${PROC_CPU}%)"
awk "BEGIN {exit !(${PROC_MEM_PCT} > 30)}" && echo "[WARNING] Process MEM  > 30%  (${PROC_MEM_MB}MB / ${PROC_MEM_PCT}%)"
[ "${DISK_USED_PCT}" -gt 80 ] && echo "[WARNING] Disk used > 80% (${DISK_USED_PCT}%)"
[ "${FIREWALL_STATUS}" = "inactive" ] && echo "[WARNING] Firewall is inactive!"

# ---- Log write ----
mkdir -p "$LOG_DIR"
rotate_log
echo "[${TIMESTAMP}] PROCESS:${APP_NAME} PID:${PID} CPU:${PROC_CPU}% MEM:${PROC_MEM_MB}MB(${PROC_MEM_PCT}%) DISK:${DISK_AVAIL}G FIREWALL:${FIREWALL_STATUS}" >> "$LOG_FILE"
echo "[INFO] Log appended: ${LOG_FILE}"
echo "===================================="
