#!/usr/bin/env python3
"""
agent-leak-app: Simulates Memory Leak, CPU Overoccupy, and Deadlock
for educational fault-analysis training.

Required env vars:
  AGENT_HOME, AGENT_PORT, AGENT_UPLOAD_DIR, AGENT_KEY_PATH, AGENT_LOG_DIR
  MEMORY_LIMIT     (int, 50-512 MB)
  CPU_MAX_OCCUPY   (int, 10-100 %)
  MULTI_THREAD_ENABLE (true/false)
"""

import os, sys, time, threading, signal, socket, datetime, gc, random, math

# ── env vars ─────────────────────────────────────────────────────────────────
AGENT_HOME          = os.environ.get('AGENT_HOME', '')
AGENT_PORT          = int(os.environ.get('AGENT_PORT', '15034'))
AGENT_UPLOAD_DIR    = os.environ.get('AGENT_UPLOAD_DIR', '')
AGENT_KEY_PATH      = os.environ.get('AGENT_KEY_PATH', '')
AGENT_LOG_DIR       = os.environ.get('AGENT_LOG_DIR', '/var/log/agent-app')
MEMORY_LIMIT        = int(os.environ.get('MEMORY_LIMIT', '256'))   # MB
CPU_MAX_OCCUPY      = int(os.environ.get('CPU_MAX_OCCUPY', '80'))  # %
MULTI_THREAD_ENABLE = os.environ.get('MULTI_THREAD_ENABLE', 'false').lower() in ('true', '1', 'yes')

KEY_CONTENT = 'agent_api_key_test'

def ts():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]

def log(level, msg):
    print(f"{ts()} [{level}] {msg}", flush=True)

# ── Boot Sequence ─────────────────────────────────────────────────────────────
def boot():
    print(">>> Starting Agent Boot Sequence...", flush=True)
    ok = True

    # [1/5] user account
    import pwd
    uid = os.getuid()
    uname = pwd.getpwuid(uid).pw_name
    if uid == 0:
        print("[1/5] Checking User Account               [FAIL]")
        print(" >>> Must not run as root.")
        ok = False
    else:
        print("[1/5] Checking User Account               [OK]")
        print(f" ... Running as service user '{uname}' (uid={uid})")

    # [2/5] env vars
    missing = [v for v in ['AGENT_HOME','AGENT_PORT','AGENT_UPLOAD_DIR','AGENT_KEY_PATH','AGENT_LOG_DIR',
                            'MEMORY_LIMIT','CPU_MAX_OCCUPY','MULTI_THREAD_ENABLE'] if not os.environ.get(v)]
    ml = MEMORY_LIMIT; cm = CPU_MAX_OCCUPY
    if missing or not (50 <= ml <= 512) or not (10 <= cm <= 100):
        print("[2/5] Verifying Environment Variables     [FAIL]")
        if missing: print(f" >>> Missing: {missing}")
        if not (50 <= ml <= 512): print(f" >>> MEMORY_LIMIT out of range: {ml}")
        if not (10 <= cm <= 100): print(f" >>> CPU_MAX_OCCUPY out of range: {cm}")
        ok = False
    else:
        print("[2/5] Verifying Environment Variables     [OK]")
        print(" ... All required Envs correct")

    # [3/5] key file
    if ok:
        key_file = AGENT_KEY_PATH
        if not os.path.isfile(key_file):
            print("[3/5] Checking Required Files             [FAIL]")
            print(f" >>> Key file not found: {key_file}")
            ok = False
        else:
            with open(key_file) as f:
                content = f.read().strip()
            if content != KEY_CONTENT:
                print("[3/5] Checking Required Files             [FAIL]")
                print(f" >>> Key content mismatch")
                ok = False
            else:
                print("[3/5] Checking Required Files             [OK]")
                print(" ... Verified 'secret.key' with correct key string.")

    # [4/5] port
    if ok:
        try:
            s = socket.socket()
            s.bind(('0.0.0.0', AGENT_PORT))
            s.close()
            print("[4/5] Checking Port Availability          [OK]")
            print(f" ... Port {AGENT_PORT} is available.")
        except OSError:
            print("[4/5] Checking Port Availability          [FAIL]")
            print(f" >>> Port {AGENT_PORT} is already in use")
            ok = False

    # [5/5] log dir
    if ok:
        if os.access(AGENT_LOG_DIR, os.W_OK):
            print("[5/5] Verifying Log Permission            [OK]")
            print(f" ... Log directory is writable: {AGENT_LOG_DIR}")
        else:
            print("[5/5] Verifying Log Permission            [FAIL]")
            print(f" >>> Log directory not writable: {AGENT_LOG_DIR}")
            ok = False

    print("-" * 60, flush=True)
    if not ok:
        print("System Boot Failed. Process Terminated.", flush=True)
        sys.exit(1)

    print("All Boot Checks Passed!")
    print("Agent READY", flush=True)

# ── Helpers ──────────────────────────────────────────────────────────────────
def get_rss_mb():
    try:
        with open(f'/proc/{os.getpid()}/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return 0.0

def cpu_burn(seconds):
    """Burn CPU for `seconds` seconds."""
    end = time.time() + seconds
    acc = 0.0
    while time.time() < end:
        acc += math.sqrt(random.random())
    return acc

# ── Scenario: OOM / Memory Leak ──────────────────────────────────────────────
def run_oom():
    log('INFO', f'[SafetyGuard] Process priority lowered (nice=10).')
    log('INFO', f'Agent listening at port {AGENT_PORT}')
    log('INFO', '=== Agent Started. Memory Leak Mode. ===')
    log('INFO', f'[MemoryGuard] Limit set to {MEMORY_LIMIT} MB.')

    os.nice(10)
    leak_pool = []
    step = 0
    while True:
        step += 1
        chunk = bytearray(10 * 1024 * 1024)   # 10 MB genuine allocation
        leak_pool.append(chunk)

        rss = get_rss_mb()
        log('INFO', f'[Memory] Leaked +10 MB. Total RSS: {rss:.0f} MB (step {step})')

        if rss >= MEMORY_LIMIT:
            log('CRITICAL', f'[MemoryGuard] Memory limit exceeded ({rss:.0f}MB >= {MEMORY_LIMIT}MB) / (Recommend Over {MEMORY_LIMIT}MB)')
            log('CRITICAL', f'[MemoryGuard] Self-terminating process {os.getpid()} to prevent system instability.')
            print(f'>>> [SYSTEM] SELF-TERMINATED (Memory Limit Exceeded) <<<', flush=True)
            sys.exit(1)

        time.sleep(2)

# ── Scenario: CPU Overoccupy ─────────────────────────────────────────────────
def get_proc_cpu_pct(pid, interval=0.5):
    """Compute process CPU% over `interval` seconds."""
    def read_cpu():
        with open(f'/proc/{pid}/stat') as f:
            parts = f.read().split()
        utime = int(parts[13]); stime = int(parts[14])
        with open('/proc/uptime') as f:
            uptime = float(f.read().split()[0])
        return utime + stime, uptime

    t1_proc, t1_sys = read_cpu()
    time.sleep(interval)
    t2_proc, t2_sys = read_cpu()

    clk = os.sysconf('SC_CLK_TCK')
    proc_delta = (t2_proc - t1_proc) / clk
    sys_delta  = (t2_sys  - t1_sys)
    if sys_delta <= 0:
        return 0.0
    return min(100.0, proc_delta / sys_delta * 100.0)

def run_cpu():
    log('INFO', f'[SafetyGuard] Process priority lowered (nice=10).')
    log('INFO', f'Agent listening at port {AGENT_PORT}')
    log('INFO', '=== Agent Started. CPU Spike Mode. ===')
    log('INFO', f'[Watchdog] CPU cap set to {CPU_MAX_OCCUPY}%.')

    os.nice(10)
    level = 1
    while True:
        log('INFO', f'[CPU] Level {level} workload starting...')
        burn_time = 0.2 * level  # level 10 = 2s of 100% CPU per cycle

        t_start = time.time()
        cpu_burn(burn_time)
        t_burn_end = time.time()
        time.sleep(1)            # idle portion of cycle
        t_end = time.time()

        # CPU% = active burn time / total cycle time
        actual_burn = t_burn_end - t_start
        cycle = t_end - t_start
        cpu_pct = (actual_burn / cycle) * 100.0

        log('INFO', f'[CPU] Level {level} workload completed. Duration: {actual_burn:.2f}s, CPU: {cpu_pct:.1f}%')

        if cpu_pct > CPU_MAX_OCCUPY:
            log('CRITICAL', f'[Watchdog] CPU overoccupy detected: {cpu_pct:.1f}% > {CPU_MAX_OCCUPY}%')
            log('CRITICAL', f'[Watchdog] INITIATING EMERGENCY ABORT (SIGTERM) for PID {os.getpid()}')
            print(f'>>> [SYSTEM] WATCHDOG: INITIATING EMERGENCY ABORT (SIGTERM) <<<', flush=True)
            sys.exit(1)

        level = min(level + 1, 10)

# ── Scenario: Deadlock ───────────────────────────────────────────────────────
def run_deadlock():
    log('INFO', f'[SafetyGuard] Process priority lowered (nice=10).')
    log('INFO', f'Agent listening at port {AGENT_PORT}')
    log('INFO', '=== Agent Started. Multi-Thread Mode. ===')
    log('INFO', '[ThreadMgr] Spawning worker threads...')

    lock_a = threading.Lock()
    lock_b = threading.Lock()

    def thread_worker_a():
        log('INFO', '[Thread-A] Task Started. Acquiring Resource-A...')
        with lock_a:
            log('INFO', '[Thread-A] Acquired Resource-A. Calculating... (50%)')
            time.sleep(0.5)
            log('INFO', '[Thread-A] WAITING for Resource-B... [BLOCKED]')
            with lock_b:   # will block — Thread-B holds lock_b
                log('INFO', '[Thread-A] Acquired Resource-B. Task Done. (100%)')

    def thread_worker_b():
        log('INFO', '[Thread-B] Task Started. Acquiring Resource-B...')
        with lock_b:
            log('INFO', '[Thread-B] Acquired Resource-B. Calculating... (50%)')
            time.sleep(0.5)
            log('INFO', '[Thread-B] WAITING for Resource-A... [BLOCKED]')
            with lock_a:   # will block — Thread-A holds lock_a
                log('INFO', '[Thread-B] Acquired Resource-A. Task Done. (100%)')

    t_a = threading.Thread(target=thread_worker_a, name='Thread-A', daemon=True)
    t_b = threading.Thread(target=thread_worker_b, name='Thread-B', daemon=True)

    t_a.start()
    time.sleep(0.1)   # ensure Thread-A grabs lock_a first
    t_b.start()

    log('INFO', '[ThreadMgr] All threads running. Monitoring...')

    # Main thread keeps the process alive (zombie state for deadlock demo)
    while True:
        time.sleep(5)
        log('INFO', f'[ThreadMgr] Status check — Thread-A alive:{t_a.is_alive()} Thread-B alive:{t_b.is_alive()}')

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    boot()

    if MULTI_THREAD_ENABLE:
        run_deadlock()
    elif MEMORY_LIMIT < 512:
        # OOM scenario: low memory limit → leak until terminated
        run_oom()
    else:
        # CPU scenario: high memory limit → focus on CPU spike
        run_cpu()
