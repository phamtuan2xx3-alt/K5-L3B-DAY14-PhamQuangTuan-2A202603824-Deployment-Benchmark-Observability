# Deployment Information

## Public URL
https://k5-day14-agent-tuan.onrender.com

## Platform
Render (Web Service `k5-day14-agent-tuan`, runtime `docker`, region `singapore`, plan `free` + Render Key Value `k5-day14-agent-redis` Redis 8.1.10)

## Test Commands

### Health Check (`GET /health`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "https://k5-day14-agent-tuan.onrender.com/health"
# Expected: 200
curl -sS "https://k5-day14-agent-tuan.onrender.com/health"
# Expected: {"status":"ok","environment":"production"}
```

### Readiness Check (`GET /ready`)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "https://k5-day14-agent-tuan.onrender.com/ready"
# Expected: 200
curl -sS "https://k5-day14-agent-tuan.onrender.com/ready"
# Expected: {"status":"ready","redis":"ok"}
```

### API Test — Missing Key (401)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "https://k5-day14-agent-tuan.onrender.com/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: 401
```

### API Test — With Authentication (200)
```bash
curl -sS -X POST "https://k5-day14-agent-tuan.onrender.com/ask" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: 200
```

## Environment Variables Set
- `PORT` (injected automatically by Render)
- `REDIS_URL` (internal connection string of `k5-day14-agent-redis`)
- `AGENT_API_KEY` (configured securely on Render, never committed to git)
- `ENVIRONMENT` (`production`)
- `LOG_LEVEL` (`INFO`)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`10.0`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
