# pdf-studio

A free, local-first PDF toolkit. Everything runs on your own machine: files are processed here and never sent anywhere else.

## Current status

All 12 tools in the registry work end to end. Files are processed locally and results are deleted after download or expiry.

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
- **Homepage:** hero, a backend-status pill that checks `/api/health` every 10 seconds, a category filter, a grid of 12 tools, and a light/dark theme toggle (dark by default).

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
npm run build
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
| `MAX_PDF_PAGES` | `300` | Most pages converted in one PDF to JPG job. |
| `MAX_IMAGES` | `50` | Most images accepted in one JPG to PDF job. |
| `MAX_MERGE_FILES` | `20` | Most PDFs accepted in one merge job. |
| `MAX_RENDER_PIXELS` | `30000000` | Most pixels rendered for one PDF page. A larger page is rendered at a lower DPI. |
| `STORAGE_DIR` | `backend/app/storage` | Where uploads and results are kept while a job lives. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | The single origin allowed by CORS. |
| `APP_VERSION` | `0.1.0` | Version reported by `/api/health`. |

Frontend (`frontend/.env.local`). Restart `npm run dev` after changing any of them, because `NEXT_PUBLIC_*` values are built into the browser bundle when the server starts.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the backend, without a trailing slash. |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | `100` | Size limit the upload forms check before sending. Keep it equal to the backend's `MAX_UPLOAD_MB`; the backend stays the authority. |
| `NEXT_PUBLIC_MAX_IMAGES` | `50` | Image limit the JPG to PDF form checks. Keep it equal to the backend's `MAX_IMAGES`. |

## API

| Method and path | What it does |
| --- | --- |
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
  - The pill can take up to about 13 seconds to change after you start or stop the backend.
- **"This PDF is password-protected."** Encrypted PDFs are rejected by Compress PDF and PDF to JPG, including ones that open without a password but restrict editing. Remove the protection in the program that created the file, then try again.
- **A file is rejected as too large.** The limit is `MAX_UPLOAD_MB` on the backend (100 MB by default) and `NEXT_PUBLIC_MAX_UPLOAD_MB` in the browser. For JPG to PDF it applies to all images together. Raise both to the same value and restart both servers. The backend checks the limit only after the whole upload has arrived, so the browser check is what saves you from a long failed upload.
- **"This PDF has too many pages."** PDF to JPG stops at `MAX_PDF_PAGES` pages (300 by default). Split the PDF into parts, or raise the limit in `backend/.env` and restart `uvicorn`.
- **JPG to PDF rejects an image.** Only JPG and PNG pictures are accepted, and the type is checked from the file's contents, not its name. A file renamed to `.jpg` that is not really a picture is refused. The message names which image in the list is the problem. Too many images need a higher `MAX_IMAGES` on the backend and `NEXT_PUBLIC_MAX_IMAGES` in the browser.
- **A result vanished.** Results are deleted after one download, after 30 minutes, and whenever the backend restarts.
- **`ModuleNotFoundError: No module named 'app'`** means you are not inside `backend/`. Run `uvicorn` and `python -m pytest` from that folder.
- **`No module named pytest`, or `ruff` is not recognized,** means the virtual environment is not active in this terminal. Run `.venv\Scripts\Activate.ps1` first; the prompt should start with `(.venv)`.
- **`ModuleNotFoundError: No module named 'fastapi'`** (or another package) means the virtual environment is not active, or `pip install -r requirements.txt` has not been run.
- **`pip install` fails while building a package** (for example `pymupdf`, `pikepdf` or `pillow`). The pinned versions were resolved on Python 3.13. Other Python versions, especially very new ones, may have no prebuilt wheels and try to compile from source. Recreate the venv with `py -3.13` (Windows) or `python3.13`.
- **PowerShell refuses to run `Activate.ps1`.** Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.
- **npm warns about the Node version.** `frontend/package.json` requires Node 24 or later.
