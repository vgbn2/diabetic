# Local Nightscout & Mongo Operations Guide

> **Diátaxis Type**: How-to Guide | **Status**: Canonical | **Review**: Continuous

This guide details configuring and maintaining local Nightscout monitor instances and MongoDB databases.

---

## 1. Local Nightscout Service Architecture

Bio-Quant integrates with `nightscout/cgm-remote-monitor:15.0.3` running on Port 1337.

```yaml
# docker-compose.yml snippet
services:
  mongodb:
    image: mongo:6.0
    restart: unless-stopped
    volumes:
      - mongodb_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.adminCommand('ping').ok"]

  nightscout:
    image: nightscout/cgm-remote-monitor:15.0.3
    depends_on:
      mongodb:
        condition: service_healthy
    ports:
      - "127.0.0.1:1337:1337"
    environment:
      MONGODB_URI: mongodb://mongodb:27017/nightscout
      API_SECRET: ${NIGHTSCOUT_API_SECRET}
```

---

## 2. Backup & Migration Procedures

### Automated Database Backup
```bash
# Execute local Nightscout backup script
bash scripts/ops/backup_local_nightscout.sh --target /var/backups/diabetic/
```

### Staged Historical Restore
```bash
# Restore BSON archive into fresh local MongoDB
bash scripts/ops/stage_restore_local_nightscout.sh --source ops/lab/fixtures/historical_archive/
```
