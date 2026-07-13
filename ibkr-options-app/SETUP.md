# Setting up ibkr-options-app on a new machine

This app is a FastAPI backend + React frontend that trades and analyzes
options against a live IBKR TWS/Gateway connection. Everything is already
in this repo on GitHub -- setting up on another laptop is: clone, install
deps, configure two `.env` files, start TWS, run both dev servers.

## Prerequisites

- **Git**
- **Python 3.11+** as a full standalone install (Anaconda, python.org, or
  pyenv -- anything except a bare macOS system Python). Confirm with
  `python3 --version`.
- **Node.js 18+** with npm.
- **Interactive Brokers TWS or IB Gateway**, installed and logged into the
  account you want this app to trade/analyze against.
- **(Optional)** An [Unusual Whales](https://unusualwhales.com/) API key --
  only needed for the "Unusual Whales" page. Every other page works
  without it.

## ⚠️ Critical gotcha: uvicorn/uvloop versions

`backend/requirements.txt` pins `uvicorn==0.35.0` and `uvloop==0.21.0`
exactly, not as a loose `>=` range. Newer versions (observed: uvicorn
0.51.0 / uvloop 0.22.1) have a real incompatibility with `ib_insync`'s
socket handling -- every `ib.connectAsync()` call fails with
`RuntimeError: Task ... attached to a different loop`, even though the
identical code works fine outside uvicorn. This was root-caused by
bisecting package versions during development. Don't let anything upgrade
past these pins without re-testing a live TWS connection first.

## 1. Clone

```bash
git clone https://github.com/biskumar/options-report.git
cd options-report
```

## 2. Configure TWS / IB Gateway

In TWS: **File > Global Configuration > API > Settings**
- Check "Enable ActiveX and Socket Clients"
- Uncheck "Read-Only API" (required to place orders; leave checked if you
  only want read-only use)
- Add `127.0.0.1` to "Trusted IPs"
- Note the socket port: **7496** = live TWS, **7497** = paper TWS,
  **4001**/**4002** = live/paper IB Gateway

Leave TWS running and logged in whenever you use the app.

## 3. Backend setup

```bash
cd ibkr-options-app/backend
pip install -r requirements.txt
cp .env.example .env
```

Edit `ibkr-options-app/backend/.env`:

```
IB_HOST=127.0.0.1
IB_PORT=7496              # match whatever you configured in step 2
IB_CLIENT_ID=101           # any integer unused by another API client
IB_ACCOUNT=
ALLOW_ORDERS=false         # keep false until you're ready to place real orders
CORS_ORIGINS=["http://localhost:5175"]
TELEGRAM_TOKEN=            # optional, for alert notifications
TELEGRAM_CHAT_ID=
```

`ALLOW_ORDERS=false` makes `/api/orders/submit` and the bracket-order
equivalent return a fake `DRY_RUN` ack instead of calling `ib.placeOrder()`
-- build/test the whole flow risk-free, then flip to `true` only when
you're ready to test against the real account.

## 4. Root-level `.env` (optional, for Unusual Whales page)

```bash
cd ../..   # back to repo root
cp .env.example .env
```

Edit the repo-root `.env`:

```
UW_API_KEY=your_unusual_whales_api_key
```

## 5. Frontend setup

```bash
cd ibkr-options-app/frontend
npm install
```

## 6. Run it

**Manually, in two terminals:**

```bash
# Terminal 1 -- backend
cd ibkr-options-app/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload

# Terminal 2 -- frontend
cd ibkr-options-app/frontend
npm run dev -- --port 5175
```

Open http://localhost:5175.

**If using Claude Code on the new machine:** it drives dev servers via
`.claude/launch.json` at the repo root, which is gitignored (not part of
the clone) since paths are machine-specific. Either just ask Claude Code
to "start the app" -- it will create this file itself -- or create it
yourself:

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "ibkr-backend",
      "runtimeExecutable": "/path/to/your/python3.11-or-later",
      "runtimeArgs": ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--reload"],
      "cwd": "/absolute/path/to/options-report/ibkr-options-app/backend",
      "port": 8010
    },
    {
      "name": "ibkr-frontend",
      "runtimeExecutable": "/path/to/your/node",
      "runtimeArgs": ["node_modules/.bin/vite", "--port", "5175"],
      "cwd": "/absolute/path/to/options-report/ibkr-options-app/frontend",
      "port": 5175
    }
  ]
}
```

## 7. Verify

- `curl http://localhost:8010/api/health` -> `{"ok": true, "allowOrders": false}`
- The banner at the top of the app should read "Connected to IBKR" within
  a few seconds of TWS being up and reachable. If it says "Disconnected,"
  click Reconnect once TWS has finished loading.

## What each page needs

| Page | Needs |
|---|---|
| Dashboard, Positions, Chain, Order Ticket, Bracket Order, Strategy Builder, Profit Calculator, Portfolio Simulator, Max Pain, Watchlist, Alerts, Charts | TWS connection only |
| Unusual Whales | TWS connection + `UW_API_KEY` in the repo-root `.env` |

`US_watchlist.json` at the repo root drives the ticker sidebar/watchlist
across every page -- already committed, edit it to change which symbols
show up.
