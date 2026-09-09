# Expensify — Smart Expense Tracker

A full-stack personal expense tracker with a modern, responsive UI, a Python
(Flask) REST API, SQLite storage, and optional AI features powered by the
Gemini API (natural-language expense entry + personalized spending insights).

## Features

- **Dashboard** — total/monthly spend, month-over-month change, top category,
  a category breakdown chart, a 30-day spending trend chart, recent
  transactions, and live budget-progress bars.
- **Expenses** — add, edit, delete; search by description/notes; filter by
  category and date range; sort by date or amount; CSV export.
- **Categories & Budgets** — create/edit/delete custom categories (icon +
  color), set a monthly budget per category, see spend vs. budget.
- **AI Quick Add** — type a sentence like *"Spent 450 on groceries yesterday
  with card"* and Gemini fills in the amount, category, date, description,
  and payment method for you to review before saving.
- **AI Insights** — Gemini analyzes your recent spending and returns a short
  list of concrete, personalized tips.
- **Modern UI** — light/dark mode, fully responsive (desktop sidebar / mobile
  bottom nav), toast notifications, confirm dialogs.

The app works fully **without** a Gemini API key — only the two AI features
are disabled until you add one; everything else (tracking, budgets, charts,
export) works immediately.

## Project structure

```
expense-tracker/
├── backend/
│   ├── app.py              # Flask app & all API routes
│   ├── db.py                # SQLite schema + connection helpers
│   ├── gemini_service.py    # Gemini API wrapper (parsing + insights)
│   ├── requirements.txt
│   └── .env.example         # copy to .env and add your Gemini key
└── frontend/
    ├── index.html
    ├── style.css
    └── script.js
```

## Setup

1. **Install dependencies** (Python 3.9+):

   ```bash
   cd expense-tracker/backend
   pip install -r requirements.txt
   ```

2. **(Optional) Enable AI features** — get a free key from
   [Google AI Studio](https://aistudio.google.com/apikey), then:

   ```bash
   cp .env.example .env
   # edit .env and paste your key into GEMINI_API_KEY
   ```

3. **Run the server:**

   ```bash
   python app.py
   ```

4. Open **http://localhost:5000** in your browser. That's it — the Flask
   server also serves the frontend, so there's nothing separate to start.

## Using it on your phone

The UI is fully responsive and works great on mobile. There are two ways to get to it from a phone:

**Option A — same Wi-Fi network (quickest)**
1. Start the server on your computer as usual (`python app.py`).
2. Find your computer's local IP address:
   - Windows: `ipconfig` → look for "IPv4 Address" (e.g. `192.168.1.42`)
   - Mac/Linux: `ifconfig` or `ip addr` → look for something like `192.168.1.42`
3. Make sure your phone is on the **same Wi-Fi network**.
4. On your phone's browser, go to `http://<that-ip>:5000` (e.g. `http://192.168.1.42:5000`).
5. Optional: add it to your home screen (Share → "Add to Home Screen" on iOS, or the browser menu → "Add to Home Screen" on Android) so it opens like an app.

This only works while your computer is on and running the server, and both devices are on the same network.

**Option B — access from anywhere (deploy it)**
If you want it reachable without your computer running, deploy the backend to a free host such as Render, PythonAnywhere, or Railway (any of them can run a Flask app), then open the deployed URL from your phone. This takes a bit more setup — ask me and I can walk you through deploying to a specific one.

**Option C — run it entirely on your phone (Android only)**
Install [Termux](https://f-droid.org/packages/com.termux/), then inside it: `pkg install python`, `pip install -r requirements.txt`, and `python app.py`. Open `http://localhost:5000` in the phone's browser. No computer needed at all, but iPhone doesn't have an equivalent tool.

## Notes

- Data is stored locally in `backend/expenses.db` (SQLite), created
  automatically on first run with ten default categories.
- The Gemini model used is `gemini-2.5-flash` by default; override it by
  setting `GEMINI_MODEL` in `.env` (e.g. to a newer model as they become
  available).
- Currency is formatted as INR (₹) by default — change the locale/currency
  in `fmtCurrency()` in `script.js` if you'd prefer USD, EUR, etc.
