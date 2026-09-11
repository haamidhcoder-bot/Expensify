"""
app.py
Flask REST API for the Expense Tracker.

Run with:
    python app.py

Serves the API under /api/* and also serves the static frontend
(../frontend) so the whole app can be opened at http://localhost:5000
with a single command.
"""

import os
import io
import csv
from datetime import datetime, date, timedelta
from calendar import monthrange

from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from dotenv import load_dotenv

import db
from gemini_service import parse_expense_text, generate_insights, GeminiNotConfigured

load_dotenv()

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)

db.init_db()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def row_to_dict(row):
    return dict(row) if row else None


def error(message, status=400):
    return jsonify({"error": message}), status


def validate_expense_payload(payload, require_all=True):
    """Returns (cleaned_data, error_message). error_message is None if valid."""
    cleaned = {}

    if require_all or "amount" in payload:
        try:
            amount = float(payload.get("amount"))
        except (TypeError, ValueError):
            return None, "amount must be a number"
        if amount <= 0:
            return None, "amount must be greater than 0"
        cleaned["amount"] = round(amount, 2)

    if require_all or "category_id" in payload:
        try:
            category_id = int(payload.get("category_id"))
        except (TypeError, ValueError):
            return None, "category_id is required"
        with db.get_db() as conn:
            cat = conn.execute("SELECT id FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat:
            return None, "category_id does not exist"
        cleaned["category_id"] = category_id

    if require_all or "date" in payload:
        date_str = payload.get("date", "")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except (TypeError, ValueError):
            return None, "date must be in YYYY-MM-DD format"
        cleaned["date"] = date_str

    cleaned["description"] = str(payload.get("description", "")).strip()[:200]
    cleaned["payment_method"] = payload.get("payment_method", "Cash") or "Cash"
    cleaned["notes"] = str(payload.get("notes", "")).strip()[:500]

    return cleaned, None


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------

@app.route("/api/categories", methods=["GET"])
def list_categories():
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT c.*,
                   COALESCE(SUM(e.amount), 0) AS total_spent,
                   COUNT(e.id) AS expense_count
            FROM categories c
            LEFT JOIN expenses e ON e.category_id = c.id
            GROUP BY c.id
            ORDER BY c.name ASC
        """).fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/categories", methods=["POST"])
def create_category():
    payload = request.get_json(force=True, silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not name:
        return error("name is required")

    icon = payload.get("icon", "📦") or "📦"
    color = payload.get("color", "#9CA3AF") or "#9CA3AF"
    try:
        budget = float(payload.get("monthly_budget", 0) or 0)
    except (TypeError, ValueError):
        return error("monthly_budget must be a number")

    try:
        with db.get_db() as conn:
            cur = conn.execute(
                "INSERT INTO categories (name, icon, color, monthly_budget) VALUES (?, ?, ?, ?)",
                (name, icon, color, budget),
            )
            new_id = cur.lastrowid
    except db.sqlite3.IntegrityError:
        return error("a category with that name already exists", 409)

    return jsonify({"id": new_id, "name": name, "icon": icon, "color": color, "monthly_budget": budget}), 201


@app.route("/api/categories/<int:category_id>", methods=["PUT"])
def update_category(category_id):
    payload = request.get_json(force=True, silent=True) or {}
    with db.get_db() as conn:
        existing = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not existing:
            return error("category not found", 404)

        name = str(payload.get("name", existing["name"])).strip() or existing["name"]
        icon = payload.get("icon", existing["icon"])
        color = payload.get("color", existing["color"])
        try:
            budget = float(payload.get("monthly_budget", existing["monthly_budget"]))
        except (TypeError, ValueError):
            return error("monthly_budget must be a number")

        try:
            conn.execute(
                "UPDATE categories SET name = ?, icon = ?, color = ?, monthly_budget = ? WHERE id = ?",
                (name, icon, color, budget, category_id),
            )
        except db.sqlite3.IntegrityError:
            return error("a category with that name already exists", 409)

    return jsonify({"id": category_id, "name": name, "icon": icon, "color": color, "monthly_budget": budget})


@app.route("/api/categories/<int:category_id>", methods=["DELETE"])
def delete_category(category_id):
    with db.get_db() as conn:
        in_use = conn.execute(
            "SELECT COUNT(*) AS c FROM expenses WHERE category_id = ?", (category_id,)
        ).fetchone()["c"]
        if in_use > 0:
            return error(
                f"cannot delete: {in_use} expense(s) still use this category. Reassign them first.", 409
            )
        deleted = conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        if deleted.rowcount == 0:
            return error("category not found", 404)
    return jsonify({"success": True})


# --------------------------------------------------------------------------
# Expenses
# --------------------------------------------------------------------------

@app.route("/api/expenses", methods=["GET"])
def list_expenses():
    category_id = request.args.get("category_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    search = request.args.get("search")
    sort = request.args.get("sort", "date_desc")

    query = """
        SELECT e.*, c.name AS category_name, c.icon AS category_icon, c.color AS category_color
        FROM expenses e
        JOIN categories c ON c.id = e.category_id
        WHERE 1 = 1
    """
    params = []

    if category_id:
        query += " AND e.category_id = ?"
        params.append(category_id)
    if start_date:
        query += " AND e.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND e.date <= ?"
        params.append(end_date)
    if search:
        query += " AND (e.description LIKE ? OR e.notes LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])

    sort_map = {
        "date_desc": "e.date DESC, e.id DESC",
        "date_asc": "e.date ASC, e.id ASC",
        "amount_desc": "e.amount DESC",
        "amount_asc": "e.amount ASC",
    }
    query += f" ORDER BY {sort_map.get(sort, sort_map['date_desc'])}"

    with db.get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/expenses/<int:expense_id>", methods=["GET"])
def get_expense(expense_id):
    with db.get_db() as conn:
        row = conn.execute("""
            SELECT e.*, c.name AS category_name, c.icon AS category_icon, c.color AS category_color
            FROM expenses e JOIN categories c ON c.id = e.category_id
            WHERE e.id = ?
        """, (expense_id,)).fetchone()
    if not row:
        return error("expense not found", 404)
    return jsonify(row_to_dict(row))


@app.route("/api/expenses", methods=["POST"])
def create_expense():
    payload = request.get_json(force=True, silent=True) or {}
    cleaned, err = validate_expense_payload(payload, require_all=True)
    if err:
        return error(err)

    with db.get_db() as conn:
        cur = conn.execute(
            """INSERT INTO expenses (amount, category_id, description, date, payment_method, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cleaned["amount"], cleaned["category_id"], cleaned["description"],
             cleaned["date"], cleaned["payment_method"], cleaned["notes"]),
        )
        new_id = cur.lastrowid
        row = conn.execute("""
            SELECT e.*, c.name AS category_name, c.icon AS category_icon, c.color AS category_color
            FROM expenses e JOIN categories c ON c.id = e.category_id WHERE e.id = ?
        """, (new_id,)).fetchone()

    return jsonify(row_to_dict(row)), 201


@app.route("/api/expenses/<int:expense_id>", methods=["PUT"])
def update_expense(expense_id):
    payload = request.get_json(force=True, silent=True) or {}
    with db.get_db() as conn:
        existing = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if not existing:
            return error("expense not found", 404)

    merged = {
        "amount": payload.get("amount", existing["amount"]),
        "category_id": payload.get("category_id", existing["category_id"]),
        "date": payload.get("date", existing["date"]),
        "description": payload.get("description", existing["description"]),
        "payment_method": payload.get("payment_method", existing["payment_method"]),
        "notes": payload.get("notes", existing["notes"]),
    }
    cleaned, err = validate_expense_payload(merged, require_all=True)
    if err:
        return error(err)

    with db.get_db() as conn:
        conn.execute(
            """UPDATE expenses SET amount = ?, category_id = ?, description = ?,
               date = ?, payment_method = ?, notes = ? WHERE id = ?""",
            (cleaned["amount"], cleaned["category_id"], cleaned["description"],
             cleaned["date"], cleaned["payment_method"], cleaned["notes"], expense_id),
        )
        row = conn.execute("""
            SELECT e.*, c.name AS category_name, c.icon AS category_icon, c.color AS category_color
            FROM expenses e JOIN categories c ON c.id = e.category_id WHERE e.id = ?
        """, (expense_id,)).fetchone()

    return jsonify(row_to_dict(row))


@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    with db.get_db() as conn:
        deleted = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        if deleted.rowcount == 0:
            return error("expense not found", 404)
    return jsonify({"success": True})


# --------------------------------------------------------------------------
# Summary / Dashboard
# --------------------------------------------------------------------------

@app.route("/api/summary", methods=["GET"])
def summary():
    today = date.today()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    first_of_last_month = last_month_end.replace(day=1)
    thirty_days_ago = today - timedelta(days=29)

    with db.get_db() as conn:
        total_spent = conn.execute("SELECT COALESCE(SUM(amount), 0) AS t FROM expenses").fetchone()["t"]

        total_this_month = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS t FROM expenses WHERE date >= ?",
            (first_of_month.isoformat(),),
        ).fetchone()["t"]

        total_last_month = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS t FROM expenses WHERE date >= ? AND date <= ?",
            (first_of_last_month.isoformat(), last_month_end.isoformat()),
        ).fetchone()["t"]

        by_category = conn.execute("""
            SELECT c.id, c.name, c.icon, c.color, c.monthly_budget,
                   COALESCE(SUM(e.amount), 0) AS spent
            FROM categories c
            LEFT JOIN expenses e ON e.category_id = c.id AND e.date >= ?
            GROUP BY c.id
            HAVING spent > 0 OR c.monthly_budget > 0
            ORDER BY spent DESC
        """, (first_of_month.isoformat(),)).fetchall()

        daily_rows = conn.execute("""
            SELECT date, SUM(amount) AS total
            FROM expenses
            WHERE date >= ?
            GROUP BY date
        """, (thirty_days_ago.isoformat(),)).fetchall()

        monthly_rows = conn.execute("""
            SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS total
            FROM expenses
            GROUP BY month
            ORDER BY month DESC
            LIMIT 6
        """).fetchall()

        recent = conn.execute("""
            SELECT e.*, c.name AS category_name, c.icon AS category_icon, c.color AS category_color
            FROM expenses e JOIN categories c ON c.id = e.category_id
            ORDER BY e.date DESC, e.id DESC LIMIT 5
        """).fetchall()

    # Fill in every day of the last 30 days (even zero-spend days) for a clean chart
    daily_map = {r["date"]: r["total"] for r in daily_rows}
    daily_trend = []
    for i in range(30):
        d = (thirty_days_ago + timedelta(days=i)).isoformat()
        daily_trend.append({"date": d, "total": daily_map.get(d, 0)})

    change_percent = None
    if total_last_month > 0:
        change_percent = round(((total_this_month - total_last_month) / total_last_month) * 100, 1)

    category_summary = []
    for c in by_category:
        pct_of_month = round((c["spent"] / total_this_month) * 100, 1) if total_this_month > 0 else 0
        budget_pct = round((c["spent"] / c["monthly_budget"]) * 100, 1) if c["monthly_budget"] > 0 else None
        category_summary.append({
            "id": c["id"], "name": c["name"], "icon": c["icon"], "color": c["color"],
            "spent": c["spent"], "monthly_budget": c["monthly_budget"],
            "percent_of_spending": pct_of_month, "budget_percent_used": budget_pct,
        })

    return jsonify({
        "total_spent": total_spent,
        "total_this_month": total_this_month,
        "total_last_month": total_last_month,
        "change_percent": change_percent,
        "by_category": category_summary,
        "daily_trend": daily_trend,
        "monthly_trend": [{"month": r["month"], "total": r["total"]} for r in reversed(monthly_rows)],
        "recent_expenses": [row_to_dict(r) for r in recent],
    })


# --------------------------------------------------------------------------
# CSV export
# --------------------------------------------------------------------------

@app.route("/api/export/csv", methods=["GET"])
def export_csv():
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT e.date, c.name AS category, e.amount, e.description, e.payment_method, e.notes
            FROM expenses e JOIN categories c ON c.id = e.category_id
            ORDER BY e.date DESC
        """).fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Category", "Amount", "Description", "Payment Method", "Notes"])
    for r in rows:
        writer.writerow([r["date"], r["category"], r["amount"], r["description"], r["payment_method"], r["notes"]])

    filename = f"expenses_export_{date.today().isoformat()}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# --------------------------------------------------------------------------
# Gemini-powered AI features
# --------------------------------------------------------------------------

@app.route("/api/ai/parse", methods=["POST"])
def ai_parse():
    payload = request.get_json(force=True, silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return error("text is required")

    with db.get_db() as conn:
        categories = [r["name"] for r in conn.execute("SELECT name FROM categories").fetchall()]

    try:
        parsed = parse_expense_text(text, categories)
    except GeminiNotConfigured as e:
        return error(str(e), 501)
    except Exception as e:
        return error(f"AI parsing failed: {e}", 502)

    with db.get_db() as conn:
        cat_row = conn.execute("SELECT id FROM categories WHERE name = ?", (parsed["category"],)).fetchone()
    parsed["category_id"] = cat_row["id"] if cat_row else None

    return jsonify(parsed)


@app.route("/api/ai/insights", methods=["GET"])
def ai_insights():
    days = int(request.args.get("days", 30))
    since = (date.today() - timedelta(days=days)).isoformat()

    with db.get_db() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS t, COUNT(*) AS c FROM expenses WHERE date >= ?", (since,)
        ).fetchone()
        by_cat = conn.execute("""
            SELECT c.name, COALESCE(SUM(e.amount),0) AS spent, COUNT(e.id) AS count,
                   c.monthly_budget
            FROM categories c LEFT JOIN expenses e ON e.category_id = c.id AND e.date >= ?
            GROUP BY c.id HAVING spent > 0
            ORDER BY spent DESC
        """, (since,)).fetchall()
        top_expenses = conn.execute("""
            SELECT e.amount, e.description, c.name AS category, e.date
            FROM expenses e JOIN categories c ON c.id = e.category_id
            WHERE e.date >= ? ORDER BY e.amount DESC LIMIT 5
        """, (since,)).fetchall()

    if total["c"] == 0:
        return jsonify({"insights": ["Add a few expenses first — insights need some spending history to work with."]})

    summary_payload = {
        "period_days": days,
        "total_spent": total["t"],
        "transaction_count": total["c"],
        "spending_by_category": [
            {"category": r["name"], "spent": r["spent"], "count": r["count"], "monthly_budget": r["monthly_budget"]}
            for r in by_cat
        ],
        "top_individual_expenses": [
            {"amount": r["amount"], "description": r["description"], "category": r["category"], "date": r["date"]}
            for r in top_expenses
        ],
    }

    try:
        insights = generate_insights(summary_payload)
    except GeminiNotConfigured as e:
        return error(str(e), 501)
    except Exception as e:
        return error(f"AI insights failed: {e}", 502)

    return jsonify({"insights": insights})


@app.route("/api/ai/status", methods=["GET"])
def ai_status():
    return jsonify({"configured": bool(os.environ.get("GEMINI_API_KEY"))})


# --------------------------------------------------------------------------
# Frontend static hosting
# --------------------------------------------------------------------------

@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # host="0.0.0.0" makes the server reachable from other devices on the
    # same Wi-Fi network (e.g. your phone), not just this computer.
    app.run(debug=True, port=port, host="0.0.0.0")
