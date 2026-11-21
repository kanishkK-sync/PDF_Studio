# pdf-studio

A free, local-first PDF toolkit with 15 tools. Run both services on your machine, or host the Next.js frontend on Vercel and the FastAPI backend on Render or Koyeb. In a hosted deployment, files leave the browser and are processed on the configured backend server.

## One-command local startup with Docker

Install Docker with Compose, then run from the repository root:

```bash
docker compose up --build
```

Open <http://localhost:3000>; the API health endpoint is <http://localhost:8000/api/health>. Compose builds the Python backend and starts the frontend development server using Node 24. The frontend installs locked dependencies with `npm ci`; no frontend production build is needed for this local workflow. First startup downloads dependencies and the backend image, including LibreOffice and fonts.

The published ports bind to localhost. Browser requests use `http://localhost:8000`, rather than the internal Docker service name. Source files are mounted into the frontend; its dependencies and Next.js cache use Docker volumes. Backend documents use temporary container storage, without a persistent document volume. Stop with `docker compose down`.

## Current status

The registry includes 15 tools. Files are processed on the configured backend (local by default), and results are deleted after download or expiry.

- **Compress PDF** (`/tools/compress-pdf`): choose a PDF, pick a level, upload, and download the smaller file. Text stays selectable and searchable, and links, bookmarks, form fields, annotations, page sizes and metadata are kept. The result is never larger than the original; if nothing can be saved, you get the original back marked "Already optimized".
  - **Light:** lossless. Cleans up the file structure and leaves images untouched.
  - **Balanced** (default): images above 170 DPI are resampled to 150 DPI.
  - **Strong:** images above 120 DPI are resampled to 100 DPI, so photos may lose detail.
- **PDF to JPG** (`/tools/pdf-to-jpg`): renders every page as a JPG image. One page gives a single `.jpg`; several pages give a `.zip` with `page-001.jpg`, `page-002.jpg` and so on. Pages are rendered one at a time on a white background.
  - **Low:** about 100 DPI.
  - **Medium** (default): about 150 DPI.
  - **High:** about 220 DPI, so the files are larger.
  - A PDF with more pages than `MAX_PDF_PAGES` is rejected. A single page that would be larger than `MAX_RENDER_PIXELS` is rendered at a lower DPI instead of failing.
- **JPG to PDF** (`/tools/jpg-to-pdf`): combines JPG and PNG images into one PDF, one page per image, in the order shown in the list. You can reorder and remove images before converting.
  - **Fit to image:** each page is as big as its picture.
  - **A4:** each picture is centred on an A4 page with a 10 mm margin, upright or sideways to match.
  - Plain RGB or grayscale pictures are embedded as they are. CMYK, palette, transparent and rotated pictures are converted first, and transparency is flattened onto white.
- **PDF to Word** (`/tools/pdf-to-word`): exports selectable text and images to a DOCX. Complex PDF layouts may need cleanup.
- **PDF to Excel** (`/tools/pdf-to-excel`): exports each detected table to its own sheet, or uses a text sheet when there are no tables. Scans need OCR, which is not included.
- **PDF to PowerPoint** (`/tools/pdf-to-powerpoint`): pictures mode preserves the appearance of each page; editable mode rebuilds text and images as slide objects with possible layout changes.
- **Edit PDF Text** (`/tools/edit-pdf`): finds an exact phrase in selectable text, removes matching occurrences and places replacement text in their page areas. Review long replacements for clipping.
- **Merge PDF** (`/tools/merge-pdf`): combines 2 to 20 PDFs in the selected order; move files with the arrow buttons.
- **Split PDF** (`/tools/split-pdf`): enter page ranges such as `1-3, 5, 8-` to extract one PDF or produce a ZIP with a separate PDF per range.
- **Word to PDF, PowerPoint to PDF, Excel to PDF** (`/tools/word-to-pdf`, `/tools/powerpoint-to-pdf`, `/tools/excel-to-pdf`): render text and basic tables or pictures with bundled Python libraries. Text remains searchable where possible. Advanced formatting, charts, formulas and animations may change or be omitted.
- **Redact PDF** (/tools/redact-pdf) removes matching searchable text, including matches across lines, and checks the saved output. Optional scrubbing also removes document metadata, annotations, forms, links and attachments. Text contained in pictures or drawn as outlines needs visual review.
- **PDF to AI Markdown** (/tools/pdf-to-markdown) extracts text, headings, lists and tables in inferred reading order. Preview or copy the Markdown, see an approximate token count, or download the UTF-8 file.
- **Visual & Structural PDF Diff** (`/tools/compare-pdf`) compares corresponding page numbers in two local PDFs, up to the first 25. Review cyan additions and magenta removals, inspect changed text, or download the PNG overlays and JSON and text reports together. A page’s similarity uses the lower of pixel agreement and normalized word-pair overlap. An added or removed page scores zero. The overall score averages the compared positions.
- **Homepage:** hero, a backend-status pill that checks `/api/health` every 10 seconds, a category filter, the tool grid, and a light/dark theme toggle (dark by default). The initial probe shows "Engine waking up..." after 2.5 seconds and waits up to 120 seconds for a cold backend. Subsequent probes time out after 3 seconds; offline checks retry every 3 seconds.

## Requirements

- Python 3.13
- Node.js 24 or later (npm comes with it)

## Run it

Use two terminals, one per server.

### Terminal 1: backend

Run everything from inside `backend/`.

Windows (PowerShell):

```powershell
cd backend
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

On Windows `cmd`, activate with `.venv\Scripts\activate.bat` instead.

macOS / Linux:

```bash
cd backend
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

The `.env` file is optional: the defaults match `.env.example`. Check the server at <http://localhost:8000/api/health>.

Run the tests and the linter (venv active, inside `backend/`):

```bash
python -m pytest
ruff check .
```

On Windows one test (the symlink test in `test_storage.py`) is skipped, because Windows does not let normal users create symlinks. That is expected.

A new terminal starts without the virtual environment. Activate it again (`.venv\Scripts\Activate.ps1`) before running `uvicorn`, `python -m pytest` or `ruff`.

### Terminal 2: frontend

Windows (PowerShell):

```powershell
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

macOS / Linux:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The `.env.local` file is optional: the app falls back to the same defaults.

Other commands, from `frontend/`:

```bash
npx tsc --noEmit
npm run lint
```

In Windows PowerShell 5.1, `&&` does not work as a command separator. Run these one after another, or join them with `;`.

### Open the app

Go to <http://localhost:3000>. Do not use `127.0.0.1`: the backend allows only the origin `http://localhost:3000`, so the status pill would show "offline" and uploads would fail.

## Environment variables

Backend (`backend/.env`, or real environment variables). Restart `uvicorn` after changing any of them.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_UPLOAD_MB` | `100` | Largest upload the backend accepts, in MB. For JPG to PDF it limits the total size of all images together. |
| `JOB_TTL_MINUTES` | `30` | Age after which the sweeper deletes a job. |
| `MAX_CONCURRENT_JOBS` | `1` | Compatibility setting. PyMuPDF jobs are serialized by one shared gate across all tools in each server process; increasing this value does not enable parallel PyMuPDF work. |
| `MAX_PDF_PAGES` | `300` | Page limit used across PDF operations and generated Office PDFs. Comparison separately covers up to the first 25 pages. |
| `MAX_IMAGES` | `50` | Most images accepted in one JPG to PDF job. |
| `MAX_MERGE_FILES` | `20` | Most PDFs accepted in one merge job. |
| `MAX_RENDER_PIXELS` | `30000000` | Most pixels rendered for one PDF page. A larger page is rendered at a lower DPI. |
| `STORAGE_DIR` | `backend/app/storage` | Where uploads and results are kept while a job lives. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | The single origin allowed by CORS. |
| `RATE_LIMIT_PER_MINUTE` | `30` | Accepted API requests per client IP in a sliding 60-second window. Must be a positive integer. Health checks and OPTIONS are exempt. Counters are in memory and reset on restart. |
| `PORT` | `8000` | Port used by the Docker startup command; use the hosting provider's supplied value where available. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` (Uvicorn default) | Trusted reverse-proxy IPs/networks for resolving client IPs. Configure for your deployment's ingress; see proxy guidance below. |
| `APP_VERSION` | `0.1.0` | Version reported by `/api/health`. |

Frontend (`frontend/.env.local`). Restart `npm run dev` after changing any of them, because `NEXT_PUBLIC_*` values are built into the browser bundle when the server starts.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the backend, without a trailing slash. |
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` | Public frontend origin for metadata, canonical URLs, sitemap URLs, and JSON-LD. |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | `100` | Size limit the upload forms check before sending. Keep it equal to the backend's `MAX_UPLOAD_MB`; the backend stays the authority. |
| `NEXT_PUBLIC_MAX_IMAGES` | `50` | Image limit the JPG to PDF form checks. Keep it equal to the backend's `MAX_IMAGES`. |

## Public split-hosting deployment

Use a stable HTTPS origin for each service, for example `https://pdf-studio.example` and `https://api.pdf-studio.example`. Browser uploads and downloads go directly to the backend; they are not proxied through Vercel functions. Do not put credentials in `NEXT_PUBLIC_*` variables; these values are public and embedded during the frontend deployment. Redeploy the frontend whenever they change.

### Backend on Render

1. Create a web service from this repository using the Docker runtime. Set the service root/build context to `backend` and the Dockerfile path relative to that root to `Dockerfile`.
2. Set `FRONTEND_ORIGIN` to the exact frontend origin, without a trailing slash or path. Set `RATE_LIMIT_PER_MINUTE=30`, `MAX_UPLOAD_MB=100`, `MAX_IMAGES=50`, and optionally the resource limits above. Let the service supply `PORT`; the Docker command reads it automatically.
3. Configure the health check path as `/api/health`. Run one instance. The image runs one Uvicorn worker as a non-root user, with writable ephemeral storage at `/app/storage`.
4. Deploy, then check `https://<backend-host>/api/health` and use that HTTPS origin as Vercel's `NEXT_PUBLIC_API_URL`.

### Backend on Koyeb

1. Create a web service from this repository using a Dockerfile build. Select `backend` as the work/build directory and its `Dockerfile`. The Docker build context must contain `requirements.txt` and `app/`.
2. Expose HTTP port `8000` and set `PORT=8000`, or make `PORT` match the port configured for the service. Set the same backend environment variables as for Render, including the exact frontend origin.
3. Configure an HTTP health check at `/api/health`, keep one instance, and deploy. Use the resulting HTTPS backend origin in the frontend environment.

### Frontend on Vercel

1. Import the repository, select the Next.js framework, and set the project root to `frontend`. Use Node.js 24 or a compatible newer version allowed by `package.json`, with the standard Next.js deployment settings.
2. Set `NEXT_PUBLIC_API_URL` to the backend's HTTPS origin and `NEXT_PUBLIC_SITE_URL` to the final public frontend origin. Set `NEXT_PUBLIC_MAX_UPLOAD_MB` and `NEXT_PUBLIC_MAX_IMAGES` equal to the backend values.
3. Deploy the frontend. Set the backend's `FRONTEND_ORIGIN` to that exact Vercel or custom-domain origin and redeploy/restart the backend. If the frontend URL changes, update both `FRONTEND_ORIGIN` and `NEXT_PUBLIC_SITE_URL` and redeploy the affected services. The single-origin CORS setting does not automatically allow Vercel preview URLs.
4. Visit a tool page and verify the health pill, an upload, and its download. Check `/sitemap.xml`, `/robots.txt`, and `/llms.txt` on the frontend origin; sitemap and canonical URLs should use the public frontend origin.

### Proxy IPs, rate limits, and storage

The limiter uses the ASGI client address supplied by Uvicorn. It never parses arbitrary `X-Forwarded-For` headers itself. Configure `FORWARDED_ALLOW_IPS` with your ingress proxy's trusted addresses/networks so users have separate budgets. If the proxy is untrusted, its address can become one shared budget for all visitors. Use `FORWARDED_ALLOW_IPS=*` only when the backend is reachable exclusively through a trusted ingress that sanitizes forwarded headers and direct access is blocked; otherwise clients can forge their IPs. Confirm these network conditions with the hosting provider before enabling wildcard trust.

After an IP uses its budget (30 by default) within 60 seconds, the next request returns HTTP 429 with `{"error":{"code":"RATE_LIMITED","message":"Too many requests. Please wait a moment and try again."}}` and a `Retry-After` header. All `/api/` routes except health checks and OPTIONS share the budget, including uploads, downloads, and deletes. Rejected requests do not extend the window. CORS exposes `Retry-After` to the configured frontend. Rate limiting is disabled automatically under pytest; dedicated limiter tests explicitly enable it.

Keep one backend process and one instance: job files and rate-limit counters are local. Multiple instances would require shared job storage and a shared rate limiter. Restarts, redeployments, and scale-to-zero discard pending results. No persistent document disk is required. Uploads are deleted after processing, outputs after download or expiry, and the sweeper runs every five minutes. This is zero long-term retention with temporary files, rather than browser-only or memory-only processing. Hosted processing takes place on the backend provider's server.

The Docker image includes LibreOffice and PDF/image system libraries. Current Office-to-PDF tools use the bundled Python renderers, so installing LibreOffice does not change their existing formatting limitations. Choose backend memory and upload limits appropriate to the documents you accept.

## API

| Method and path | What it does |
| --- | --- |
| `POST /api/compare-pdf` | Multipart PDFs `original` and `revised` share one upload-size limit. Returns a ZIP download job and the headers `X-Compared-Pages`, `X-Truncated`, `X-Pages-Changed`, `X-Total-Pages` and `X-Overall-Similarity`. Total pages is the longer document’s page count. |
| `POST /api/redact-pdf` | Multipart PDF `file`, comma- or newline-separated `terms`, comma-separated `presets` (emails, phones, ssn, cards, urls), and `scrub_metadata` (default true). Supply a term or preset. Returns a download job and the headers `X-Redacted-Count`, `X-Metadata-Scrubbed` and `X-Verified-Unrecoverable`. Verification checks the saved PDF’s extractable page text. |
| `POST /api/pdf-to-markdown` | Multipart PDF `file` and `include_page_markers` (default true). Returns Markdown for preview, a download job and the headers `X-Page-Count`, `X-Word-Count` and `X-Estimated-Tokens`. Image-only documents return HTTP 400 with `no_content`. |
| `GET /api/health` | Returns `{"status": "ok", "version": "..."}`. |
| `POST /api/compress` | Multipart form with `file` and `level` (`light`, `balanced` or `strong`). Returns JSON with `job_id`, `original_name`, `original_size`, `compressed_size`, `saved_bytes`, `saved_percent`, `already_optimized`, `level` and `download_url`. |
| `POST /api/pdf-to-jpg` | Multipart form with `file` and `quality` (`low`, `medium` or `high`). Returns JSON with `job_id`, `original_name`, `page_count`, `file_count`, `result_size`, `kind` (`jpg` or `zip`), `quality` and `download_url`. |
| `POST /api/jpg-to-pdf` | Multipart form with a repeated `files` field (the order sent is the page order) and `page_size` (`fit` or `a4`). Returns JSON with `job_id`, `page_count`, `total_input_size`, `result_size`, `page_size`, `download_name` and `download_url`. |
| `POST /api/pdf-to-word` | Multipart `file`; returns a DOCX job with page count and download URL. |
| `POST /api/pdf-to-excel` | Multipart `file`; returns an XLSX job with table and sheet counts, mode and download URL. |
| `POST /api/pdf-to-pptx` | Multipart `file` and `mode` (`pictures` or `editable`); returns a PPTX job with slide count and download URL. |
| `POST /api/edit-pdf` | Multipart PDF `file`, `find`, and `replace`; returns an edited PDF job with replacement count. |
| `POST /api/merge` | Multipart repeated PDF `files`, in desired order; returns a merged PDF job. |
| `POST /api/split` | Multipart PDF `file`, `ranges` (for example `1-3, 5, 8-`), and `mode` (`extract` or `separate`); returns a PDF or ZIP job. |
| `POST /api/word-to-pdf` | Multipart DOCX `file`; returns a PDF job. |
| `POST /api/powerpoint-to-pdf` | Multipart PPTX `file`; returns a PDF job. |
| `POST /api/excel-to-pdf` | Multipart XLSX `file`; returns a PDF job. |
| `GET /api/jobs/{job_id}/download` | Sends the result, then deletes the job. The file is a PDF, a JPG or a ZIP depending on the job, named `<name>-compressed.pdf`, `<name>.jpg`, `<name>-jpg.zip`, `<first image name>.pdf` or `images.pdf`. A second request, an unknown id or an expired id gives 404 `job_not_found`. |
| `DELETE /api/jobs/{job_id}` | Deletes a job. Always answers 204, even for unknown ids, and is safe to repeat. |

Errors from these routes look like `{"error": {"code": "...", "message": "..."}}`. Codes include `not_pdf`, `not_image`, `not_office`, `encrypted`, `corrupt`, `too_large`, `too_many_files`, `too_many_pages`, `page_too_large`, `invalid_level`, `invalid_quality`, `invalid_page_size`, `invalid_ranges`, `invalid_request`, `no_content`, `no_match`, `no_text`, `job_not_found`, `processing_failed`, and `internal_error`.

## How long files live

- The upload is deleted as soon as processing ends, whether it succeeded or failed.
- The result is deleted right after you download it.
- A sweeper runs every 5 minutes and deletes any job older than `JOB_TTL_MINUTES` (30 by default).
- All storage is emptied every time the backend starts. A `uvicorn --reload` restart therefore discards jobs that are in flight or waiting for download.

## Project layout

```text
pdf-studio/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app, CORS, routers, startup cleanup, sweeper
│   │   ├── core/              settings (read from .env), error system
│   │   ├── api/routes/        health, jobs and all conversion/editing routes
│   │   ├── schemas/           response models
│   │   ├── services/          conversion, editing, merge and split engines
│   │   ├── utils/             job storage, upload helpers, folder cleanup
│   │   └── storage/           uploads/ and outputs/ (contents are git-ignored)
│   ├── tests/                 backend tests
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/               layout, template, homepage, tools/[slug], globals.css
│   │   ├── components/        home/, layout/, providers/, tools/
│   │   ├── config/tools.ts    the tool registry
│   │   ├── lib/               API client, formatters, job hooks, limits, motion system, helpers
│   │   └── store/             UI state (active category)
│   ├── package.json
│   └── .env.example
├── docs/                      placeholder
└── scripts/                   placeholder
```

## Troubleshooting

- **The status pill says "Backend offline", or an upload says it can't reach the server.**
  - Check that `uvicorn` is running and that <http://localhost:8000/api/health> responds.
  - Check that you opened the site at `localhost:3000`, not `127.0.0.1`.
  - If you changed `NEXT_PUBLIC_API_URL`, restart `npm run dev`.
  - On the first check, a slow backend shows "Engine waking up..." after 2.5 seconds and has up to 120 seconds to respond. After that, detecting an outage can take about 13 seconds; offline probes retry every 3 seconds.
- **"This PDF is password-protected."** Encrypted PDFs are rejected by Compress PDF and PDF to JPG, including ones that open without a password but restrict editing. Remove the protection in the program that created the file, then try again.
- **A file is rejected as too large.** The limit is `MAX_UPLOAD_MB` on the backend (100 MB by default) and `NEXT_PUBLIC_MAX_UPLOAD_MB` in the browser. For JPG to PDF it applies to all images together. Raise both to the same value, restart the backend, and restart or redeploy the frontend. The browser check saves unnecessary uploads; backend limits remain authoritative.
- **"This PDF has too many pages."** PDF to JPG stops at `MAX_PDF_PAGES` pages (300 by default). Split the PDF into parts, or raise the limit in `backend/.env` and restart `uvicorn`.
- **JPG to PDF rejects an image.** Only JPG and PNG pictures are accepted, and the type is checked from the file's contents, not its name. A file renamed to `.jpg` that is not really a picture is refused. The message names which image in the list is the problem. Too many images need a higher `MAX_IMAGES` on the backend and `NEXT_PUBLIC_MAX_IMAGES` in the browser.
- **A result vanished.** Results are deleted after one download, after 30 minutes, and whenever the backend restarts.
- **`ModuleNotFoundError: No module named 'app'`** means you are not inside `backend/`. Run `uvicorn` and `python -m pytest` from that folder.
- **`No module named pytest`, or `ruff` is not recognized,** means the virtual environment is not active in this terminal. Run `.venv\Scripts\Activate.ps1` first; the prompt should start with `(.venv)`.
- **`ModuleNotFoundError: No module named 'fastapi'`** (or another package) means the virtual environment is not active, or `pip install -r requirements.txt` has not been run.
- **`pip install` fails while building a package** (for example `pymupdf`, `pikepdf` or `pillow`). The pinned versions were resolved on Python 3.13. Other Python versions, especially very new ones, may have no prebuilt wheels and try to compile from source. Recreate the venv with `py -3.13` (Windows) or `python3.13`.
- **PowerShell refuses to run `Activate.ps1`.** Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.
- **npm warns about the Node version.** `frontend/package.json` requires Node 24 or later.
