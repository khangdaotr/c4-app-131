# Hướng dẫn deploy CareerV (P-131) lên Railway

> Dành cho học viên tự deploy lại bản demo. Làm theo thứ tự, mỗi bước có lệnh để copy và cách kiểm tra.
> Thời gian: khoảng 30–40 phút, trong đó ~10 phút chờ build backend.
> Bản mẫu đang chạy: https://demo-prod-p-131.up.railway.app (frontend) · https://demo-prod-p-131-api.up.railway.app/docs (API).

---

## Mục lục

1. [Kiến trúc sẽ dựng](#1-kiến-trúc-sẽ-dựng)
2. [Chuẩn bị](#2-chuẩn-bị)
3. [Tạo tài khoản Railway và cài CLI](#3-tạo-tài-khoản-railway-và-cài-cli)
4. [Tạo project và 2 service](#4-tạo-project-và-2-service)
5. [Volume, vùng (region) và domain](#5-volume-vùng-region-và-domain)
6. [Biến môi trường](#6-biến-môi-trường)
7. [Deploy](#7-deploy)
8. [Kiểm tra sau deploy](#8-kiểm-tra-sau-deploy)
9. [Deploy lại khi sửa code](#9-deploy-lại-khi-sửa-code)
10. [Tự deploy khi push GitHub (tuỳ chọn)](#10-tự-deploy-khi-push-github-tuỳ-chọn)
11. [Xử lý lỗi thường gặp](#11-xử-lý-lỗi-thường-gặp)
12. [Chi phí và giới hạn gói Trial](#12-chi-phí-và-giới-hạn-gói-trial)
13. [Vì sao chọn Railway, và những gì repo đã sửa để deploy được](#13-vì-sao-chọn-railway-và-những-gì-repo-đã-sửa-để-deploy-được)

---

## 1. Kiến trúc sẽ dựng

```
Trình duyệt
   │  https://<ten-ban>.up.railway.app          (chỉ gọi MỘT origin)
   ▼
┌─────────────────────────┐   /api/v1/*  (Next.js rewrites, mạng nội bộ IPv6)   ┌──────────────────────────┐
│ service "frontend"      │ ───────────────────────────────────────────────────▶ │ service "backend"        │
│ Next.js 16 (Railpack)   │          http://backend.railway.internal:8000        │ FastAPI (Dockerfile)     │
│ port 3000               │                                                      │ gunicorn + uvicorn, 8000 │
└─────────────────────────┘                                                      │ volume /app/data         │
                                                                                 │  ├─ app.db (SQLite)      │
   https://<ten-ban>-api.up.railway.app/docs  (Swagger, chỉ để xem/test API)     │  ├─ uploads/ (CV)        │
                                                                                 │  └─ chroma*/ (vector)    │
                                                                                 └──────────────────────────┘
```

Điểm quan trọng:

- **Trình duyệt chỉ nói chuyện với frontend.** Mọi request `/api/v1/...` được Next.js chuyển tiếp (rewrite) sang backend
  qua mạng nội bộ của Railway. Cookie đăng nhập vì thế là first-party, không bị Safari/iOS chặn, và không có vòng Internet
  thừa giữa frontend và backend.
- **Dữ liệu nằm trên volume** của backend. Deploy lại không mất dữ liệu. Không cần Postgres cho bản demo 1–3 người dùng.
- Cả hai service **cùng một project, cùng một vùng** (Singapore) để độ trễ thấp cho người dùng ở Việt Nam.

## 2. Chuẩn bị

| Cần có | Ghi chú |
|---|---|
| Tài khoản GitHub | Để đăng nhập Railway. Không bắt buộc fork repo nếu deploy từ máy. |
| Mã nguồn repo trên máy | `git clone https://github.com/AI20K-Build-Phase-Cohort-4/P-131.git` (hoặc fork của bạn) |
| Terminal: macOS/Linux hoặc Windows (PowerShell / Git Bash) | Các lệnh dưới viết cho bash; PowerShell chỉ khác ở cách đặt biến. |
| (Khuyến nghị) API key LLM | DeepSeek (https://platform.deepseek.com) hoặc Groq (https://console.groq.com). Không có key thì app vẫn chạy nhưng các tính năng AI dùng quy tắc dự phòng. |
| Node ≥ 20 và Python 3.11 (tuỳ chọn) | Chỉ cần nếu muốn build thử ở máy trước khi deploy. |

Không cần Docker trên máy: Railway build image trên cloud.

## 3. Tạo tài khoản Railway và cài CLI

### 3.1 Tài khoản

1. Vào https://railway.com → **Continue with GitHub** → Authorize.
2. Lần đầu Railway hỏi chấp nhận **Terms of Service** và **Fair Use Policy** (2 bước, phải cuộn hết danh sách mới bấm được).
3. Gói mặc định là **Trial**: 5 USD tín dụng dùng trong 30 ngày, 1 GB RAM mỗi service, chỉ 1 vùng. Đủ cho bản demo (xem mục 12).

### 3.2 Cài Railway CLI

```bash
# macOS
brew install railway
# Windows (PowerShell)
scoop install railway        # hoặc: npm i -g @railway/cli
# Linux / cách chung
npm i -g @railway/cli

railway --version            # cần >= 5.x
```

### 3.3 Đăng nhập CLI

```bash
railway login                 # mở trình duyệt, bấm Authorize
# Nếu không mở được trình duyệt (SSH, WSL):
railway login --browserless   # in ra link + mã, mở link trên máy có trình duyệt
railway whoami                # phải in ra email của bạn
```

## 4. Tạo project và 2 service

Chạy mọi lệnh **từ thư mục gốc của repo** (nơi có `Dockerfile`, `requirements.txt`, thư mục `frontend/`).

```bash
cd P-131

# Tạo project (đổi tên tuỳ ý; tên này KHÔNG phải domain)
railway init --name careerv-demo

# Tạo 2 service rỗng
railway add --service backend
railway add --service frontend

# Kiểm tra
railway service list --json
```

Lệnh `railway init` đồng thời "link" thư mục hiện tại với project, nên các lệnh sau không cần truyền project id.

> Làm trên dashboard thay vì CLI: **New Project → Empty Project**, rồi **+ Create → Empty Service** hai lần, đổi tên
> thành `backend` và `frontend` (Settings → Service Name). Tên service được dùng làm hostname nội bộ (`backend.railway.internal`),
> vì thế **phải đặt đúng `backend`**, hoặc sửa lại biến `BACKEND_API_URL` ở mục 6 cho khớp.

## 5. Volume, vùng (region) và domain

### 5.1 Volume cho backend (SQLite, CV tải lên, vector store)

```bash
railway service link backend          # chọn backend làm service mặc định của thư mục
railway volume add -m /app/data       # mount tại /app/data
```

Dashboard: chuột phải vào service backend → **Attach Volume** → mount path `/app/data`.

### 5.2 Vùng Singapore cho cả hai service

Mặc định Railway đặt service ở Mỹ (`us-east4` / `iad`). Người dùng ở Việt Nam nên dùng Singapore.

```bash
railway service scale -s backend  asia-southeast1-eqsg3a=1 iad=0 us-east4-eqdc4a=0
railway service scale -s frontend asia-southeast1-eqsg3a=1 iad=0 us-east4-eqdc4a=0
```

Kết quả mong đợi: `{"regions":{"asia-southeast1-eqsg3a":{"numReplicas":1}, ...null}}`. Nếu còn vùng nào `numReplicas: 1`
khác Singapore, gói Trial sẽ **không deploy được** (lỗi "Your plan can only deploy to a single region"). Đặt vùng đó `=0`.

Dashboard: Service → Settings → **Regions** → chọn Singapore, bỏ vùng cũ.

### 5.3 Domain công khai

```bash
railway domain -s backend  -p 8000     # sinh domain kiểu backend-production-xxxx.up.railway.app
railway domain -s frontend -p 3000

# Đổi sang tên dễ nhớ (tên phải chưa ai dùng trên toàn Railway)
railway domain update backend-production-xxxx.up.railway.app  --domain ten-ban-api -s backend
railway domain update frontend-production-xxxx.up.railway.app --domain ten-ban     -s frontend

railway domain list -s frontend --json | grep domain
railway domain list -s backend  --json | grep domain
```

Ghi lại hai domain, ví dụ:

- Frontend: `https://ten-ban.up.railway.app`
- Backend: `https://ten-ban-api.up.railway.app`

Dashboard: Service → Settings → **Networking → Generate Domain**, nhập port (8000 backend, 3000 frontend), bấm icon bút để đổi tên.

## 6. Biến môi trường

### 6.1 Sinh các secret

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                  # AUTH_SECRET_KEY
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"        # PII_VAULT_KEY (Fernet)
```

Mật khẩu admin: tự chọn, **≥ 8 ký tự, có cả chữ và số** (yếu hơn thì backend bỏ qua, không tạo admin).

### 6.2 Backend

Thay `FE_URL`, email/mật khẩu admin và API key của bạn rồi chạy một lệnh:

```bash
FE_URL=https://ten-ban.up.railway.app

railway variable set -s backend --skip-deploys \
  APP_ENV=production PORT=8000 LOG_LEVEL=INFO WORKERS=1 \
  RAILWAY_RUN_UID=0 \
  "AUTH_SECRET_KEY=<dán chuỗi 1>" "PII_VAULT_KEY=<dán chuỗi 2>" PII_MASKING_ENABLED=true \
  LIGHTWEIGHT_NER=true "ASSISTANT_EMBEDDING_MODEL=" \
  "FRONTEND_URL=$FE_URL" "CORS_ORIGINS=$FE_URL" SESSION_COOKIE_SAMESITE=lax \
  DATABASE_URL=sqlite:////app/data/app.db UPLOAD_DIR=/app/data/uploads \
  CHROMA_PERSIST_DIR=/app/data/chroma ASSISTANT_CHROMA_PERSIST_DIR=/app/data/chroma_assistant \
  ADMIN_EMAIL=ban@example.com "ADMIN_PASSWORD=<mật khẩu admin>" \
  LLM_PROVIDER=deepseek MODEL_NAME=deepseek-chat LLM_THINKING_AGENT=disabled LLM_REASONING_EFFORT=low LLM_TIMEOUT_S=60

# API key nhập riêng qua stdin để không lưu vào lịch sử shell
echo "sk-xxxxxxxx" | railway variable set DEEPSEEK_API_KEY --stdin -s backend --skip-deploys
```

Ý nghĩa từng nhóm:

| Biến | Giá trị | Vì sao |
|---|---|---|
| `APP_ENV` | `production` | Không tạo tài khoản demo, bắt buộc `AUTH_SECRET_KEY` và bật PII masking, cookie `Secure`. |
| `PORT` | `8000` | Phải trùng port đã khai khi tạo domain. |
| `RAILWAY_RUN_UID` | `0` | Dockerfile chạy bằng user `appuser`; volume Railway mount thuộc root nên app không ghi được. Biến này bảo Railway chạy container bằng root. |
| `AUTH_SECRET_KEY` | chuỗi ≥ 32 byte | Ký cookie phiên. Thiếu thì backend không khởi động ở production. |
| `PII_VAULT_KEY` | khoá Fernet | Mã hoá thông tin cá nhân tách khỏi CV trước khi gửi LLM. |
| `LIGHTWEIGHT_NER` | `true` | Gói Trial 1 GB RAM: NER regex nhẹ thay `underthesea` (nạp torch ~500 MB). Lên Hobby thì bỏ. |
| `ASSISTANT_EMBEDDING_MODEL` | *(rỗng)* | Không nạp model E5 (torch + 470 MB) để tránh OOM. Trợ lý tra tài liệu bằng BM25 + embedding băm. Lên Hobby: xoá biến này và gọi `POST /api/v1/assistant/reindex`. |
| `FRONTEND_URL`, `CORS_ORIGINS` | URL frontend | Backend chỉ nhận request đổi dữ liệu (POST/PUT/DELETE) từ origin này. Sai URL → lỗi 403 `untrusted_origin` khi đăng nhập. |
| `DATABASE_URL`, `UPLOAD_DIR`, `CHROMA_*` | đường dẫn trong `/app/data` | Tất cả dữ liệu nằm trên volume. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | tài khoản quản trị đầu tiên | Production không có tài khoản demo; đây là cách duy nhất để có admin. Đã tồn tại thì không bị ghi đè. |
| `LLM_PROVIDER`, `MODEL_NAME`, `DEEPSEEK_API_KEY` | deepseek / deepseek-chat | Dùng Groq thì đặt `LLM_PROVIDER=groq`, `MODEL_NAME=llama-3.3-70b-versatile`, key vào `GROQ_API_KEY`. `LLM_THINKING_AGENT=disabled` giảm thời gian sinh câu hỏi từ ~22 s xuống ~3 s. |

Tham khảo đầy đủ: `.env.example` ở gốc repo và `src/config.py`.

### 6.3 Frontend

```bash
BE_URL=https://ten-ban-api.up.railway.app

railway variable set -s frontend --skip-deploys \
  "NEXT_PUBLIC_API_URL=$BE_URL" \
  BACKEND_API_URL=http://backend.railway.internal:8000 \
  NEXT_PUBLIC_LIVE_APIS=all PORT=3000 NEXT_PUBLIC_FEATURE_DEMO_TRY=false
```

| Biến | Vì sao |
|---|---|
| `NEXT_PUBLIC_API_URL` | Được nhúng vào bundle lúc build. Khi trình duyệt thấy URL này là địa chỉ ngoài (không phải localhost), `frontend/lib/config.ts` tự chuyển sang gọi đường dẫn tương đối `/api/v1/...`, tức đi qua proxy. |
| `BACKEND_API_URL` | Đích của rewrites trong `frontend/next.config.ts`. `backend.railway.internal` là hostname nội bộ, trùng tên service. Đổi tên service thì đổi biến này. |
| `NEXT_PUBLIC_LIVE_APIS=all` | Gọi backend thật cho mọi nhóm API. Để trống thì frontend chạy mock. |

Biến `NEXT_PUBLIC_*` chỉ có hiệu lực **sau khi build lại**. Đổi chúng thì phải deploy lại frontend.

## 7. Deploy

Mỗi service được đẩy từ một thư mục khác nhau:

```bash
# Backend: build theo Dockerfile ở gốc repo (~8–10 phút lần đầu: tải torch CPU + model embedding)
railway up --service backend --detach

# Frontend: chỉ upload thư mục frontend/ làm gốc, Railpack tự nhận Next.js (~3 phút)
railway up ./frontend --path-as-root --service frontend --detach
```

Theo dõi:

```bash
railway deployment list -s backend  --json | head -20      # status: BUILDING → DEPLOYING → SUCCESS
railway deployment list -s frontend --json | head -20
railway logs -s backend --build --lines 50                  # log build
railway logs -s backend --deployment --lines 100            # log chạy
```

Hoặc mở dashboard: `railway open`.

Lưu ý:

- `railway up` tôn trọng `.gitignore`, nên `.env`, `data/`, `node_modules/` không bị upload.
- Hai file `railway.json` (gốc và `frontend/`) khai healthcheck (`/health` cho backend với timeout 600 s, `/login` cho frontend)
  và lệnh start của frontend `npm run start -- -H ::`. Không xoá chúng.
- Backend trả `SUCCESS` sau khi `/health` trả 200. Sau đó app còn chạy nền ~30 s để nạp JD vector store và dựng chỉ mục tài
  liệu trợ lý; log sẽ in `JD vector store: 8 mục` và `Successfully indexed N chunks`.

## 8. Kiểm tra sau deploy

```bash
FE_URL=https://ten-ban.up.railway.app
BE_URL=https://ten-ban-api.up.railway.app

curl -s $BE_URL/health                        # {"status":"ok","env":"production","version":"1.0.0"}
curl -s -o /dev/null -w "%{http_code}\n" $FE_URL/login      # 200
curl -s -o /dev/null -w "%{http_code}\n" $BE_URL/docs       # 200 (Swagger)

# Đăng nhập admin qua proxy frontend (giống trình duyệt làm)
curl -s -c cookie.txt -H "Origin: $FE_URL" -H "Content-Type: application/json" \
  -d '{"email":"ban@example.com","password":"<mật khẩu admin>"}' $FE_URL/api/v1/auth/login
# {"role":"admin","profile":{...}}
curl -s -b cookie.txt $FE_URL/api/v1/me       # trả thông tin admin
```

Trên trình duyệt: mở `$FE_URL/login`, đăng nhập bằng admin → vào trang Quản trị. Tạo tài khoản sinh viên ở `$FE_URL/register`
rồi thử tải CV, phân tích, phỏng vấn, chat với trợ lý.

Xem tài nguyên:

```bash
railway metrics -s backend  --json      # RAM thường ~550 MB / 1024 MB khi rảnh
railway metrics -s frontend --json      # ~100 MB
```

## 9. Deploy lại khi sửa code

```bash
git pull                                                     # lấy code mới
railway up --service backend --detach                        # nếu sửa backend
railway up ./frontend --path-as-root --service frontend --detach   # nếu sửa frontend
```

Chỉ đổi biến môi trường (không `--skip-deploys`) thì Railway tự deploy lại service đó. Dữ liệu trên volume giữ nguyên.

Lệnh hữu ích khác:

```bash
railway service restart -s backend                 # khởi động lại, không build
railway service files list /app/data -s backend    # xem file trên volume
railway service files download /app/data/app.db ./backup.db -s backend   # sao lưu SQLite
railway down -s backend                            # gỡ deployment mới nhất (rollback nhanh)
```

## 10. Tự deploy khi push GitHub (tuỳ chọn)

Thay vì `railway up` từ máy, nối service với repo GitHub (fork của bạn):

```bash
railway service source connect --repo <github-user>/P-131 --branch main --service backend
railway service source connect --repo <github-user>/P-131 --branch main --service frontend
```

Lần đầu Railway yêu cầu cài **Railway GitHub App** vào tài khoản/tổ chức có repo (làm trên dashboard theo link CLI in ra).
Với **frontend** phải vào Settings → **Root Directory** = `frontend` (dashboard) vì repo là monorepo; backend giữ root `/`.
Từ đó mỗi lần push `main` Railway build lại. Có thể thêm Settings → **Watch Paths** (`frontend/**` cho frontend,
`src/**`, `requirements.txt`, `Dockerfile` cho backend) để không build thừa.

## 11. Xử lý lỗi thường gặp

| Triệu chứng | Nguyên nhân | Cách sửa |
|---|---|---|
| Deploy `FAILED` ngay, không có build log; `configErrors: "Your plan can only deploy to a single region"` | Service còn replica ở 2 vùng (Singapore + Mỹ) | `railway service scale -s <service> asia-southeast1-eqsg3a=1 iad=0 us-east4-eqdc4a=0`, deploy lại |
| `railway up` báo `prefix not found` | Truyền đường dẫn `.` cho backend | Bỏ tham số đường dẫn: `railway up --service backend` |
| Domain backend trả `502 Application failed to respond`, nhưng frontend proxy vẫn gọi được | App chỉ nghe IPv6 (uvicorn `--host ::`), public proxy vào bằng IPv4 | Dockerfile đã dùng gunicorn `-b [::]:$PORT` (dual-stack). Không đổi về uvicorn thuần. |
| Log: `Worker (pid:N) was sent SIGKILL! Perhaps out of memory?` lặp lại | Vượt 1 GB RAM khi nạp torch/E5/underthesea | Kiểm tra đã đặt `LIGHTWEIGHT_NER=true` và `ASSISTANT_EMBEDDING_MODEL=` (rỗng). Hoặc nâng gói Hobby. |
| Đăng nhập trả `403 {"code":"untrusted_origin"}` | `FRONTEND_URL`/`CORS_ORIGINS` không khớp domain frontend (thiếu `https://`, thừa `/`, hoặc domain cũ) | Sửa biến backend đúng domain, deploy lại |
| Đăng nhập xong vẫn bị đẩy về trang login | Trình duyệt gọi thẳng backend (cookie cross-site) | Kiểm tra `NEXT_PUBLIC_API_URL` là domain backend thật (không phải localhost) và frontend đã **build lại** sau khi đặt biến |
| Backend không tạo admin, log `ADMIN_PASSWORD quá yếu` | Mật khẩu < 8 ký tự hoặc thiếu chữ/số | Đặt lại `ADMIN_PASSWORD`, deploy lại |
| Backend crash lúc khởi động: `AUTH_SECRET_KEY must contain at least 32 bytes` | Thiếu hoặc quá ngắn | Sinh lại ở mục 6.1 |
| `PermissionError` khi ghi `/app/data` | Volume thuộc root, app chạy `appuser` | Đặt `RAILWAY_RUN_UID=0` |
| Chatbot trả lời "không tìm thấy tài liệu" | Chỉ mục chưa dựng (log không có `Successfully indexed`) | Đăng nhập admin, gọi `POST $FE_URL/api/v1/assistant/reindex`; hoặc restart backend |
| Tính năng AI trả kết quả đơn giản/giống nhau | Chưa có API key LLM | Đặt `DEEPSEEK_API_KEY` (hoặc Groq), deploy lại |
| `railway volume add` báo lỗi/panic | Chưa link service | `railway service link backend` rồi chạy lại |
| Build frontend lỗi TypeScript | Code lỗi, không phải Railway | Chạy `cd frontend && npm ci && npm run build` ở máy để xem lỗi |
| CLI in cảnh báo "Config as Code (railway.json) is deprecated" | Railway chuyển sang `.railway/railway.ts` từ 12/2026 | Chỉ là cảnh báo; `railway.json` vẫn hoạt động đến 01/12/2026 |

Xem log chi tiết: `railway logs -s backend --deployment --lines 200`, hoặc dashboard → service → Deployments → View Logs.

## 12. Chi phí và giới hạn gói Trial

| | Trial (mặc định) | Hobby (5 USD/tháng) |
|---|---|---|
| RAM mỗi service | 1 GB | tới 8 GB |
| vCPU | dùng chung | 8 vCPU |
| Tín dụng | 5 USD, hết hạn sau 30 ngày | 5 USD/tháng kèm gói |
| Vùng | 1 | 1 (Pro mới nhiều vùng) |
| Hết tín dụng | service **bị dừng** | tính thêm theo mức dùng |

Ước tính tiêu thụ của bản demo này: backend ~0.55 GB RAM, frontend ~0.1 GB, CPU rất thấp khi rảnh. Giá Railway khoảng
10 USD/GB-tháng RAM và 20 USD/vCPU-tháng, nên 5 USD tín dụng Trial đủ cho **khoảng 2 tuần chạy liên tục**. Để demo bền hơn:

- Nâng lên Hobby (cần thẻ), hoặc
- Bật **Settings → Sleep Application** cho cả hai service: service ngủ khi không có request, không tính RAM. Request đầu
  sau khi ngủ chậm ~5–10 s (backend) vì phải khởi động lại.

Khi đã lên Hobby, bật lại chất lượng đầy đủ:

```bash
railway variable delete LIGHTWEIGHT_NER -s backend --skip-deploys
railway variable delete ASSISTANT_EMBEDDING_MODEL -s backend
# sau khi deploy xong, đăng nhập admin và gọi:
curl -X POST -b cookie.txt -H "Origin: $FE_URL" $FE_URL/api/v1/assistant/reindex
```

## 13. Vì sao chọn Railway, và những gì repo đã sửa để deploy được

**Railway thay vì Vercel.** Backend cần torch, sentence-transformers, ChromaDB, onnxruntime (OCR): quá nặng và chạy quá lâu
cho Vercel Serverless. Vercel chỉ hợp với frontend. Nếu đặt frontend ở Vercel và backend ở Railway, mỗi request qua proxy đi
thêm một vòng Internet giữa hai nhà cung cấp; cùng một project Railway thì đi mạng nội bộ, và chỉ cần một bảng điều khiển,
một hoá đơn.

**Railway thay vì Render Free.** Render Free giới hạn 512 MB RAM, bản trước đã OOM nhiều lần; Railway Trial cho 1 GB và
Hobby cho 8 GB.

**Những thay đổi trong repo (đã có sẵn, học viên không cần làm lại):**

1. `.dockerignore`: bản cũ loại bỏ `docs/`, `eval/`, `*.md` khiến image thiếu `docs/user-guide` (tài liệu RAG của trợ lý) và
   `eval/router/artifacts/*.joblib` (bộ phân loại router). Nay chỉ giữ đúng hai thư mục đó.
2. `Dockerfile`: cài torch bản CPU trước `requirements.txt` (bản mặc định kéo CUDA ~3 GB); tải sẵn model embedding lúc
   build; chạy bằng `gunicorn -k uvicorn.workers.UvicornWorker -b [::]:$PORT` để nghe cả IPv4 (public proxy) lẫn IPv6
   (mạng nội bộ). `--timeout 300` vì phân tích CV có thể gọi LLM lâu.
3. `src/main.py`: ở production, nạp JD vector store và dựng chỉ mục trợ lý trong **thread nền** sau khi app lên (bản cũ bỏ
   qua hoàn toàn ở production, chatbot không có tài liệu). Thêm `logging.basicConfig` theo `LOG_LEVEL`.
4. `src/services/assistant/embedding.py`: `ASSISTANT_EMBEDDING_MODEL=""` nghĩa là không nạp E5, dùng embedding băm; dành
   cho máy 1 GB RAM.
5. `railway.json` ở gốc và `frontend/railway.json`: builder, healthcheck, lệnh start.
6. `requirements.txt`: thêm `gunicorn`.

Các file liên quan khi muốn đọc thêm: `src/config.py` (toàn bộ biến môi trường), `src/api/security.py` (kiểm tra origin),
`frontend/next.config.ts` (rewrites), `frontend/lib/config.ts` (chọn gọi proxy hay gọi thẳng).
