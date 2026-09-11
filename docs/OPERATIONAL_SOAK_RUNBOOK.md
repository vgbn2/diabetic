# Operational Soak & Runtime Runbook

> **Diátaxis Type**: How-to Guide & Runbook | **Status**: Canonical | **Owner**: Platform Operations | **Review**: Continuous

This runbook outlines operational procedures for executing, monitoring, diagnosing, and soaking the Bio-Quant daemon.

---

## 1. Starting the Bio-Quant Daemon

### Via Docker Compose (Recommended Production Mode)
```bash
# Start MongoDB, Local Nightscout, and Bio-Quant Engine in background
docker compose up -d

# View live container logs
docker compose logs -f bio-quant-core

# Verify health status of all 3 services
docker compose ps
```

### Direct CLI Host Execution
```bash
# Activate virtual environment
source .venv/bin/activate

# Launch live monitoring daemon
python -m diabetic.main live --port 8000
```

---

## 2. Soak Testing & Resource Invariant Monitoring

During extended 24-hour soak runs, monitor resource consumption to ensure no memory leakage or thread proliferation occurs:

```bash
# Monitor RSS memory, CPU usage, and open file descriptors
ps aux | grep "python -m diabetic.main live"

# Verify single-thread linear algebra clamping
python -c "import torch; print('Torch Threads:', torch.get_num_threads())"
```

### Soak Health Thresholds
- **RSS Memory**: Must remain stable under **600 MB** over 72 hours.
- **CPU Usage**: Average < **5%** on 1 core between polling epochs, spiking to < **25%** during inference cycles.
- **File Descriptors**: Must remain constant (< **64 FDs**) with zero leaked database connection handles.

---

## 3. Emergency Recovery & PID Lock Reset

If the daemon is killed abruptly with `SIGKILL` (`kill -9`) leaving a stale `diabetic.lock` file:

```bash
# 1. Verify no existing process is running on port 8000
lsof -i :8000

# 2. Safely purge stale lock if verified dead
python -c "from diabetic.coordinator import Coordinator; Coordinator.cleanup_stale_locks()"

# 3. Restart daemon
python -m diabetic.main live
```
