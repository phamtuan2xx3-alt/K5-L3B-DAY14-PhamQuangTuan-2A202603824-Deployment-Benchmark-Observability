# Day 14 Lab — Mission Answers

> **Họ tên:** Phạm Quang Tuấn  
> **MSSV:** `2A202603824` · **Lớp:** `K5-L3B`  
> **Repository:** `K5-L3B-DAY14-PhamQuangTuan-2A202603824-Deployment-Benchmark-Observability`

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcoded secrets (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` đặt trực tiếp trong source code; đẩy lên Git công khai là lộ ngay. Trong `production/config.py`, toàn bộ bí mật và cấu hình được đọc từ biến môi trường (`os.getenv(...)`).
2. **Không quản lý cấu hình tập trung / hardcode config (dòng 21–22):** `DEBUG = True`, `MAX_TOKENS = 500` viết cứng ngay trong `app.py`, không đổi được giữa `dev`/`staging`/`production` mà không sửa code. Bản `production/` tách sang `Settings` dataclass trong `config.py` kèm `.env.example`.
3. **Dùng `print()` thay cho structured logging và làm lộ secret ra log (dòng 33–38):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` in thẳng API key ra stdout và khó parse trong log aggregator. Bản `production/app.py` dùng `logging` định dạng JSON (`json.dumps({...})`) và không bao giờ ghi secret.
4. **Thiếu endpoint health check & readiness (dòng 42–43):** Không có `GET /health` hay `GET /ready`, nên cloud platform/load balancer không biết khi nào process treo hoặc chưa sẵn sàng nhận traffic. Bản `production/app.py` cung cấp đủ `GET /health` (liveness) và `GET /ready` (readiness, trả 503 khi `is_ready=False`).
5. **Bind `localhost`, port cố định `8000`, bật `reload=True` và thiếu graceful shutdown (dòng 49–54):** `host="localhost"` khiến container không nhận kết nối từ bên ngoài; `port=8000` bỏ qua biến `PORT` do platform cấp; `reload=True` tốn tài nguyên và không an toàn ở production; không xử lý `SIGTERM` / `lifespan`. Bản `production/app.py` bind `0.0.0.0`, đọc `PORT` từ env, tắt `reload` theo `DEBUG`, và dùng `lifespan` + `signal.signal(signal.SIGTERM, handle_sigterm)`.

### Exercise 1.2: Kết quả chạy bản `develop`

```text
$ curl -sS -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 07:44:39 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop | Production | Tại sao quan trọng? |
| --- | --- | --- | --- |
| Config | Hardcode trực tiếp (`DEBUG = True`, `MAX_TOKENS = 500`) | Đọc từ biến môi trường qua `Settings` (`config.py`) + `.env.example` | Đổi cấu hình giữa dev/staging/prod mà không cần sửa code hay build lại image (12-Factor III). |
| Secrets | Hardcode `OPENAI_API_KEY`, `DATABASE_URL` trong code | `os.getenv("OPENAI_API_KEY")`, `os.getenv("AGENT_API_KEY")`, fail-fast khi thiếu ở prod | Tránh rò rỉ thông tin nhạy cảm vào lịch sử Git và tách biệt quyền truy cập secret theo môi trường. |
| Host & Port | `host="localhost"`, `port=8000`, `reload=True` | `host="0.0.0.0"`, `port=int(os.getenv("PORT", 8000))`, `reload=settings.debug` | `0.0.0.0` cho phép nhận traffic từ ngoài container; đọc `PORT` giúp nền tảng PaaS (Render/Railway/Cloud Run) tự định tuyến cổng. |
| Health check | Không có (`/health` 404) | `GET /health` (200) và `GET /ready` (200 / 503) | Cho phép orchestrator/load balancer tự động kiểm tra sống-chết để restart hoặc ngắt route khi chưa sẵn sàng. |
| Logging | `print()` plain text, còn in cả API key | `logging` định dạng JSON có `event`, `question_length`, `client_ip` (không log secret) | Dễ thu thập, tìm kiếm, lọc và dựng dashboard/alert trên Loki, Datadog hoặc Cloud Logging. |
| Shutdown | Tắt đột ngột | `lifespan` (`is_ready = False`) + bắt `SIGTERM` | Cho phép request đang chạy hoàn thành trước khi process thoát, tránh lỗi HTTP giữa chừng khi deploy bản mới. |

---

## Part 2: Docker

### Exercise 2.1: Trả lời câu hỏi `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (bản Debian đầy đủ kèm Python 3.11 và công cụ hệ thống, dung lượng ~1 GB+).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Tại sao `COPY requirements.txt` đứng trước `COPY . .`:** Docker cache theo từng layer. Khi chỉ sửa source code (`app.py`), các layer trước (`COPY requirements.txt` và `RUN pip install`) không đổi nên Docker dùng lại cache, không phải tải và cài lại toàn bộ thư viện.
4. **`CMD` vs `ENTRYPOINT`:** `CMD` định nghĩa lệnh hoặc tham số mặc định có thể bị ghi đè dễ dàng khi chạy `docker run <image> <lệnh_mới>`; còn `ENTRYPOINT` cố định file/chương trình thực thi chính của container (các đối số truyền thêm lúc `docker run` sẽ được nối vào sau `ENTRYPOINT`).

### Exercise 2.2: Build & chạy container `my-agent:develop`

```text
$ curl -sS -i http://127.0.0.1:8000/health
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 08:10:25 GMT
server: uvicorn
content-length: 53
content-type: application/json

{"status":"ok","uptime_seconds":0.5,"container":true}

$ curl -sS -i -X POST "http://127.0.0.1:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 08:10:25 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: So sánh kích thước image `develop` vs `production` (multi-stage)

- **Stage 1 (`builder`):** Dùng `python:3.11-slim`, cài `gcc`, `libpq-dev` rồi chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`):** Bắt đầu từ `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local` cùng `main.py` và `utils/mock_llm.py`, không mang `gcc`/headers biên dịch vào image cuối.
- **Kích thước đo thực tế bằng `docker images my-agent`:**
  - `my-agent:develop`: **1.67 GB** (`1670 MB`)
  - `my-agent:advanced`: **240 MB**
  - **Chênh lệch:** Giảm **1,430 MB** (**85.6%** nhỏ hơn).

### Exercise 2.4: Kiến trúc Docker Compose stack & test qua Nginx

**Sơ đồ kiến trúc (`02-docker/production/docker-compose.yml`):**

```text
Client ──(HTTP :80)──▶ Nginx (reverse proxy + rate limit 10r/s)
                          │ (network: internal)
                          ▼
                      Agent (:8000, uvicorn 2 workers)
                       ├──▶ Redis (:6379, cache / rate limit, volume redis_data)
                       └──▶ Qdrant (:6333, vector DB cho RAG, volume qdrant_data)
```

4 service khởi chạy (`agent`, `nginx`, `qdrant`, `redis`) giao tiếp qua mạng nội bộ `internal` bằng Docker DNS theo tên service (`redis://redis:6379/0`, `http://qdrant:6333`), chỉ `nginx` mở cổng ra ngoài. *(Lưu ý trên Windows: cổng 80 bị Windows HTTP.sys giữ riêng nên chạy test với override cổng host `8081:80` vào cổng 80 của container Nginx.)*

```text
$ docker compose -p k5-day14-docker ps --format "table {{.Name}}\t{{.Service}}\t{{.Status}}\t{{.Ports}}"
NAME                       SERVICE   STATUS                            PORTS
k5-day14-docker-agent-1    agent     Up 4 seconds (health: starting)   8000/tcp
k5-day14-docker-nginx-1    nginx     Up 4 seconds                      0.0.0.0:8081->80/tcp, [::]:8081->80/tcp
k5-day14-docker-qdrant-1   qdrant    Up 15 seconds (healthy)           6333-6334/tcp
k5-day14-docker-redis-1    redis     Up 15 seconds (healthy)           6379/tcp

$ curl -sS -i http://127.0.0.1:8081/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"status":"ok","uptime_seconds":2.6,"version":"2.0.0","timestamp":"2026-11-26T08:11:27.147586"}

$ curl -sS -i -X POST http://127.0.0.1:8081/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

---

## Part 3: Cloud Deployment

### Deploy chính trên Render (Exercise 3.2 — agent Part 6)

- **Public URL:** https://k5-day14-agent-tuan.onrender.com
- **Platform:** Render (`k5-day14-agent-tuan` Web Service, runtime `docker`, plan `free`, region `singapore`) + Render Key Value (`k5-day14-agent-redis`, Redis 8.1.10, `allkeys-lru`).
- **Tài liệu & ảnh chụp:** Xem [DEPLOYMENT.md](DEPLOYMENT.md) và [screenshots/dashboard.png](screenshots/dashboard.png), [screenshots/running.png](screenshots/running.png), [screenshots/test.png](screenshots/test.png).

Kết quả 4 lệnh tự kiểm trên URL public:

```text
GET  https://k5-day14-agent-tuan.onrender.com/health                 -> 200 {"status":"ok","environment":"production"}
GET  https://k5-day14-agent-tuan.onrender.com/ready                  -> 200 {"status":"ready","redis":"ok"}
POST https://k5-day14-agent-tuan.onrender.com/ask (no key)           -> 401 {"detail":"Invalid or missing X-API-Key"}
POST https://k5-day14-agent-tuan.onrender.com/ask (X-API-Key valid)  -> 200 {"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"input_tokens":1,"output_tokens":17,"cost_usd":1.035e-05}}
```

### So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` | `render.yaml` |
| --- | --- | --- |
| Định dạng & phạm vi | TOML; chỉ cấu hình **1 service hiện tại** (`[build]`, `[deploy]`). | YAML Blueprint (IaC); khai báo được **cả cụm multi-service** (`web` + `keyvalue`/`redis` + database) trong 1 file. |
| Builder / Runtime | `builder = "DOCKERFILE"` hoặc `"NIXPACKS"`, tuỳ chọn `startCommand` (Nixpacks). | `runtime: docker` (kèm `rootDir`, `dockerfilePath`) hoặc `runtime: python` (`buildCommand`, `startCommand`). |
| Liên kết Redis & Env vars | Tạo Redis trên dashboard/CLI rồi tự tham chiếu biến; đặt biến qua `railway variables set` hoặc UI. | Liên kết trực tiếp qua `fromService: { type: keyvalue, name: ..., property: connectionString }`. |
| Quản lý Secret | Không khai báo trong `railway.toml`; truyền qua dashboard/CLI. | Khai báo tên biến trong `envVars` với `generateValue: true` (tự sinh random) hoặc `sync: false` (nhập tay trên UI) để không lộ giá trị vào Git. |
| Health check & Restart | `healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType = "ON_FAILURE"`. | `healthCheckPath: /health`, `autoDeploy: true`, `plan`, `region` ngay trong spec service. |

### Exercise 3.3: Mô tả pipeline CI/CD GCP Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Pipeline trong `cloudbuild.yaml` chạy tự động gồm 4 bước tuần tự (`waitFor`):
1. **`test`** (trên `python:3.11-slim`): cài `requirements.txt` + `pytest` và chạy `pytest tests/ -v` để chặn build nếu test lỗi.
2. **`build`** (`gcr.io/cloud-builders/docker`): build Docker image gắn 2 tag (`$COMMIT_SHA` và `latest`), tận dụng `--cache-from` từ image `latest`.
3. **`push`** (`gcr.io/cloud-builders/docker`): đẩy tất cả tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`** (`gcr.io/cloud-builders/gcloud`): chạy `gcloud run deploy` triển khai image `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`), cấu hình public endpoint, `min-instances=1` (giảm cold start), `max-instances=10`, `512Mi` RAM / `1` CPU, và nạp secret từ Secret Manager (`--set-secrets`); kết hợp file `service.yaml` (Knative) để định nghĩa thêm `containerConcurrency: 80`, `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

`verify_api_key` đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)`: thiếu header → `401`, sai key → `403`, khớp `AGENT_API_KEY` → `200`. Để rotate key an toàn, hỗ trợ danh sách key cũ + mới song song (grace period) qua env var rồi thu hồi key cũ sau khi client cập nhật xong.

```text
# Không có key -> 401
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Sai key -> 403
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# Đúng key (X-API-Key: secret-key-123) -> 200
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Phân tích `rate_limiter.py`:** Dùng thuật toán **Sliding Window Counter** lưu trên `deque` trong RAM (`self._windows[user_id]`). Mỗi lần check, hệ thống xoá các timestamp cũ hơn `now - 60s`; nếu độ dài `>= max_requests` thì trả `429` kèm `Retry-After` và `X-RateLimit-*`. Limit mặc định là **10 requests/phút** cho user (`rate_limiter_user`) và **100 requests/phút** cho admin (`rate_limiter_admin`). Để bypass/tăng limit cho admin, `app.py` kiểm tra `role` giải mã từ JWT (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`).
- **Kết quả lấy token (`student` / `demo123`), gọi `/ask` (200) và vòng lặp 12 request hit `429`:**

```text
# 1. Gọi /ask với Authorization: Bearer <JWT_TOKEN_REDACTED> -> 200
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}

# 2. Vòng lặp tiếp theo (token student giới hạn 10 req/phút nên từ request thứ 10 trong loop bị 429):
Request 1:  HTTP 200 -> {"usage":{"requests_remaining":8,...}}
...
Request 9:  HTTP 200 -> {"usage":{"requests_remaining":0,...}}
Request 10: HTTP 429 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Request 11: HTTP 429 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}

# Header đầy đủ của response 429:
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795679416
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cách làm Cost Guard

- **Cơ chế:** Trước khi gọi LLM, `check_budget()` kiểm tra tổng chi phí tích luỹ (theo ngày/tháng) đang lưu trong Redis; nếu `current_spent >= budget` thì chặn ngay bằng **`HTTP 402 Payment Required`** để không gọi sang LLM provider. Sau khi LLM trả lời, `record_cost(input_tokens, output_tokens)` tính chi phí dựa trên đơn giá token (`PRICE_INPUT_PER_1K`, `PRICE_OUTPUT_PER_1K`), cộng dồn vào Redis bằng lệnh atomic `INCRBYFLOAT` và đặt `EXPIRE` để tự reset sang chu kỳ mới.
- **Tại sao cần cả Rate Limit và Cost Guard:** Rate Limit kiểm soát **tốc độ** (số request/phút để chống spam/DoS), còn Cost Guard kiểm soát **tổng tiền** (tránh kịch bản kẻ xấu hoặc người dùng gửi câu hỏi rất dài ở tốc độ thấp hợp lệ nhưng vẫn đốt hết ngân sách token).

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health check & Graceful shutdown (`05-scaling-reliability/develop/`)

- **Phân biệt Liveness (`/health`) vs Readiness (`/ready`):** `/health` kiểm tra process còn sống không (nếu fail thì orchestrator restart container); `/ready` kiểm tra instance đã khởi động xong và kết nối phụ thuộc (như Redis/DB) có sẵn sàng nhận traffic chưa (nếu fail 503 thì load balancer tạm ngừng chuyển request tới instance đó chứ không restart).
- **Kết quả test `/health`, `/ready` và `kill -SIGTERM` khi đang có request in-flight:**

```text
$ curl -sS -i http://127.0.0.1:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:49:19.407647+00:00","checks":{"memory":{"status":"ok","used_percent":8.8}}}

$ curl -sS -i http://127.0.0.1:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}

# Gửi POST /ask?question=hello (delay ~0.1s) rồi gửi ngay SIGTERM -> request vẫn hoàn thành 200 OK:
HTTP/1.1 200 OK
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

# Log server khi nhận SIGTERM:
INFO:     Shutting down
INFO:     127.0.0.1:58682 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 14:49:22,537 INFO 🔄 Graceful shutdown initiated...
2026-11-26 14:49:22,537 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [2441]
2026-11-26 14:49:22,537 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

### Exercise 5.3–5.5: Stateless Design & Load Balancing (`05-scaling-reliability/production/`)

- **Tại sao state trong RAM bị hỏng khi scale:** Khi Nginx điều phối round-robin giữa 3 replica, mỗi container có RAM riêng biệt; request 1 vào `instance A` sẽ không thấy session nằm trong RAM của `instance B` ở request 2. Đưa session/history (kèm TTL) vào Redis giúp mọi instance đều đọc/ghi chung một nguồn trạng thái.
- **Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`:**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 767bde23-a4b9-44c1-acc3-14f3a27b884e

Request 1: [instance-d08164]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-ea115e]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 3: [instance-d08164]
  Q: What is Kubernetes?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 4: [instance-37d253]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 5: [instance-ea115e]
  Q: What is Redis used for?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-ea115e', 'instance-37d253', 'instance-d08164'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

5 request được Nginx chia qua đủ 3 instance khác nhau (`instance-d08164`, `instance-ea115e`, `instance-37d253`), nhưng toàn bộ 10 message (5 turn hỏi-đáp) vẫn được bảo toàn đầy đủ nhờ lưu trong Redis.

---

## Part 6: Final Project (`06-lab-complete/`)

Chạy `python check_production_ready.py` (bản đầy đủ có Docker trong môi trường WSL2 Debian `posix`):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 42/42 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

- Kích thước image Docker build thực tế: **63 MB** (`< 500 MB`).
- `docker stop` thoát êm với exit code `0` trong **0.6s**.
- Mọi dòng log ứng dụng là JSON hợp lệ (`17 dòng JSON` trong lần kiểm thử runtime).

---

## AI Log

| Giai đoạn | Hỏi / Nhờ AI làm gì | Nhận được gì | Sinh viên tự kiểm tra & xác minh thế nào |
| --- | --- | --- | --- |
| Part 6 (`06-lab-complete/`) | Gợi ý cấu trúc hoàn thiện các module `config.py`, `auth.py`, `rate_limiter.py`, `cost_guard.py`, `redis_client.py`, `main.py`, multi-stage `Dockerfile`, `docker-compose.yml`, `render.yaml`. | Bộ code FastAPI + Redis + Dockerfile multi-stage + `render.yaml`. | Đọc lại từng file, chạy `render blueprints validate render.yaml` (`valid: true`), chạy `check_production_ready.py` đầy đủ trong WSL2 Debian đạt `PASS 12/12` (42/42 checks, image 63 MB) và kiểm tra `docker compose up` trực tiếp. |
| Part 1–5 & Part 3 (Render) | Hỗ trợ chạy lệnh thực hành trên WSL2 Debian, triển khai dịch vụ Render qua Render CLI và tổng hợp bảng so sánh `railway.toml` vs `render.yaml` + pipeline Cloud Run. | Output lệnh `curl`, `docker images`, `test_stateless.py`, và dịch vụ Render live tại `https://k5-day14-agent-tuan.onrender.com`. | Tự kiểm tra đối chiếu mã HTTP trả về (`200`, `200`, `401`, `200`), kiểm tra từng con số dung lượng image (`1.67 GB` vs `240 MB`), và xác nhận không chứa secret hay thông tin nhạy cảm trong repo. |
| Part 7 (`benchmark-observability/`) | Hỗ trợ chạy kịch bản load test, eval, sửa 2 entry `KNOWLEDGE_BASE` trong `mock_llm.py` và chạy các thí nghiệm Prometheus/Grafana/Jaeger/Locust. | File JSON/CSV, 2 entry mới cho `hpa/kubernetes` và `jwt`, cùng số liệu chaos/trace. | Tự đối chiếu toàn bộ số liệu trong `BENCHMARK_REPORT.md` khớp chính xác với các file trong `reports/` và `benchmark-results/`, xem trực tiếp từng ảnh chụp trong `screenshots/` và kiểm tra không sửa `check_production_ready.py` hay `golden_dataset.jsonl`. |
