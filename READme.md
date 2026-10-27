# pdf-studio

A free, local-first PDF toolkit. Everything runs on your own machine: files are processed here and never sent anywhere else.

## Current status

Phase 1 is done: **Compress PDF** works end to end. The other nine tools are still placeholders.

- **Compress PDF** (`/tools/compress-pdf`): choose a PDF, pick a level, upload, and download the smaller file. Text stays selectable and searchable, and links, bookmarks, form fields, annotations, page sizes and metadata are kept. The result is never larger than the original; if nothing can be saved, you get the original back marked "Already optimized".
  - **Light:** lossless. Cleans up the file structure and leaves images untouched.
  - **Balanced** (default): images above 170 DPI are resampled to 150 DPI.
  - **Strong:** images above 120 DPI are resampled to 100 DPI, so photos may lose detail.
- **Other tools:** each has a placeholder page at `/tools/<slug>` that says "Coming soon". An unknown slug shows a "Tool not found" page.
- **Homepage:** hero, a backend-status pill that checks `/api/health` every 10 seconds, a category filter, a grid of 10 tools, and a light/dark theme toggle (dark by default).
- **Not built yet:** inline text editing and the conversions between PDF and Word, PowerPoint, Excel and JPG.

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
npm run build
```

In Windows PowerShell 5.1, `&&` does not work as a command separator. Run these one after another, or join them with `;`.

### Open the app

Go to <http://localhost:3000>. Do not use `127.0.0.1`: the backend allows only the origin `http://localhost:3000`, so the status pill would show "offline" and uploads would fail.

## Environment variables

Backend (`backend/.env`, or real environment variables). Restart `uvicorn` after changing any of them.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_UPLOAD_MB` | `100` | Largest upload the backend accepts, in MB. |
| `JOB_TTL_MINUTES` | `30` | Age after which the sweeper deletes a job. |
| `MAX_CONCURRENT_JOBS` | `2` | How many PDFs are compressed at the same time. Extra jobs wait. |
| `STORAGE_DIR` | `backend/app/storage` | Where uploads and results are kept while a job lives. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | The single origin allowed by CORS. |
| `APP_VERSION` | `0.1.0` | Version reported by `/api/health`. |

Frontend (`frontend/.env.local`). Restart `npm run dev` after changing any of them, because `NEXT_PUBLIC_*` values are built into the browser bundle when the server starts.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the backend, without a trailing slash. |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | `100` | Size limit the upload form checks before sending. Keep it equal to the backend's `MAX_UPLOAD_MB`; the backend stays the authority. |

## API

| Method and path | What it does |
| --- | --- |
| `GET /api/health` | Returns `{"status": "ok", "version": "..."}`. |
| `POST /api/compress` | Multipart form with `file` and `level` (`light`, `balanced` or `strong`). Returns JSON with `job_id`, `original_name`, `original_size`, `compressed_size`, `saved_bytes`, `saved_percent`, `already_optimized`, `level` and `download_url`. |
| `GET /api/jobs/{job_id}/download` | Sends the result as `<name>-compressed.pdf`, then deletes the job. A second request, an unknown id or an expired id gives 404 `job_not_found`. |
| `DELETE /api/jobs/{job_id}` | Deletes a job. Always answers 204, even for unknown ids, and is safe to repeat. |

Errors from these routes look like `{"error": {"code": "...", "message": "..."}}`. Codes: `not_pdf`, `encrypted`, `corrupt`, `too_large`, `invalid_level`, `invalid_request`, `job_not_found`, `processing_failed`, `internal_error`.

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
│   │   ├── api/routes/        health, compress, jobs
│   │   ├── schemas/           response models
│   │   ├── services/          compression engine
│   │   ├── utils/             job storage, upload helpers
│   │   └── storage/           uploads/ and outputs/ (contents are git-ignored)
│   ├── tests/                 backend tests
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/               layout, template, homepage, tools/[slug], globals.css
│   │   ├── components/        home/, layout/, providers/, tools/
│   │   ├── config/tools.ts    the tool registry
│   │   ├── lib/               API client, formatters, job hook, motion system, helpers
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
  - The pill can take up to about 13 seconds to change after you start or stop the backend.
- **"Password-protected PDFs can't be compressed."** Encrypted PDFs are rejected, including ones that open without a password but restrict editing. Remove the protection in the program that created the file, then try again.
- **The file is rejected as too large.** The limit is `MAX_UPLOAD_MB` on the backend (100 MB by default) and `NEXT_PUBLIC_MAX_UPLOAD_MB` in the browser. Raise both to the same value and restart both servers. The backend checks the limit only after the whole file has arrived, so the browser check is what saves you from a long failed upload.
- **A result vanished.** Results are deleted after one download, after 30 minutes, and whenever the backend restarts.
- **`ModuleNotFoundError: No module named 'app'`** means you are not inside `backend/`. Run `uvicorn` and `python -m pytest` from that folder.
- **`ModuleNotFoundError: No module named 'fastapi'`** (or another package) means the virtual environment is not active, or `pip install -r requirements.txt` has not been run.
- **`pip install` fails while building a package** (for example `pymupdf`, `pikepdf` or `pillow`). The pinned versions were resolved on Python 3.13. Other Python versions, especially very new ones, may have no prebuilt wheels and try to compile from source. Recreate the venv with `py -3.13` (Windows) or `python3.13`.
- **PowerShell refuses to run `Activate.ps1`.** Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.
- **npm warns about the Node version.** `frontend/package.json` requires Node 24 or later.