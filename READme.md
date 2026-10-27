# scripts

Placeholder for helper scripts.

This folder is intentionally empty for now. Possible future contents,
once the matching need exists:

- Dev helpers (for example, starting both servers with one command)
- Maintenance tasks (for example, clearing the backend storage folders)

Nothing here is required to run the project. See the root `README.md` for
setup and run commands.

# pdf-studio

A free, local-first PDF toolkit. Everything runs on your own machine.

This is an early stage: the project scaffold plus a visual shell for the homepage. There is no PDF processing yet.

## Current status

- **Backend:** one endpoint, `GET /api/health`, which returns `{"status": "ok", "version": "0.1.0"}`. The version comes from `APP_VERSION`. CORS allows only `http://localhost:3000`.
- **Frontend:** a homepage with a hero, a backend-status pill that checks `/api/health` every 10 seconds, a category filter, a grid of 10 tools, and a light/dark theme toggle (dark by default).
- **Tool pages:** each tool has a placeholder page at `/tools/<slug>` that says "Coming soon". An unknown slug shows a "Tool not found" page.
- **Not built yet:** file upload and any PDF processing.

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

Run the tests (venv active, inside `backend/`):

```bash
python -m pytest
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

The `.env.local` file is optional: the app falls back to the same URL, `http://localhost:8000`.

Other commands, from `frontend/`:

```bash
npm run lint
npm run build
```

### Open the app

Go to <http://localhost:3000>. Do not use `127.0.0.1`: the backend allows only the origin `http://localhost:3000`, so the status pill would show "offline".

### After changing env values

- **Frontend:** restart `npm run dev`. `NEXT_PUBLIC_*` values are built into the browser bundle when the server starts.
- **Backend:** restart `uvicorn`. Settings are read once at startup.

## Project layout

```text
pdf-studio/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app, CORS, router
│   │   ├── core/              settings (read from .env)
│   │   ├── api/routes/        health route
│   │   ├── schemas/           response models
│   │   ├── services/          empty for now
│   │   ├── utils/             empty for now
│   │   └── storage/           uploads/ and outputs/ (contents are git-ignored)
│   ├── tests/                 health tests
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/               layout, template, homepage, tools/[slug], globals.css
│   │   ├── components/        home/, layout/, providers/, tools/
│   │   ├── config/tools.ts    the tool registry
│   │   ├── lib/               motion system, helpers, hooks
│   │   └── store/             UI state (active category)
│   ├── package.json
│   └── .env.example
├── docs/                      placeholder
└── scripts/                   placeholder
```

## Troubleshooting

- **The status pill says "Backend offline".**
  - Check that `uvicorn` is running and that <http://localhost:8000/api/health> responds.
  - Check that you opened the site at `localhost:3000`, not `127.0.0.1`.
  - If you changed `NEXT_PUBLIC_API_URL`, restart `npm run dev`.
  - The pill can take up to about 13 seconds to change after you start or stop the backend.
- **`ModuleNotFoundError: No module named 'app'`** means you are not inside `backend/`. Run `uvicorn` and `python -m pytest` from that folder.
- **`ModuleNotFoundError: No module named 'fastapi'`** (or another package) means the virtual environment is not active, or `pip install -r requirements.txt` has not been run.
- **`pip install` fails while building a package** (for example `pymupdf`, `pikepdf` or `pillow`). The pinned versions were resolved on Python 3.13. Other Python versions, especially very new ones, may have no prebuilt wheels and try to compile from source. Recreate the venv with `py -3.13` (Windows) or `python3.13`.
- **PowerShell refuses to run `Activate.ps1`.** Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.
- **npm warns about the Node version.** `frontend/package.json` requires Node 24 or later.