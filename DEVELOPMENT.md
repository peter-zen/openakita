# OpenAkita Development Guide

This document describes a practical development workflow for customizing OpenAkita with:

- WSL for Python backend, tools, MCP, and most frontend work
- Windows for Tauri desktop shell development, native testing, and packaging

This is the recommended split if your main development environment is Linux-like, but your target desktop app is Windows.

## Recommended Workflow

Use the environments for what they are best at:

- WSL:
  - Python development
  - OpenAkita backend and MCP/tool logic
  - Fast iteration with `openakita serve --dev`
  - Most React frontend work via web mode
- Windows:
  - Tauri desktop shell
  - Rust toolchain
  - WebView2-backed desktop testing
  - Installer and `.exe` packaging

Why this split:

- The backend is Python-first and runs well inside WSL.
- The desktop app is Tauri 2.x and depends on the native Windows toolchain for the most reliable build and packaging flow.
- The desktop app already supports connecting to an externally running OpenAkita service in remote mode.

## Architecture Summary

Relevant parts of the repo:

- `src/openakita/`: Python backend
- `apps/setup-center/`: React + Vite frontend and Tauri desktop app
- `apps/setup-center/src-tauri/`: Rust/Tauri shell

Important runtime defaults:

- Backend HTTP API default port: `18900`
- Backend default bind host: `127.0.0.1`
- Desktop app remote mode expects an OpenAkita service endpoint such as `http://127.0.0.1:18900`

## WSL Setup

Clone and develop inside the WSL filesystem, not under `/mnt/c`, for better Python and filesystem performance.

```bash
git clone git@github.com:peter-zen/openakita.git
cd openakita

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

If you need optional IM or browser-related extras, install a broader extra set as needed.

## Backend Development in WSL

For day-to-day backend development:

```bash
source .venv/bin/activate
API_HOST=0.0.0.0 API_PORT=18900 openakita serve --dev
```

Notes:

- `--dev` enables Python file watching and automatic restart.
- Use `API_HOST=0.0.0.0` instead of the default `127.0.0.1` so Windows can reliably reach the WSL service.
- Keep port `18900` unless you have a concrete reason to change it. The desktop app and web dev flow assume this by default.

Useful commands:

```bash
openakita serve
openakita serve --dev
openakita
pytest
ruff check src/
ruff format src/
mypy src/openakita/
```

## Frontend Development in WSL

Most UI work does not require Tauri on every edit. Use web mode first:

```bash
cd apps/setup-center
npm install
npm run dev:web
```

This gives you a Vite dev server and proxies API traffic to the backend at `http://127.0.0.1:18900`.

Recommended usage:

- Change React/TypeScript/CSS in WSL
- Keep `openakita serve --dev` running in another WSL terminal
- Use web mode for fast UI iteration
- Move to Windows Tauri only when you need native desktop behavior

## Windows Setup for Tauri

Install these on Windows:

- Rust via `rustup`
- Node.js and npm
- Visual Studio C++ Build Tools
- Microsoft WebView2 Runtime

Then work with `apps/setup-center/` from a normal Windows path.

## Important Path Recommendation

Do not make `\\\\wsl$\\...` your primary Windows Tauri build path.

It may work in some setups, but Windows-side `npm`, `cargo`, `cmd`, and installer tooling are less reliable on UNC paths. Use a normal Windows filesystem path for native desktop work when possible.

Recommended options:

1. Keep your main development repo in WSL.
2. Create a Windows-side clone or `git worktree` for Tauri testing and packaging.

Example approach:

- WSL main repo:
  - `/home/<you>/openakita`
- Windows Tauri worktree or clone:
  - `C:\dev\openakita-win`

If you prefer a single logical repo history, a separate Windows `git worktree` is a good compromise.

## Tauri Development on Windows

From the Windows-side repo or worktree:

```powershell
cd apps\setup-center
npm install
npm run tauri dev
```

For packaging:

```powershell
cd apps\setup-center
npm run tauri build
```

## Runtime Integration

Recommended development loop:

1. In WSL, run:

```bash
API_HOST=0.0.0.0 API_PORT=18900 openakita serve --dev
```

2. In Windows, start the desktop app with:

```powershell
cd apps\setup-center
npm run tauri dev
```

3. In the desktop app:

- Click `连接服务` / `Connect Service`
- Enter `127.0.0.1:18900`

Why `127.0.0.1`:

- Current desktop/Tauri configuration explicitly allows `localhost` and `127.0.0.1`
- This is the path the app already expects by default
- On modern WSL2, Windows-to-WSL localhost forwarding usually makes this work directly

## Do Not Point the Desktop App at a Separate MCP URL

The desktop app connects to the OpenAkita backend service, not directly to an isolated MCP endpoint.

That means the desktop app should target:

- `http://127.0.0.1:18900`

Not:

- a standalone MCP server URL as the main app base URL

MCP servers are managed behind the OpenAkita service.

## Recommended Daily Development Flow

For backend-heavy work:

1. Edit Python in WSL.
2. Run `openakita serve --dev` in WSL.
3. Connect the Windows desktop app to `127.0.0.1:18900`.
4. Test changes immediately without rebuilding Python.

For frontend-heavy work:

1. Edit `apps/setup-center/` in WSL.
2. Run `npm run dev:web`.
3. Keep the backend running in WSL.
4. Only switch to `npm run tauri dev` on Windows when you need desktop-specific validation.

For release-like desktop testing:

1. Move to the Windows-side repo/worktree.
2. Run `npm run tauri dev`.
3. Run `npm run tauri build`.
4. Validate the packaged desktop app on Windows.

## Suggested Repo Strategy

If you want clean long-term customization, use this structure:

- `origin`: your fork
- `upstream`: official OpenAkita repo

Typical sync flow:

```bash
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

If you already switched remotes, this matches the intended setup.

## Troubleshooting

### Windows desktop app cannot connect to `127.0.0.1:18900`

Check:

- WSL backend is actually running
- You started it with `API_HOST=0.0.0.0`
- Port `18900` is not occupied by another process
- Windows can reach WSL localhost forwarding in your current WSL version

Quick checks:

```bash
# In WSL
curl http://127.0.0.1:18900/api/health
```

```powershell
# In Windows PowerShell
curl http://127.0.0.1:18900/api/health
```

### Web mode works, Tauri build fails

Usually this is a Windows toolchain issue, not a React issue. Re-check:

- `rustup` installed correctly
- MSVC build tools installed
- WebView2 runtime available
- You are building from a normal Windows path, not relying on `\\\\wsl$\\...`

### You changed frontend code but desktop app still looks stale

If you are using web mode, restart the Vite dev server if needed.

If you are using Tauri packaging, rebuild:

```powershell
cd apps\setup-center
npm run tauri build
```

## Recommended Default for This Repo

If you are starting from scratch and want the least painful setup:

- Main development repo: WSL filesystem
- Backend runtime: WSL
- Fast UI iteration: WSL web mode
- Native desktop validation and packaging: Windows-side Tauri build

That gives you:

- fast Python iteration
- stable desktop packaging
- a clean split between backend customization and Windows-native desktop concerns

## Current Setup Execution Plan

This is the current execution plan for bringing the repo into a usable dual-environment
development state.

### Target State

- WSL is the primary development environment
- Windows keeps a separate local repo copy for Tauri work
- The backend runs in WSL on `http://127.0.0.1:18900`
- The Windows desktop app uses remote mode and connects to the WSL backend
- Daily development uses:
  - WSL for Python, CLI, `openakita serve --dev`, and `npm run dev:web`
  - Windows for `npm run tauri dev`

### Step 1: Record the Baseline

Before changing anything, verify:

- Python is available in WSL and is version `3.11+`
- Node.js and npm are available in WSL
- `.venv` exists or will be created in the repo root
- `apps/setup-center/node_modules` exists or will be installed
- Windows Tauri work will use a normal Windows filesystem path, not `\\\\wsl$\\...`

### Step 2: WSL Implementation

In the WSL repo:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
openakita --help
API_HOST=0.0.0.0 API_PORT=18900 openakita serve --dev
```

Then for frontend web iteration:

```bash
cd apps/setup-center
npm install
npm run dev:web
```

Expected result:

- CLI is available from the repo venv
- backend dev server runs on port `18900`
- Vite web dev server starts successfully

### Step 3: Windows Implementation

In a Windows-local clone or worktree such as `C:\dev\openakita-win`:

- Install:
  - Rust via `rustup`
  - Node.js and npm
  - Visual Studio C++ Build Tools
  - Microsoft WebView2 Runtime
- Then run:

```powershell
cd apps\setup-center
npm install
npm run tauri dev
```

Expected result:

- Tauri dev app starts from a Windows-local path
- the app can connect to `127.0.0.1:18900` in remote mode

### Step 4: Acceptance Checks

The setup is considered usable only when all of the following are true:

- WSL:
  - `.venv` is present and usable
  - `pip install -e ".[dev]"` completes
  - `openakita --help` works
  - `openakita serve --dev` starts successfully
  - `npm install` completes in `apps/setup-center`
  - `npm run dev:web` starts successfully
- Windows:
  - Windows-local Tauri repo is ready
  - `npm run tauri dev` launches the desktop app
  - the desktop app connects to `127.0.0.1:18900`

### Step 5: Scope for This Round

This round does not require:

- Windows-local Python backend setup
- Tauri packaging via `npm run tauri build`
- IM channel setup
- Playwright/browser automation extras
- release packaging validation

## Daily Startup Manual

This section is the practical runbook for starting OpenAkita again after a
shutdown or reboot.

### Quick Cheat Sheet

Use this as the shortest daily checklist.

#### Option A: WSL backend + web frontend

Terminal 1:

```bash
cd /home/zengping/code/openakita
. .venv/bin/activate
API_HOST=0.0.0.0 API_PORT=18900 openakita serve --dev
```

Terminal 2:

```bash
cd /home/zengping/code/openakita/apps/setup-center
npm run dev:web
```

Open:

```text
http://127.0.0.1:5173/web/#/chat
```

Quick check:

```bash
curl http://127.0.0.1:18900/api/health
curl http://127.0.0.1:5173/api/health
```

#### Option B: WSL backend + Windows desktop

WSL terminal:

```bash
cd /home/zengping/code/openakita
. .venv/bin/activate
API_HOST=0.0.0.0 API_PORT=18900 openakita serve --dev
```

Windows terminal:

```powershell
cd C:\dev\openakita-win\apps\setup-center
npm run tauri dev
```

Desktop backend address:

```text
127.0.0.1:18900
```

Quick check in Windows:

```powershell
curl http://127.0.0.1:18900/api/health
```

#### Stop

In each running terminal:

```text
Ctrl+C
```

#### Important

- `npm run dev:web` starts the frontend only.
- `openakita serve --dev` starts the backend only.
- New chat conversations reset model selection back to `auto`.
- Python backend changes currently require a manual backend restart.

### Repo Layout Used By This Setup

- WSL main repo:
  - `/home/zengping/code/openakita`
- Windows Tauri repo:
  - `C:\dev\openakita-win`

Important:

- The WSL repo and the Windows repo are separate working copies.
- If you changed code only in WSL, those changes do not automatically appear in
  the Windows repo.
- For Python/backend work, always treat the WSL repo as the source of truth.
- For Windows Tauri verification, make sure the Windows repo contains the code
  version you want to test.

## Daily Startup Option A: WSL Backend + Web Frontend

Use this for most daily development.

### Terminal 1: Start the backend in WSL

```bash
cd /home/zengping/code/openakita
. .venv/bin/activate
API_HOST=0.0.0.0 API_PORT=18900 openakita serve --dev
```

Expected result:

- backend starts on `http://127.0.0.1:18900`
- `GET /api/health` returns status `ok`

Quick check:

```bash
curl http://127.0.0.1:18900/api/health
```

### Terminal 2: Start the web frontend in WSL

```bash
cd /home/zengping/code/openakita/apps/setup-center
npm run dev:web
```

Expected result:

- Vite starts on `http://127.0.0.1:5173/web/`
- `/api/*` requests are proxied to `127.0.0.1:18900`

Open in browser:

```text
http://127.0.0.1:5173/web/#/chat
```

### Web mode notes

- `npm run dev:web` starts the frontend only.
- It does not start the Python backend for you.
- If the chat page shows backend not running, first check whether `openakita serve --dev`
  is actually running in WSL.

## Daily Startup Option B: WSL Backend + Windows Desktop (Tauri)

Use this when you need desktop-shell behavior.

### Step 1: Start the backend in WSL

```bash
cd /home/zengping/code/openakita
. .venv/bin/activate
API_HOST=0.0.0.0 API_PORT=18900 openakita serve --dev
```

Quick checks:

```bash
curl http://127.0.0.1:18900/api/health
```

In Windows PowerShell:

```powershell
curl http://127.0.0.1:18900/api/health
```

### Step 2: Start the Windows desktop app

In Windows PowerShell or CMD:

```powershell
cd C:\dev\openakita-win\apps\setup-center
npm run tauri dev
```

Then in the desktop app:

- use `127.0.0.1:18900` as the backend address

### Windows desktop notes

- Windows localhost forwarding to WSL has been enabled through `.wslconfig`
- If Windows cannot reach `127.0.0.1:18900`, re-check that the WSL backend is
  actually running before debugging the desktop app

## How To Stop Services

### Stop backend

In the WSL backend terminal:

```bash
Ctrl+C
```

### Stop web frontend

In the WSL Vite terminal:

```bash
Ctrl+C
```

### Stop Windows Tauri dev app

In the Windows terminal running `npm run tauri dev`:

```powershell
Ctrl+C
```

Then close the desktop window if it is still open.

## Quick Verification Checklist

After startup, verify in this order:

1. WSL backend:

```bash
curl http://127.0.0.1:18900/api/health
```

2. Web frontend (if using web mode):

```bash
curl http://127.0.0.1:5173/api/health
```

3. Windows desktop connectivity (if using Tauri):

```powershell
curl http://127.0.0.1:18900/api/health
```

If all three pass, the environment is ready.

## Important Known Behavior

- `openakita serve --dev` currently prints that `watchfiles` is not installed.
- That means Python backend code changes do not auto-reload right now.
- After changing Python backend code, restart the backend manually.

## Most Common Failure Cases

### Web page says backend is not running

Usually one of these:

- `openakita serve --dev` is not running in WSL
- `npm run dev:web` is not running
- the browser tab is stale and needs refresh after backend restart

### Windows desktop cannot connect

Check:

- WSL backend is running
- Windows can access `http://127.0.0.1:18900/api/health`
- you are launching Tauri from `C:\dev\openakita-win`, not from `\\wsl$`

### Python/backend changes do not seem to apply

Restart the backend:

```bash
cd /home/zengping/code/openakita
. .venv/bin/activate
API_HOST=0.0.0.0 API_PORT=18900 openakita serve --dev
```

### Windows desktop shows old frontend behavior

Restart the Windows Tauri dev process from:

```powershell
cd C:\dev\openakita-win\apps\setup-center
npm run tauri dev
```
