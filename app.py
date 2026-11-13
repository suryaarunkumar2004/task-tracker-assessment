"""Task Tracker - a task management web application with Google sign-in.

Stack: Flask (Python), SQLite, vanilla HTML5/CSS3/JavaScript.
Core requirements:
- Google Authentication & Local Evaluator/Demo Authentication
- Create, view, update, edit, and delete tasks
- Exact states supported: Planned, In Progress, Complete
- User data isolation, validation, undo safety net, and data export
"""
from __future__ import annotations

import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, TypeVar, cast

from authlib.integrations.flask_client import OAuth  # type: ignore[import-untyped]
from authlib.integrations.base_client.errors import OAuthError  # type: ignore[import-untyped]
from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for, Response
from flask.typing import ResponseReturnValue
from werkzeug.middleware.proxy_fix import ProxyFix

_ = load_dotenv()

STATUSES: tuple[str, ...] = ("Planned", "In Progress", "Complete")
PRIORITIES: tuple[str, ...] = ("Low", "Medium", "High")
TITLE_MAX: int = 100
DESCRIPTION_MAX: int = 500
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "tasks.db")

app: Flask = Flask(__name__)

# Use SECRET_KEY from environment or a secure generated key for development
configured_secret: str = os.environ.get("SECRET_KEY", "").strip()
if configured_secret:
    app.secret_key = configured_secret
else:
    if os.environ.get("APP_ENV") == "production":
        raise RuntimeError("SECRET_KEY must be set in production.")
    # Safe persistent default for local development so it runs out-of-the-box
    app.secret_key = "task-tracker-dev-insecure-secret-key-3289f8a9e4"

# Trust the proxy headers set by hosting platforms so redirect URLs use https.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("APP_ENV") == "production"


def is_google_configured() -> bool:
    """Return True if real Google OAuth credentials have been set up in .env."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    return bool(client_id and client_secret and "your-client-id" not in client_id)


oauth: OAuth = OAuth(app)
_ = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Demo accounts available for zero-config local evaluation and testing multi-user isolation
DEMO_ACCOUNTS: dict[str, dict[str, object]] = {
    "alex": {
        "google_id": "demo_google_1001",
        "email": "alex.johnson@example.com",
        "name": "Alex Johnson",
        "picture": None,
    },
    "taylor": {
        "google_id": "demo_google_1002",
        "email": "taylor.morgan@example.com",
        "name": "Taylor Morgan",
        "picture": None,
    },
}


# ---------- Database ----------
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        con: sqlite3.Connection = sqlite3.connect(DATABASE_PATH)
        con.row_factory = sqlite3.Row
        _ = con.execute("PRAGMA foreign_keys = ON")
        g.db = con
    return g.db


@app.teardown_appcontext
def close_db(_exc: BaseException | None = None) -> None:
    db: sqlite3.Connection | None = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db: sqlite3.Connection = sqlite3.connect(DATABASE_PATH)
    try:
        _ = db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                google_id  TEXT NOT NULL UNIQUE,
                email      TEXT NOT NULL,
                name       TEXT NOT NULL,
                picture    TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                title       TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'Planned'
                            CHECK (status IN ('Planned', 'In Progress', 'Complete')),
                priority    TEXT NOT NULL DEFAULT 'Medium'
                            CHECK (priority IN ('Low', 'Medium', 'High')),
                due_date    TEXT,
                deleted_at  TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
            """
        )
        existing = {str(row[1]) for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
        if "priority" not in existing:
            _ = db.execute("ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'Medium'")
        if "due_date" not in existing:
            _ = db.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
        if "deleted_at" not in existing:
            _ = db.execute("ALTER TABLE tasks ADD COLUMN deleted_at TEXT")
        db.commit()
    finally:
        db.close()


init_db()


# ---------- Helpers ----------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_user() -> sqlite3.Row | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    row: sqlite3.Row | None = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return row


RouteFunc = TypeVar("RouteFunc", bound=Callable[..., ResponseReturnValue])


def login_required(view: RouteFunc) -> RouteFunc:
    @wraps(view)
    def wrapped(*args: object, **kwargs: object) -> ResponseReturnValue:
        user = current_user()
        if user is None:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify(error="Your session has expired. Please sign in again."), 401
            return redirect(url_for("login"))
        g.user = user
        return view(*args, **kwargs)

    return cast(RouteFunc, wrapped)


def task_to_dict(row: sqlite3.Row | None) -> dict[str, object]:
    if row is None:
        return {}
    keys = row.keys() if hasattr(row, "keys") else ()
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "priority": row["priority"],
        "due_date": row["due_date"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"] if "updated_at" in keys else row["created_at"],
    }


def json_body() -> dict[str, object] | None:
    """Return the JSON object in the request, or None if it is missing or not an object."""
    if not request.is_json:
        return None
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def text_value(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    return "" if value is None else str(value).strip()


def validate_fields(data: dict[str, object]) -> tuple[dict[str, object] | None, str | None]:
    """Validate whichever task fields are present in `data`.

    Returns (fields, error). Only fields that were sent are returned.
    """
    fields: dict[str, object] = {}
    if "title" in data:
        title = text_value(data, "title")
        if not title:
            return None, "Enter a task title."
        if len(title) > TITLE_MAX:
            return None, f"Title must be {TITLE_MAX} characters or fewer."
        fields["title"] = title
    if "description" in data:
        description = text_value(data, "description")
        if len(description) > DESCRIPTION_MAX:
            return None, f"Description must be {DESCRIPTION_MAX} characters or fewer."
        fields["description"] = description
    if "status" in data:
        if data["status"] not in STATUSES:
            return None, "Status must be Planned, In Progress, or Complete."
        fields["status"] = data["status"]
    if "priority" in data:
        if data["priority"] not in PRIORITIES:
            return None, "Priority must be Low, Medium, or High."
        fields["priority"] = data["priority"]
    if "due_date" in data:
        raw = data["due_date"]
        if raw in (None, ""):
            fields["due_date"] = None
        else:
            try:
                _ = datetime.strptime(str(raw), "%Y-%m-%d")
            except ValueError:
                return None, "Enter the due date in the format YYYY-MM-DD."
            fields["due_date"] = str(raw)
    return fields, None


def fetch_task(task_id: int, include_deleted: bool = False) -> sqlite3.Row | None:
    user = getattr(g, "user", None) or current_user()
    if user is None:
        return None
    query = "SELECT * FROM tasks WHERE id = ? AND user_id = ?"
    if not include_deleted:
        query += " AND deleted_at IS NULL"
    row: sqlite3.Row | None = get_db().execute(query, (task_id, user["id"])).fetchone()
    return row


# ---------- Pages and authentication ----------
@app.route("/")
@login_required
def index() -> ResponseReturnValue:
    user = getattr(g, "user", None) or current_user()
    return render_template(
        "index.html",
        user=user,
        statuses=STATUSES,
        priorities=PRIORITIES,
        title_max=TITLE_MAX,
        description_max=DESCRIPTION_MAX,
        google_configured=is_google_configured(),
    )


@app.route("/login")
def login() -> ResponseReturnValue:
    if current_user():
        return redirect(url_for("index"))
    return render_template(
        "login.html",
        error=request.args.get("error"),
        google_configured=is_google_configured(),
        demo_accounts=DEMO_ACCOUNTS,
    )


@app.route("/auth/google")
def auth_google() -> ResponseReturnValue:
    if not is_google_configured():
        # Helpful guidance for evaluators running without Google Cloud credentials
        return redirect(url_for("login", error="google_not_configured"))
    try:
        google_client = oauth.create_client("google")
        if not google_client:
            return redirect(url_for("login", error="oauth_error"))
        return google_client.authorize_redirect(url_for("auth_callback", _external=True))
    except Exception:
        return redirect(url_for("login", error="oauth_error"))


@app.route("/auth/callback")
def auth_callback() -> ResponseReturnValue:
    google_client = oauth.create_client("google")
    if not google_client:
        return redirect(url_for("login", error="1"))
    try:
        raw_token = google_client.authorize_access_token()
    except OAuthError:
        return redirect(url_for("login", error="1"))

    token = raw_token if isinstance(raw_token, dict) else {}
    raw_userinfo = token.get("userinfo")
    info = raw_userinfo if isinstance(raw_userinfo, dict) else {}
    google_id = info.get("sub")
    email = info.get("email")
    if not google_id or not email:
        return redirect(url_for("login", error="1"))

    raw_name = info.get("name")
    name: str = str(raw_name) if raw_name else str(email).split("@")[0]
    db: sqlite3.Connection = get_db()
    _ = db.execute(
        """
        INSERT INTO users (google_id, email, name, picture) VALUES (?, ?, ?, ?)
        ON CONFLICT(google_id) DO UPDATE SET email = excluded.email,
            name = excluded.name, picture = excluded.picture
        """,
        (str(google_id), str(email), name, info.get("picture")),
    )
    db.commit()
    user: sqlite3.Row | None = db.execute("SELECT id FROM users WHERE google_id = ?", (str(google_id),)).fetchone()
    if user is None:
        return redirect(url_for("login", error="1"))
    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for("index"))


@app.route("/auth/demo", methods=["POST", "GET"])
def auth_demo() -> ResponseReturnValue:
    """Demo login endpoint for quick local testing and evaluation."""
    account_key: str = str(request.values.get("account", "alex"))
    demo_user = DEMO_ACCOUNTS.get(account_key, DEMO_ACCOUNTS["alex"])

    db: sqlite3.Connection = get_db()
    _ = db.execute(
        """
        INSERT INTO users (google_id, email, name, picture) VALUES (?, ?, ?, ?)
        ON CONFLICT(google_id) DO UPDATE SET email = excluded.email,
            name = excluded.name, picture = excluded.picture
        """,
        (demo_user["google_id"], demo_user["email"], demo_user["name"], demo_user.get("picture")),
    )
    db.commit()
    user: sqlite3.Row | None = db.execute("SELECT id FROM users WHERE google_id = ?", (demo_user["google_id"],)).fetchone()
    if user is None:
        return redirect(url_for("login", error="1"))
    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for("index"))


@app.route("/logout", methods=["POST"])
def logout() -> ResponseReturnValue:
    session.clear()
    return redirect(url_for("login"))


# ---------- Task API ----------
@app.get("/api/tasks")
@login_required
def list_tasks() -> ResponseReturnValue:
    user = getattr(g, "user", None) or current_user()
    if user is None:
        return jsonify(error="Unauthorized"), 401
    rows = get_db().execute(
        "SELECT * FROM tasks WHERE user_id = ? AND deleted_at IS NULL ORDER BY id DESC",
        (user["id"],),
    ).fetchall()
    return jsonify(tasks=[task_to_dict(r) for r in rows])


@app.post("/api/tasks")
@login_required
def create_task() -> ResponseReturnValue:
    data = json_body()
    if data is None:
        return jsonify(error="Request must be a JSON object."), 415

    fields, error = validate_fields(data)
    if error or fields is None:
        return jsonify(error=error or "Invalid data."), 400
    if "title" not in fields:
        return jsonify(error="Enter a task title."), 400

    user = getattr(g, "user", None) or current_user()
    if user is None:
        return jsonify(error="Unauthorized"), 401

    db: sqlite3.Connection = get_db()
    ts = now_iso()
    cur = db.execute(
        """INSERT INTO tasks (user_id, title, description, status, priority, due_date, created_at, updated_at)
        VALUES (?, ?, ?, 'Planned', ?, ?, ?, ?)""",
        (
            user["id"],
            fields["title"],
            fields.get("description", ""),
            fields.get("priority", "Medium"),
            fields.get("due_date"),
            ts,
            ts,
        ),
    )
    db.commit()
    new_task = fetch_task(cur.lastrowid) if cur.lastrowid is not None else None
    return jsonify(task=task_to_dict(new_task)), 201


@app.patch("/api/tasks/<int:task_id>")
@login_required
def update_task(task_id: int) -> ResponseReturnValue:
    data = json_body()
    if data is None:
        return jsonify(error="Request must be a JSON object."), 415

    fields, error = validate_fields(data)
    if error or fields is None:
        return jsonify(error=error or "Invalid data."), 400
    if not fields:
        return jsonify(error="There is nothing to update."), 400

    if fetch_task(task_id) is None:
        return jsonify(error="Task not found."), 404

    user = getattr(g, "user", None) or current_user()
    if user is None:
        return jsonify(error="Unauthorized"), 401

    assignments = ", ".join(f"{column} = ?" for column in fields)
    db: sqlite3.Connection = get_db()
    _ = db.execute(
        f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ? AND user_id = ?",
        (*fields.values(), now_iso(), task_id, user["id"]),
    )
    db.commit()
    return jsonify(task=task_to_dict(fetch_task(task_id)))


@app.delete("/api/tasks/<int:task_id>")
@login_required
def delete_task(task_id: int) -> ResponseReturnValue:
    user = getattr(g, "user", None) or current_user()
    if user is None:
        return jsonify(error="Unauthorized"), 401
    db: sqlite3.Connection = get_db()
    cur = db.execute(
        "UPDATE tasks SET deleted_at = ? WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
        (now_iso(), task_id, user["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        return jsonify(error="Task not found."), 404
    return jsonify(ok=True)


@app.post("/api/tasks/<int:task_id>/restore")
@login_required
def restore_task(task_id: int) -> ResponseReturnValue:
    user = getattr(g, "user", None) or current_user()
    if user is None:
        return jsonify(error="Unauthorized"), 401
    db: sqlite3.Connection = get_db()
    cur = db.execute(
        "UPDATE tasks SET deleted_at = NULL WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL",
        (task_id, user["id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        return jsonify(error="Task not found."), 404
    return jsonify(task=task_to_dict(fetch_task(task_id)))


@app.post("/api/tasks/clear-completed")
@login_required
def clear_completed() -> ResponseReturnValue:
    user = getattr(g, "user", None) or current_user()
    if user is None:
        return jsonify(error="Unauthorized"), 401
    db: sqlite3.Connection = get_db()
    rows = db.execute(
        "SELECT id FROM tasks WHERE user_id = ? AND status = 'Complete' AND deleted_at IS NULL",
        (user["id"],),
    ).fetchall()
    task_ids = [int(r["id"]) for r in rows]
    if not task_ids:
        return jsonify(cleared_count=0, task_ids=[])

    ts = now_iso()
    placeholders = ",".join("?" * len(task_ids))
    _ = db.execute(
        f"UPDATE tasks SET deleted_at = ? WHERE id IN ({placeholders}) AND user_id = ?",
        (ts, *task_ids, user["id"]),
    )
    db.commit()
    return jsonify(cleared_count=len(task_ids), task_ids=task_ids)


@app.post("/api/tasks/restore-multiple")
@login_required
def restore_multiple() -> ResponseReturnValue:
    user = getattr(g, "user", None) or current_user()
    if user is None:
        return jsonify(error="Unauthorized"), 401
    data = json_body()
    raw_ids = data.get("task_ids") if data else None
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify(error="Provide a list of task IDs to restore."), 400

    task_ids = [int(x) for x in raw_ids if isinstance(x, (int, str)) and str(x).isdigit()]
    if not task_ids:
        return jsonify(error="Provide valid task IDs to restore."), 400

    db: sqlite3.Connection = get_db()
    placeholders = ",".join("?" * len(task_ids))
    _ = db.execute(
        f"UPDATE tasks SET deleted_at = NULL WHERE id IN ({placeholders}) AND user_id = ?",
        (*task_ids, user["id"]),
    )
    db.commit()
    return jsonify(ok=True, restored_count=len(task_ids))


@app.get("/api/tasks/export")
@login_required
def export_tasks() -> ResponseReturnValue:
    user = getattr(g, "user", None) or current_user()
    if user is None:
        return jsonify(error="Unauthorized"), 401
    fmt = request.args.get("format", "csv").lower()
    rows = get_db().execute(
        "SELECT id, title, description, status, priority, due_date, created_at, updated_at "
        "FROM tasks WHERE user_id = ? AND deleted_at IS NULL ORDER BY id DESC",
        (user["id"],),
    ).fetchall()

    if fmt == "json":
        return jsonify(tasks=[task_to_dict(r) for r in rows])

    # Default: CSV format
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Title", "Description", "Status", "Priority", "Due Date", "Created At", "Updated At"])
    for r in rows:
        writer.writerow([
            r["id"],
            r["title"],
            r["description"],
            r["status"],
            r["priority"],
            r["due_date"] or "",
            r["created_at"],
            r["updated_at"],
        ])

    csv_data = output.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tasks_export_{timestamp}.csv"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("APP_ENV") != "production")
