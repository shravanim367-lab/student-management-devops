import os
import sqlite3
import time
from pathlib import Path
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template
from flask import request, url_for
from prometheus_client import Counter, Histogram, generate_latest
from prometheus_client import CONTENT_TYPE_LATEST

app = Flask(__name__)

DATABASE = os.getenv("DATABASE_PATH", "students.db")
Path(DATABASE).parent.mkdir(parents=True, exist_ok=True)

REQUESTS = Counter(
    "student_app_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

LATENCY = Histogram(
    "student_app_request_duration_seconds",
    "HTTP request duration in seconds",
)

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                roll_number TEXT NOT NULL UNIQUE,
                course TEXT NOT NULL
            )
        """)
        g.db.commit()
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.before_request
def start_timer():
    g.request_start = time.perf_counter()

@app.after_request
def record_metrics(response):
    if request.endpoint != "metrics":
        duration = time.perf_counter() - getattr(
            g, "request_start", time.perf_counter()
        )
        LATENCY.observe(duration)
        REQUESTS.labels(
            request.method,
            request.endpoint or "unknown",
            str(response.status_code),
        ).inc()
    return response

@app.get("/")
def index():
    students = get_db().execute(
        "SELECT * FROM students ORDER BY id DESC"
    ).fetchall()
    return render_template("index.html", students=students)

@app.post("/students")
def add_student():
    name = request.form.get("name", "").strip()
    roll_number = request.form.get("roll_number", "").strip()
    course = request.form.get("course", "").strip()

    if not name or not roll_number or not course:
        return "All fields are required", 400

    try:
        db = get_db()
        db.execute(
            "INSERT INTO students (name, roll_number, course) "
            "VALUES (?, ?, ?)",
            (name, roll_number, course),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return "Roll number already exists", 409

    return redirect(url_for("index"))

@app.post("/students/<int:student_id>/update")
def update_student(student_id):
    name = request.form.get("name", "").strip()
    roll_number = request.form.get("roll_number", "").strip()
    course = request.form.get("course", "").strip()

    if not name or not roll_number or not course:
        return "All fields are required", 400

    db = get_db()
    cursor = db.execute(
        "UPDATE students SET name=?, roll_number=?, course=? "
        "WHERE id=?",
        (name, roll_number, course, student_id),
    )

    try:
        db.commit()
    except sqlite3.IntegrityError:
        return "Roll number already exists", 409

    if cursor.rowcount == 0:
        return "Student not found", 404

    return redirect(url_for("index"))

@app.post("/students/<int:student_id>/delete")
def delete_student(student_id):
    db = get_db()
    cursor = db.execute(
        "DELETE FROM students WHERE id=?", (student_id,)
    )
    db.commit()

    if cursor.rowcount == 0:
        return "Student not found", 404

    return redirect(url_for("index"))

@app.get("/health")
def health():
    get_db().execute("SELECT 1").fetchone()
    return jsonify(status="UP"), 200

@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {
        "Content-Type": CONTENT_TYPE_LATEST
    }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)