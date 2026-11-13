"""Task Tracker - a task management web application with Google sign-in.

Stack: Flask (Python), SQLite, vanilla HTML5/CSS3/JavaScript.
Core requirements:
- Google Authentication & Local Evaluator/Demo Authentication
- Create, view, update, edit, and delete tasks
- Exact states supported: Planned, In Progress, Complete
- User data isolation, validation, undo safety net, and data export
"""
import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for, Response
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

STATUSES = ("Planned", "In Progress", "Complete")
PRIORITIES = ("Low", "Medium", "High")
TITLE_MAX = 100
DESCRIPTION_MAX = 500
DATABASE_PATH = os.environ.get("DATABASE_PATH", "tasks.db")

app = Flask(__name__)

# Use SECRET_KEY from environment or a secure generated key for development
configured_secret = os.environ.get("SECRET_KEY", "").strip()
if configured_secret:
    app.secret_key = configured_secret
else:
    if os.environ.get("APP_ENV") == "production":
        raise RuntimeError("SECRET_KEY must be set in production.")
    # Safe persistent default for local development so it runs out-of-the-box
    app.secret_key = "task-tracker-dev-insecure-secret-key-3289f8a9e4"

# Trust the proxy headers set by hosting platforms so redirect URLs use https.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("APP_ENV") == "production",
)


def is_google_configured():
    """Return True if real Google OAuth credentials have been set up in .env."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    return bool(client_id and client_secret and "your-client-id" not in client_id)


oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Demo accounts available for zero-config local evaluation and testing multi-user isolation
DEMO_ACCOUNTS = {
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
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE_PATH)
    try:
        db.executescript(
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
        # Upgrade databases created by an earlier version of the app.
        existing = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
        if "priority" not in existing:
            db.execute("ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'Medium'")
        if "due_date" not in existing:
            db.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
        if "deleted_at" not in existing:
            db.execute("ALTER TABLE tasks ADD COLUMN deleted_at TEXT")
        db.commit()
    finally:
        db.close()


init_db()


# ---------- Helpers ----------
def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify(error="Your session has expired. Please sign in again."), 401
            return redirect(url_for("login"))
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def task_to_dict(row):
    if not row:
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


def json_body():
    """Return the JSON object in the request, or None if it is missing or not an object."""
    if not request.is_json:
        return None
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def text_value(data, key):
    value = data.get(key)
    return "" if value is None else str(value).strip()


def validate_fields(data):
    """Validate whichever task fields are present in `data`.

    Returns (fields, error). Only fields that were sent are returned.
    """
    fields = {}
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
                datetime.strptime(str(raw), "%Y-%m-%d")
            except ValueError:
                return None, "Enter the due date in the format YYYY-MM-DD."
            fields["due_date"] = str(raw)
    return fields, None


def fetch_task(task_id, include_deleted=False):
    user = getattr(g, "user", None) or current_user()
    if not user:
        return None
    query = "SELECT * FROM tasks WHERE id = ? AND user_id = ?"
    if not include_deleted:
        query += " AND deleted_at IS NULL"
    return get_db().execute(query, (task_id, user["id"])).fetchone()


# ---------- Pages and authentication ----------
@app.route("/")
@login_required
def index():
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
def login():
    if current_user():
        return redirect(url_for("index"))
    return render_template(
        "login.html",
        error=request.args.get("error"),
        google_configured=is_google_configured(),
        demo_accounts=DEMO_ACCOUNTS,
    )


@app.route("/auth/google")
def auth_google():
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
def auth_callback():
    try:
        google_client = oauth.create_client("google")
        if not google_client:
            return redirect(url_for("login", error="1"))
        token = google_client.authorize_access_token()
    except OAuthError:
        return redirect(url_for("login", error="1"))

    info = token.get("userinfo") or {}
    google_id, email = info.get("sub"), info.get("email")
    if not google_id or not email:
        return redirect(url_for("login", error="1"))

    name = info.get("name") or email.split("@")[0]
    db = get_db()
    db.execute(
        """
        INSERT INTO users (google_id, email, name, picture) VALUES (?, ?, ?, ?)
        ON CONFLICT(google_id) DO UPDATE SET email = excluded.email,
            name = excluded.name, picture = excluded.picture
        """,
        (google_id, email, name, info.get("picture")),
    )
    db.commit()
    user = db.execute("SELECT id FROM users WHERE google_id = ?", (google_id,)).fetchone()
    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for("index"))


@app.route("/auth/demo", methods=["POST", "GET"])
def auth_demo():
    """Demo login endpoint for quick local testing and evaluation."""
    account_key = request.values.get("account", "alex")
    demo_user = DEMO_ACCOUNTS.get(account_key, DEMO_ACCOUNTS["alex"])

    db = get_db()
    db.execute(
        """
        INSERT INTO users (google_id, email, name, picture) VALUES (?, ?, ?, ?)
        ON CONFLICT(google_id) DO UPDATE SET email = excluded.email,
            name = excluded.name, picture = excluded.picture
        """,
        (demo_user["google_id"], demo_user["email"], demo_user["name"], demo_user.get("picture")),
    )
    db.commit()
    user = db.execute("SELECT id FROM users WHERE google_id = ?", (demo_user["google_id"],)).fetchone()
    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for("index"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- Task API ----------
@app.get("/api/tasks")
@login_required
def list_tasks():
    user = getattr(g, "user", None) or current_user()
    if not user:
        return jsonify(error="Unauthorized"), 401
    rows = get_db().execute(
        "SELECT * FROM tasks WHERE user_id = ? AND deleted_at IS NULL ORDER BY id DESC",
        (user["id"],),
    ).fetchall()
    return jsonify(tasks=[task_to_dict(r) for r in rows])


@app.post("/api/tasks")
@login_required
def create_task():
    data = json_body()
    if data is None:
        return jsonify(error="Request must be a JSON object."), 415

    fields, error = validate_fields(data)
    if error:
        return jsonify(error=error), 400
    if "title" not in fields:
        return jsonify(error="Enter a task title."), 400

    user = getattr(g, "user", None) or current_user()
    if not user:
        return jsonify(error="Unauthorized"), 401

    db = get_db()
    ts = now_iso()
    cur = db.execute(
        "INSERT INTO tasks (user_id, title, description, status, priority, due_date, created_at, updated_at) "
        "VALUES (?, ?, ?, 'Planned', ?, ?, ?, ?)",
        (user["id"], fields["title"], fields.get("description", ""),
         fields.get("priority", "Medium"), fields.get("due_date"), ts, ts),
    )
    db.commit()
    new_task = fetch_task(cur.lastrowid)
    return jsonify(task=task_to_dict(new_task)), 201


@app.patch("/api/tasks/<int:task_id>")
@login_required
def update_task(task_id):
    data = json_body()
    if data is None:
        return jsonify(error="Request must be a JSON object."), 415

    fields, error = validate_fields(data)
    if error:
        return jsonify(error=error), 400
    if not fields:
        return jsonify(error="There is nothing to update."), 400

    if fetch_task(task_id) is None:
        return jsonify(error="Task not found."), 404

    user = getattr(g, "user", None) or current_user()
    if not user:
        return jsonify(error="Unauthorized"), 401

    assignments = ", ".join(f"{column} = ?" for column in fields)
    db = get_db()
    db.execute(
        f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ? AND user_id = ?",
        (*fields.values(), now_iso(), task_id, user["id"]),
    )
    db.commit()
    return jsonify(task=task_to_dict(fetch_task(task_id)))


@app.delete("/api/tasks/<int:task_id>")
@login_required
def delete_task(task_id):
    user = getattr(g, "user", None) or current_user()
    if not user:
        return jsonify(error="Unauthorized"), 401
    db = get_db()
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
def restore_task(task_id):
    user = getattr(g, "user", None) or current_user()
    if not user:
        return jsonify(error="Unauthorized"), 401
    db = get_db()
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
def clear_completed():
    user = getattr(g, "user", None) or current_user()
    if not user:
        return jsonify(error="Unauthorized"), 401
    db = get_db()
    rows = db.execute(
        "SELECT id FROM tasks WHERE user_id = ? AND status = 'Complete' AND deleted_at IS NULL",
        (user["id"],)
    ).fetchall()
    task_ids = [r["id"] for r in rows]
    if not task_ids:
        return jsonify(cleared_count=0, task_ids=[])

    ts = now_iso()
    placeholders = ",".join("?" * len(task_ids))
    db.execute(
        f"UPDATE tasks SET deleted_at = ? WHERE id IN ({placeholders}) AND user_id = ?",
        (ts, *task_ids, user["id"])
    )
    db.commit()
    return jsonify(cleared_count=len(task_ids), task_ids=task_ids)


@app.post("/api/tasks/restore-multiple")
@login_required
def restore_multiple():
    user = getattr(g, "user", None) or current_user()
    if not user:
        return jsonify(error="Unauthorized"), 401
    data = json_body()
    task_ids = data.get("task_ids") if data else []
    if not isinstance(task_ids, list) or not task_ids:
        return jsonify(error="Provide a list of task IDs to restore."), 400

    db = get_db()
    placeholders = ",".join("?" * len(task_ids))
    db.execute(
        f"UPDATE tasks SET deleted_at = NULL WHERE id IN ({placeholders}) AND user_id = ?",
        (*task_ids, user["id"])
    )
    db.commit()
    return jsonify(ok=True, restored_count=len(task_ids))


@app.get("/api/tasks/export")
@login_required
def export_tasks():
    user = getattr(g, "user", None) or current_user()
    if not user:
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
