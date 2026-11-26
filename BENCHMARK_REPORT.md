# Benchmark & Observability Report — Day 14

**Họ tên:** Phạm Quang Tuấn (`MSSV: 2A202603824`)  
**Ngày chạy:** 2026-11-26  
**Môi trường:** Windows 11 + WSL2 Debian (Python 3.13.5) + Docker Desktop 28.3.0, Intel Core i5-11400H @ 2.70GHz, 31.8 GB RAM

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
| --- | --- | --- |
| p95 latency `/ask` | `< 500 ms` | Với mock LLM bình thường (~120–210 ms) + retrieval (~20 ms), 95% request phải hoàn thành dưới 500 ms để đảm bảo trải nghiệm mượt cho người dùng mà không bị tail latency (3% request chậm ~1.7s) làm fail SLO. |
| Error rate `/ask` | `< 2.0 %` | Mock LLM có tỷ lệ lỗi upstream ngẫu nhiên 1% (`MOCK_ERROR_RATE=0.01`); đặt ngưỡng < 2% tạo error budget hợp lý cho dao động ngắn nhưng bắt được ngay sự cố tăng lỗi thực sự. |
| Accuracy trên golden dataset | `>= 85 %` | Đảm bảo chất lượng trả lời không tụt xuống mức agent v1 (4.3%) khi thay đổi prompt/retrieval; sau khi bổ sung Knowledge Base đặt ngưỡng CI 100% không regression. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 3.92 | 192.5 | 227.7 | 1704.9 | 1.00% | PASS |
| 10 | 38.05 | 191.1 | 223.1 | 1703.4 | 0.67% | PASS |
| 50 | 118.08 | 204.8 | 308.9 | 1711.6 | 1.33% | PASS |
| 100 | 50.29 | 579.8 | 3708.1 | 4091.2 | 1.33% | FAIL |

*(Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.)*

**Nhận xét:** RPS **không** tăng tuyến tính mãi theo concurrency. Từ `c=1` đến `c=50`, vì endpoint async xử lý I/O chờ LLM song song tốt nên RPS tăng mạnh từ `3.92` lên `118.08 req/s` và p95 vẫn đạt SLO (`308.9 ms`). Tuy nhiên khi đẩy lên `c=100`, 1 process uvicorn bị quá tải/nghẽn hàng đợi event loop nên RPS **tụt xuống `50.29 req/s`**, p95 nhảy vọt lên **`3708.1 ms`** và vi phạm SLO.

### 2.2 Tail latency (`concurrency = 20`, `300 requests`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
| --- | ---: | ---: | ---: |
| 0 | 194.7 | 224.3 | 253.7 |
| 0.03 (mặc định) | 228.6 | 222.6 | 1703.2 |
| 0.1 | 340.7 | 1694.7 | 1722.0 |

*(Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.)*

**Nhận xét:** **`p99` và `p95` nhạy nhất** với các request chậm bất thường: ở `MOCK_SLOW_RATE=0.03` (3% chậm), `avg` chỉ tăng từ `194.7 ms` lên `228.6 ms` (+33.9 ms) trông rất ổn, nhưng `p99` nhảy vọt từ `253.7 ms` lên **`1703.2 ms`**. Khi tăng lên `0.1` (10% chậm > 5%), cả `p95` cũng vọt lên **`1694.7 ms`** trong khi `avg` mới là `340.7 ms`. Do đó không nên đặt SLO theo `average` vì giá trị trung bình che giấu nhóm người dùng đang phải chờ gần 2 giây; SLO phải đặt theo **percentile (`p95`/`p99`)**.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
| --- | --- | --- | --- |
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 58.3 | 109.0 | 113.7 |
| Tổng cost (USD) | $0.000420 | $0.000760 | $0.000790 |
| Cost / câu đúng (USD) | $0.00042015 | $0.00003619 | $0.00003436 |
| Quality gate | FAIL | PASS | PASS |

*(Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.)*

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
| --- | --- | --- |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry từ khoá `["jwt"]` giải thích sự khác biệt giữa API key cố định và JWT có chữ ký số + thời điểm hết hạn vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry từ khoá `["hpa", "kubernetes", "autoscal"]` mô tả Kubernetes HPA scale theo CPU, memory hoặc custom metrics vào `KNOWLEDGE_BASE`. |

**Quality gate trong CI:** `eval/run_eval.py` trả về **exit code `1`** nếu `accuracy < --min-accuracy` hoặc có bất kỳ câu nào bị regression so với `--baseline` (đã kiểm chứng thực tế khi chạy eval `v1` với `--min-accuracy 0.85 --baseline reports/eval_v2.json` → exit code `1`). Trong GitHub Actions, đặt bước chạy eval sẽ tự động làm job fail và chặn merge PR:

```yaml
name: quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - name: Run agent + eval quality gate
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          pip install -r requirements.txt
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
          sleep 3
          python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline reports/eval_v2.json
```

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**  
Agent v2 thêm bước retrieval nên `Avg tokens / câu` tăng gần gấp đôi (`58.3 → 109.0`, tăng ~87%), tổng chi phí 23 câu tăng từ `$0.000420` lên `$0.000760` và latency `p95` tăng thêm ~20.7 ms (`189.1 → 209.8 ms`). Đổi lại, độ chính xác nhảy vọt từ **4.3% → 91.3%** (và **100%** sau khi bổ sung KB), khiến chỉ số hiệu quả thực sự **`Cost / câu đúng` giảm hơn 11 lần** (từ `$0.00042015` xuống `$0.00003619` và `$0.00003436`).

---

## 4. Observability stack (production)

### 4.1 Screenshot & Trả lời Exercise 7.4

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với ít nhất 2 alert đang **firing**: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Trả lời Exercise 7.4 (quan sát trực tiếp trên tải 30 users, 2 replica):**
1. **p95 và avg:** Khi chạy tải ổn định, Prometheus/Grafana ghi nhận `p95 = 294.42 ms` (`294.15 ms` trên panel) và `avg = 235.53 ms`. Khoảng cách tương đối gần (~59 ms) khi `p99 ~ 1.8 s` cho thấy 95% request đều nhanh và ổn định, chỉ một phần nhỏ ~3% tail latency mới bị chậm (~1.7 s).
2. **Panels Requests/s theo instance:** Nginx chia tải rất đều giữa 2 instance agent (`192.168.16.4:8000` đạt `9.274 req/s` và `192.168.16.7:8000` đạt `9.183 req/s`, tổng ~18.3–18.5 req/s).
3. **Vì sao input tokens/s (`1415.0 tok/s`) lớn hơn output tokens/s (`738.6 tok/s`):** Ở agent v2 (RAG), phần prompt đầu vào bao gồm cả `SYSTEM_PROMPT`, tài liệu context tìm được từ Knowledge Base và câu hỏi người dùng nên dài hơn câu trả lời ngắn gọn đầu ra.
4. **`curl http://localhost:8080/metrics` trả về gì và vì sao:** Trả về **`404 Not Found`** từ Nginx, vì `nginx.conf` cấu hình rõ `location = /metrics { return 404; }` để không lộ thông số hệ thống nội bộ ra Internet — chỉ Prometheus trong mạng Docker nội bộ `obs_net` mới được phép scrape trực tiếp `:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống"

*(Unit test alert rules: `promtool test rules /p/alert_rules_test.yml` → **`SUCCESS`**.)*

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
| --- | --- | --- | --- | --- |
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | `90.1 s` | `Error rate`, `Requests/s theo status code` (`503`) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | `150.1 s` | `Latency /ask — p50 / p95 / p99` (`p95` vượt đường đỏ 1s) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | `145.1 s` (burn rate `$4.22/giờ`) | `Cost burn rate (USD/giờ)`, `LLM latency p95 theo model` |
| D | `docker pause` 1 instance (`k5-day14-observability-agent-1`) | `AgentInstanceDown` | `43.6 s` | `Instances`, `Requests/s theo instance` |
| E | `AGENT_VERSION=v1` | Không kích hoạt alert hạ tầng mới (`agent_info` đổi sang `v1`) | Không áp dụng (0 alert mới từ v1) | `Retrieval hit ratio` mất dữ liệu hit, `Tokens/s` giảm, bảng version chuyển `v1` |

*(Ghi chú: Thí nghiệm A và B được bật đồng thời để chụp ảnh [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png) hiển thị cả `AgentHighErrorRate` và `AgentHighLatencyP95` cùng ở trạng thái `FIRING (2)`.)*

**Thí nghiệm E không làm alert hạ tầng nào firing. Cách phát hiện sự cố này trong production:**  
Alert hạ tầng chỉ đo HTTP 5xx, latency và sống/chết của container, trong khi agent `v1` vẫn trả HTTP 200 rất nhanh nhưng **trả lời sai về mặt ngữ nghĩa**. Để phát hiện suy giảm chất lượng trong production cần:
1. Chạy **Eval Quality Gate tự động trong CI/CD** trước mỗi lần deploy (như `run_eval.py --baseline` chặn deploy `v1`).
2. Theo dõi các **metric chất lượng/domain** trên dashboard (ví dụ `agent_retrieval_total{result="hit"}` giảm đột ngột về 0 hoặc tỷ lệ feedback thumbs-down của người dùng tăng).
3. Chạy **online eval / LLM-as-judge** lấy mẫu ngẫu nhiên (vd 5–10% traffic thật) để cảnh báo khi điểm chất lượng giảm.

### 4.3 Debug bằng trace

Trace chậm nhất tìm được trong Jaeger ([screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)):

- `trace_id`: `d5e17d53e99c61e81d2def3a17a9cb59`
- Tổng thời gian: `1719.7 ms` (`1.7s` hiển thị trên Jaeger UI)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`1697.1 ms`, chiếm `98.7%` tổng thời gian request; trong khi `agent.retrieve_context` chỉ mất `18.7 ms`)
- Dòng log tương ứng (grep theo `trace_id` `d5e17d53e99c61e81d2def3a17a9cb59`):

```json
{"ts": "2026-11-26T08:26:16.877045+00:00", "level": "INFO", "service": "observable-agent", "instance": "b96628d8d397", "event": "llm_call", "trace_id": "d5e17d53e99c61e81d2def3a17a9cb59", "span_id": "5b1bbb3de77d4966", "request_id": "e70e99189523", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1697.1}
{"ts": "2026-11-26T08:26:16.878089+00:00", "level": "INFO", "service": "observable-agent", "instance": "b96628d8d397", "event": "http_request", "trace_id": "d5e17d53e99c61e81d2def3a17a9cb59", "span_id": "5b1bbb3de77d4966", "request_id": "e70e99189523", "method": "POST", "route": "/ask", "status": 200, "ms": 1719.7}
```

Trace lỗi (`503 Service Unavailable`) được liên kết qua `trace_id`: `0282ff8ca6d751129c4d4e8612a189c0` ([screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)), với event `exception`: `Upstream LLM error: 503 Service Unavailable (mock)`.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10/s, 2 phút)

*(Số liệu trích chính xác từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`, hàng `Aggregated` và `/ask`.)*

| Số instance | Scope | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `Aggregated` | 62.85 | 210 | 730 | 1800 | 82 / 7487 (1.10%) |
| 1 | `POST /ask` | 57.08 | 220 | 780 | 1800 | 82 / 6799 (1.21%) |
| 3 | `Aggregated` | 65.41 | 200 | 260 | 1700 | 79 / 7792 (1.01%) |
| 3 | `POST /ask` | 59.26 | 200 | 270 | 1700 | 79 / 7060 (1.12%) |

**Giải thích kết quả:**  
Khi scale từ `1` lên `3` instance (giới hạn `0.5` CPU mỗi container), **p95 của `/ask` giảm rất mạnh từ `780 ms` xuống `270 ms`** (`-65.4%`) và `GET /health` p95 giảm từ `220 ms` xuống `18 ms`, vì 3 replica gánh tải song song loại bỏ tình trạng nghẽn CPU và xếp hàng event loop ở mức 100 user đồng thời. Trong khi đó, RPS tổng chỉ tăng nhẹ (`62.85 → 65.41 req/s`) do `AgentUser` có `wait_time = between(0.5, 2)` giới hạn tốc độ sinh request của 100 user, và **`p99` vẫn ở mức `1700–1800 ms`** vì nút thắt lúc này nằm ở **latency của upstream LLM** (3% request chậm thêm 1500 ms là chi phí cố định từ phía LLM, scale thêm replica app không làm LLM trả lời nhanh hơn).

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Không bao giờ đánh giá hiệu năng bằng latency trung bình:** Cần đo `p95`/`p99` bằng load test chịu tải thực; `avg` dễ che giấu các ca chậm 1.7s ảnh hưởng trực tiếp tới trải nghiệm người dùng.
  2. **Chất lượng và chi phí phải đo song hành qua Eval + `cost / câu đúng`:** RAG (v2) tốn gấp đôi token nhưng giảm chi phí trên mỗi câu trả lời đúng hơn 11 lần và chất lượng cần được khóa bằng quality gate trong CI.
  3. **3 trụ cột Metrics – Traces – Logs gắn chặt với nhau:** Prometheus/Grafana phát hiện *khi nào* có vấn đề, Jaeger chỉ ra *span nào* gây chậm/lỗi, và `trace_id` trong JSON log giúp truy vết chi tiết bản ghi ứng dụng.
- **Metric / alert sẽ bổ sung nếu đưa agent lên production thật:**
  - Theo dõi **Quality / Retrieval Miss Rate** (`rate(agent_retrieval_total{result="miss"}[5m])`) và điểm đánh giá từ **online LLM-as-judge / user feedback** để phát hiện suy giảm chất lượng như thí nghiệm E.
  - Theo dõi **Redis latency / connection errors** và **Nginx 5xx / 504 gateway timeout** (vì 504 ở load balancer không tự hiện trong metric nội bộ của agent).
  - Bổ sung alert **Time-to-First-Token (TTFT)** nếu triển khai streaming response.
