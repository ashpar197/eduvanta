"""
EDUVANTA - Smart Study App (Enhanced)
======================================
Features: Login, YouTube Video Search, Quiz, Notes,
          Study Timetable with Breaks, To-Do Checklist,
          Performance Report
Run: python app.py
Visit: http://localhost:5000
"""

import os
import re
import json
from flask import Flask, request, jsonify, render_template_string, session
from flask_cors import CORS
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "eduvanta_secret_2024"
CORS(app)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# ── In-memory stores ──────────────────────────────────────────────────────────
notes_store = []
note_id_counter = 1

# Simple user store (username -> password)
USERS = {}

# Per-user performance data
user_data = {}  # username -> { quiz_scores: [], study_hours: [], todos: [] }

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_youtube_client():
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY not found in .env file.")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

def format_duration(iso_duration):
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        return "N/A"
    hours, minutes, seconds = [int(x or 0) for x in match.groups()]
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"

def format_count(count_str):
    try:
        n = int(count_str)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)
    except:
        return "N/A"

def get_user():
    return session.get("username")

def init_user(username):
    if username not in user_data:
        user_data[username] = {"quiz_scores": [], "study_hours": [], "todos": []}

# ── AUTH ROUTES ───────────────────────────────────────────────────────────────
@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if username in USERS:
        return jsonify({"error": "Username already taken"}), 400
    USERS[username] = password
    init_user(username)
    session["username"] = username
    return jsonify({"success": True, "username": username})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if USERS.get(username) != password:
        return jsonify({"error": "Invalid username or password"}), 401
    init_user(username)
    session["username"] = username
    return jsonify({"success": True, "username": username})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("username", None)
    return jsonify({"success": True})

@app.route("/api/me")
def me():
    u = get_user()
    return jsonify({"username": u} if u else {"username": None})

# ── VIDEO SEARCH ──────────────────────────────────────────────────────────────
@app.route("/api/search")
def search_videos():
    topic = request.args.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "Missing topic"}), 400
    try:
        youtube = get_youtube_client()
        search_response = youtube.search().list(
            q=f"{topic} tutorial explained",
            part="id,snippet", type="video",
            videoCategoryId="27", relevanceLanguage="en",
            maxResults=8, safeSearch="strict", order="relevance",
        ).execute()
        video_ids = [i["id"]["videoId"] for i in search_response.get("items", [])]
        if not video_ids:
            return jsonify({"videos": []})
        details = youtube.videos().list(
            part="contentDetails,statistics,snippet",
            id=",".join(video_ids)
        ).execute()
        results = []
        for item in details.get("items", []):
            s = item["snippet"]
            results.append({
                "video_id":  item["id"],
                "title":     s["title"],
                "channel":   s["channelTitle"],
                "thumbnail": s["thumbnails"].get("high", {}).get("url", ""),
                "duration":  format_duration(item.get("contentDetails", {}).get("duration", "PT0S")),
                "views":     format_count(item.get("statistics", {}).get("viewCount", "0")),
                "url":       f"https://www.youtube.com/watch?v={item['id']}",
            })
        return jsonify({"topic": topic, "videos": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── NOTES ─────────────────────────────────────────────────────────────────────
@app.route("/api/notes", methods=["GET"])
def get_notes():
    return jsonify(notes_store)

@app.route("/api/notes", methods=["POST"])
def add_note():
    global note_id_counter
    data = request.json
    note = {
        "id": note_id_counter,
        "title": data.get("title", "Untitled"),
        "content": data.get("content", ""),
    }
    notes_store.append(note)
    note_id_counter += 1
    return jsonify({"success": True, "note": note})

@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    global notes_store
    notes_store = [n for n in notes_store if n["id"] != note_id]
    return jsonify({"success": True})

# ── QUIZ ──────────────────────────────────────────────────────────────────────
@app.route("/api/quiz")
def get_quiz():
    topic = request.args.get("topic", "general").lower()
    questions = QUIZ_BANK.get(topic, QUIZ_BANK["general"])
    return jsonify({"topic": topic, "questions": questions})

@app.route("/api/quiz/save", methods=["POST"])
def save_quiz_score():
    u = get_user()
    if not u:
        return jsonify({"error": "Not logged in"}), 401
    data = request.json
    user_data[u]["quiz_scores"].append({
        "topic": data.get("topic"),
        "score": data.get("score"),
        "total": data.get("total"),
        "pct":   data.get("pct"),
    })
    return jsonify({"success": True})

# ── TODOS ─────────────────────────────────────────────────────────────────────
@app.route("/api/todos", methods=["GET"])
def get_todos():
    u = get_user()
    if not u:
        return jsonify([])
    return jsonify(user_data[u]["todos"])

@app.route("/api/todos", methods=["POST"])
def add_todo():
    u = get_user()
    if not u:
        return jsonify({"error": "Not logged in"}), 401
    data = request.json
    task = {
        "id": len(user_data[u]["todos"]) + 1,
        "text": data.get("text", ""),
        "done": False,
    }
    user_data[u]["todos"].append(task)
    return jsonify({"success": True, "todo": task})

@app.route("/api/todos/<int:todo_id>/toggle", methods=["POST"])
def toggle_todo(todo_id):
    u = get_user()
    if not u:
        return jsonify({"error": "Not logged in"}), 401
    for t in user_data[u]["todos"]:
        if t["id"] == todo_id:
            t["done"] = not t["done"]
            break
    return jsonify({"success": True})

@app.route("/api/todos/<int:todo_id>", methods=["DELETE"])
def delete_todo(todo_id):
    u = get_user()
    if not u:
        return jsonify({"error": "Not logged in"}), 401
    user_data[u]["todos"] = [t for t in user_data[u]["todos"] if t["id"] != todo_id]
    return jsonify({"success": True})

# ── STUDY HOURS ───────────────────────────────────────────────────────────────
@app.route("/api/study-hours", methods=["POST"])
def log_study_hours():
    u = get_user()
    if not u:
        return jsonify({"error": "Not logged in"}), 401
    data = request.json
    user_data[u]["study_hours"].append(data.get("hours", 0))
    return jsonify({"success": True})

# ── PERFORMANCE ───────────────────────────────────────────────────────────────
@app.route("/api/performance")
def performance():
    u = get_user()
    if not u:
        return jsonify({"error": "Not logged in"}), 401
    d = user_data[u]
    todos = d["todos"]
    total_todos = len(todos)
    done_todos = sum(1 for t in todos if t["done"])
    todo_pct = round(done_todos / total_todos * 100) if total_todos else 0

    scores = d["quiz_scores"]
    avg_quiz = round(sum(s["pct"] for s in scores) / len(scores)) if scores else 0

    hours = d["study_hours"]
    total_hours = round(sum(hours), 1)

    # Simple grade based on composite
    composite = (todo_pct * 0.4 + avg_quiz * 0.4 + min(total_hours / 20 * 100, 100) * 0.2)
    if composite >= 85:
        grade = "A"
        msg = "Outstanding! You're on top of your studies. 🏆"
    elif composite >= 70:
        grade = "B"
        msg = "Great work! Keep the momentum going. 💪"
    elif composite >= 55:
        grade = "C"
        msg = "Good effort! A bit more consistency will help. 📚"
    elif composite >= 40:
        grade = "D"
        msg = "You're getting there. Try to study more regularly. 🌱"
    else:
        grade = "F"
        msg = "Don't give up! Start small — even 30 min a day makes a difference. 🌟"

    return jsonify({
        "todo_pct": todo_pct,
        "done_todos": done_todos,
        "total_todos": total_todos,
        "avg_quiz": avg_quiz,
        "quiz_count": len(scores),
        "total_hours": total_hours,
        "sessions": len(hours),
        "grade": grade,
        "message": msg,
        "composite": round(composite),
    })

# ── MAIN ROUTE ────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template_string(HTML_PAGE)

# ── QUIZ BANK ─────────────────────────────────────────────────────────────────
QUIZ_BANK = {
    "general": [
        {"q": "What does CPU stand for?", "options": ["Central Processing Unit", "Computer Personal Unit", "Central Program Utility", "Core Processing Unit"], "answer": 0},
        {"q": "Which planet is closest to the Sun?", "options": ["Venus", "Earth", "Mercury", "Mars"], "answer": 2},
        {"q": "What is H2O commonly known as?", "options": ["Hydrogen", "Oxygen", "Salt", "Water"], "answer": 3},
        {"q": "How many sides does a hexagon have?", "options": ["5", "6", "7", "8"], "answer": 1},
        {"q": "What is the capital of France?", "options": ["Berlin", "Madrid", "Paris", "Rome"], "answer": 2},
    ],
    "python": [
        {"q": "Which keyword defines a function in Python?", "options": ["func", "define", "def", "fun"], "answer": 2},
        {"q": "What does len() return?", "options": ["Last element", "Length of object", "List of elements", "None"], "answer": 1},
        {"q": "Which of these is a Python data type?", "options": ["integer", "int", "number", "whole"], "answer": 1},
        {"q": "What symbol is used for comments in Python?", "options": ["//", "/*", "#", "--"], "answer": 2},
        {"q": "What does print() do?", "options": ["Saves to file", "Displays output", "Creates variable", "Loops code"], "answer": 1},
    ],
    "math": [
        {"q": "What is 12 × 12?", "options": ["132", "144", "124", "148"], "answer": 1},
        {"q": "What is the square root of 81?", "options": ["7", "8", "9", "10"], "answer": 2},
        {"q": "What is 15% of 200?", "options": ["25", "30", "35", "20"], "answer": 1},
        {"q": "What is the value of π (pi) approximately?", "options": ["2.14", "3.14", "4.14", "1.14"], "answer": 1},
        {"q": "What is 2 to the power of 8?", "options": ["128", "512", "256", "64"], "answer": 2},
    ],
}

# ── HTML PAGE ─────────────────────────────────────────────────────────────────
HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Eduvanta</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;1,300&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #13131a;
    --card: #1a1a24;
    --border: #2a2a3a;
    --accent: #7c6af7;
    --accent2: #f7c26a;
    --text: #f0f0f8;
    --muted: #7a7a9a;
    --green: #5de0a0;
    --red: #f76a6a;
    --blue: #6ab0f7;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: 'DM Sans', sans-serif; min-height: 100vh; }

  /* ── LOGIN / REGISTER ── */
  #auth-screen {
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: radial-gradient(ellipse at 30% 20%, rgba(124,106,247,0.15) 0%, transparent 60%),
                radial-gradient(ellipse at 80% 80%, rgba(247,194,106,0.08) 0%, transparent 60%), var(--bg);
  }
  .auth-box {
    background: var(--surface); border: 1px solid var(--border); border-radius: 24px;
    padding: 3rem 2.5rem; width: 100%; max-width: 420px; text-align: center;
    box-shadow: 0 40px 80px rgba(0,0,0,0.5);
  }
  .auth-logo { font-family: 'Syne', sans-serif; font-size: 2rem; font-weight: 800; color: var(--accent); margin-bottom: 0.25rem; }
  .auth-logo span { color: var(--accent2); }
  .auth-subtitle { color: var(--muted); font-size: 0.9rem; margin-bottom: 2rem; }
  .auth-tabs { display: flex; background: var(--bg); border-radius: 12px; padding: 4px; margin-bottom: 2rem; }
  .auth-tab { flex: 1; padding: 0.6rem; border: none; background: none; color: var(--muted); font-family: 'Syne', sans-serif; font-size: 0.85rem; font-weight: 600; cursor: pointer; border-radius: 8px; transition: all 0.2s; }
  .auth-tab.active { background: var(--accent); color: white; }
  .auth-input { width: 100%; background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 0.9rem 1.2rem; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 0.95rem; outline: none; margin-bottom: 0.9rem; transition: border 0.2s; }
  .auth-input:focus { border-color: var(--accent); }
  .auth-input::placeholder { color: var(--muted); }
  .auth-btn { width: 100%; background: var(--accent); color: white; border: none; border-radius: 12px; padding: 0.95rem; font-family: 'Syne', sans-serif; font-weight: 700; font-size: 1rem; cursor: pointer; transition: all 0.2s; margin-top: 0.25rem; }
  .auth-btn:hover { opacity: 0.85; transform: translateY(-1px); }
  .auth-error { color: var(--red); font-size: 0.85rem; margin-bottom: 0.75rem; display: none; }

  /* ── APP SHELL ── */
  #app-shell { display: none; }

  nav {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 0 1.5rem; display: flex; align-items: center; gap: 0.5rem;
    height: 60px; position: sticky; top: 0; z-index: 100; overflow-x: auto;
  }
  .logo { font-family: 'Syne', sans-serif; font-weight: 800; font-size: 1.3rem; color: var(--accent); letter-spacing: -0.5px; margin-right: auto; white-space: nowrap; }
  .logo span { color: var(--accent2); }
  .nav-btn { background: none; border: none; color: var(--muted); font-family: 'DM Sans', sans-serif; font-size: 0.85rem; padding: 6px 12px; border-radius: 8px; cursor: pointer; transition: all 0.2s; white-space: nowrap; }
  .nav-btn:hover, .nav-btn.active { background: var(--accent); color: white; }
  .nav-user { color: var(--accent2); font-size: 0.8rem; font-family: 'Syne', sans-serif; font-weight: 600; white-space: nowrap; }
  .nav-logout { background: none; border: 1px solid var(--border); color: var(--muted); font-size: 0.8rem; padding: 4px 10px; border-radius: 8px; cursor: pointer; transition: all 0.2s; font-family: 'DM Sans', sans-serif; }
  .nav-logout:hover { border-color: var(--red); color: var(--red); }

  .page { display: none; padding: 2rem; max-width: 1040px; margin: 0 auto; animation: fadeIn 0.3s ease; }
  .page.active { display: block; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

  /* HERO */
  .hero { text-align: center; padding: 4rem 1rem 3rem; }
  .hero h1 { font-family: 'Syne', sans-serif; font-size: 3.5rem; font-weight: 800; line-height: 1.1; margin-bottom: 1rem; }
  .hero h1 span { color: var(--accent); }
  .hero p { color: var(--muted); font-size: 1.1rem; margin-bottom: 2.5rem; }
  .hero-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 1rem; max-width: 700px; margin: 0 auto; }
  .hero-card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem 1rem; cursor: pointer; transition: all 0.2s; text-align: center; }
  .hero-card:hover { border-color: var(--accent); transform: translateY(-3px); }
  .hero-card .icon { font-size: 2rem; margin-bottom: 0.5rem; }
  .hero-card h3 { font-family: 'Syne', sans-serif; font-size: 0.9rem; }

  .section-title { font-family: 'Syne', sans-serif; font-size: 1.8rem; font-weight: 700; margin-bottom: 1.5rem; }
  .section-title span { color: var(--accent); }

  .search-row { display: flex; gap: 0.75rem; margin-bottom: 2rem; }
  .search-input { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 0.85rem 1.2rem; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 1rem; outline: none; transition: border 0.2s; }
  .search-input:focus { border-color: var(--accent); }
  .search-input::placeholder { color: var(--muted); }
  .btn { background: var(--accent); color: white; border: none; border-radius: 12px; padding: 0.85rem 1.5rem; font-family: 'Syne', sans-serif; font-weight: 600; font-size: 0.9rem; cursor: pointer; transition: all 0.2s; white-space: nowrap; }
  .btn:hover { opacity: 0.85; transform: translateY(-1px); }
  .btn-green { background: var(--green); color: #0a2a1a; }
  .btn-outline { background: none; border: 1px solid var(--border); color: var(--text); }
  .btn-outline:hover { border-color: var(--accent); color: var(--accent); }
  .btn-danger { background: var(--red); }
  .btn-sm { padding: 0.5rem 1rem; font-size: 0.8rem; border-radius: 8px; }

  .video-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.2rem; }
  .video-card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; transition: all 0.2s; cursor: pointer; text-decoration: none; color: inherit; display: block; }
  .video-card:hover { border-color: var(--accent); transform: translateY(-3px); }
  .video-thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; }
  .video-info { padding: 1rem; }
  .video-title { font-family: 'Syne', sans-serif; font-size: 0.9rem; font-weight: 600; margin-bottom: 0.5rem; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .video-meta { display: flex; gap: 1rem; color: var(--muted); font-size: 0.8rem; }
  .video-channel { color: var(--accent); font-size: 0.8rem; margin-bottom: 0.4rem; }

  .notes-form { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem; margin-bottom: 2rem; }
  .notes-form input, .notes-form textarea { width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.75rem 1rem; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 0.95rem; outline: none; margin-bottom: 0.75rem; transition: border 0.2s; }
  .notes-form input:focus, .notes-form textarea:focus { border-color: var(--accent); }
  .notes-form textarea { resize: vertical; min-height: 100px; }
  .notes-grid { display: grid; gap: 1rem; }
  .note-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 1.2rem; display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; }
  .note-card h4 { font-family: 'Syne', sans-serif; font-weight: 600; margin-bottom: 0.4rem; }
  .note-card p { color: var(--muted); font-size: 0.9rem; line-height: 1.5; }
  .note-del { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1.2rem; transition: color 0.2s; flex-shrink: 0; }
  .note-del:hover { color: var(--red); }

  .quiz-setup { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 2rem; max-width: 500px; }
  .quiz-setup label { display: block; color: var(--muted); font-size: 0.85rem; margin-bottom: 0.4rem; text-transform: uppercase; letter-spacing: 0.5px; }
  .quiz-setup select { width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.75rem 1rem; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 0.95rem; outline: none; margin-bottom: 1.2rem; cursor: pointer; }
  .quiz-box { max-width: 600px; }
  .quiz-progress { color: var(--muted); font-size: 0.85rem; margin-bottom: 0.5rem; }
  .progress-bar { background: var(--border); border-radius: 99px; height: 4px; margin-bottom: 2rem; }
  .progress-fill { background: var(--accent); height: 100%; border-radius: 99px; transition: width 0.4s; }
  .quiz-question { font-family: 'Syne', sans-serif; font-size: 1.3rem; font-weight: 600; margin-bottom: 1.5rem; line-height: 1.4; }
  .quiz-options { display: grid; gap: 0.75rem; }
  .quiz-option { background: var(--card); border: 1.5px solid var(--border); border-radius: 12px; padding: 1rem 1.25rem; cursor: pointer; transition: all 0.2s; text-align: left; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 0.95rem; }
  .quiz-option:hover:not(:disabled) { border-color: var(--accent); background: rgba(124,106,247,0.08); }
  .quiz-option.correct { border-color: var(--green); background: rgba(93,224,160,0.1); color: var(--green); }
  .quiz-option.wrong { border-color: var(--red); background: rgba(247,106,106,0.1); color: var(--red); }
  .quiz-result { text-align: center; padding: 3rem 1rem; }
  .quiz-score { font-family: 'Syne', sans-serif; font-size: 4rem; font-weight: 800; color: var(--accent); }
  .quiz-result p { color: var(--muted); margin: 0.5rem 0 2rem; }

  /* ── TIMETABLE ── */
  .tt-setup { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 2rem; margin-bottom: 2rem; }
  .tt-setup h3 { font-family: 'Syne', sans-serif; font-weight: 700; font-size: 1.1rem; margin-bottom: 1.2rem; }
  .tt-row { display: flex; gap: 1rem; flex-wrap: wrap; align-items: flex-end; margin-bottom: 1rem; }
  .tt-field { display: flex; flex-direction: column; gap: 0.4rem; }
  .tt-field label { color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; }
  .tt-field input, .tt-field select { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.7rem 1rem; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 0.9rem; outline: none; transition: border 0.2s; width: 150px; }
  .tt-field input:focus, .tt-field select:focus { border-color: var(--accent); }
  .subjects-input { width: 100% !important; }
  .timetable-grid { display: grid; gap: 0; border: 1px solid var(--border); border-radius: 16px; overflow: hidden; }
  .tt-slot { display: grid; grid-template-columns: 120px 1fr 80px; align-items: center; border-bottom: 1px solid var(--border); background: var(--card); transition: background 0.2s; }
  .tt-slot:last-child { border-bottom: none; }
  .tt-slot.break-slot { background: rgba(247,194,106,0.06); }
  .tt-slot.study-slot { background: rgba(124,106,247,0.04); }
  .tt-time { padding: 0.85rem 1rem; color: var(--muted); font-size: 0.8rem; font-family: 'Syne', sans-serif; border-right: 1px solid var(--border); }
  .tt-label { padding: 0.85rem 1.2rem; font-size: 0.9rem; }
  .tt-badge { padding: 0.85rem 1rem; }
  .badge { font-size: 0.7rem; padding: 2px 8px; border-radius: 99px; font-family: 'Syne', sans-serif; font-weight: 600; }
  .badge-study { background: rgba(124,106,247,0.2); color: var(--accent); }
  .badge-break { background: rgba(247,194,106,0.2); color: var(--accent2); }

  /* ── TO-DO ── */
  .todo-add { display: flex; gap: 0.75rem; margin-bottom: 1.5rem; }
  .todo-input { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 0.85rem 1.2rem; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 0.95rem; outline: none; transition: border 0.2s; }
  .todo-input:focus { border-color: var(--accent); }
  .todo-input::placeholder { color: var(--muted); }
  .todo-list { display: grid; gap: 0.6rem; }
  .todo-item { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1rem 1.2rem; display: flex; align-items: center; gap: 1rem; transition: all 0.2s; }
  .todo-item.done { opacity: 0.5; }
  .todo-item.done .todo-text { text-decoration: line-through; color: var(--muted); }
  .todo-check { width: 20px; height: 20px; border: 2px solid var(--border); border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all 0.2s; background: none; }
  .todo-check.checked { background: var(--green); border-color: var(--green); }
  .todo-check.checked::after { content: '✓'; color: #0a2a1a; font-size: 0.8rem; font-weight: 700; }
  .todo-text { flex: 1; font-size: 0.95rem; }
  .todo-del { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1rem; transition: color 0.2s; }
  .todo-del:hover { color: var(--red); }
  .todo-stats { display: flex; gap: 1rem; margin-bottom: 1.5rem; }
  .todo-stat { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 0.75rem 1.2rem; font-size: 0.85rem; }
  .todo-stat strong { color: var(--accent); font-family: 'Syne', sans-serif; font-size: 1.2rem; display: block; }

  /* ── PERFORMANCE ── */
  .perf-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
  .perf-card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem; text-align: center; }
  .perf-card .perf-icon { font-size: 2.2rem; margin-bottom: 0.5rem; }
  .perf-card .perf-val { font-family: 'Syne', sans-serif; font-size: 2.5rem; font-weight: 800; color: var(--accent); line-height: 1; }
  .perf-card .perf-label { color: var(--muted); font-size: 0.8rem; margin-top: 0.3rem; }
  .grade-card { background: linear-gradient(135deg, rgba(124,106,247,0.2), rgba(124,106,247,0.05)); border-color: rgba(124,106,247,0.4); }
  .grade-val { font-size: 5rem !important; }
  .perf-msg { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem; margin-bottom: 2rem; text-align: center; }
  .perf-msg p { color: var(--muted); font-size: 1rem; }
  .perf-bars { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem; }
  .perf-bars h4 { font-family: 'Syne', sans-serif; font-weight: 600; margin-bottom: 1.2rem; }
  .bar-row { margin-bottom: 1rem; }
  .bar-label { display: flex; justify-content: space-between; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.4rem; }
  .bar-track { background: var(--border); border-radius: 99px; height: 8px; }
  .bar-fill { height: 100%; border-radius: 99px; transition: width 0.8s ease; }
  .bar-green { background: var(--green); }
  .bar-purple { background: var(--accent); }
  .bar-gold { background: var(--accent2); }

  .log-hours-box { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem; margin-bottom: 2rem; }
  .log-hours-box h4 { font-family: 'Syne', sans-serif; font-weight: 600; margin-bottom: 1rem; }
  .hours-row { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
  .hours-input { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.7rem 1rem; color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 0.95rem; outline: none; width: 140px; transition: border 0.2s; }
  .hours-input:focus { border-color: var(--accent); }

  .loading { text-align: center; padding: 3rem; color: var(--muted); }
  .spinner { width: 36px; height: 36px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 1rem; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .empty { text-align: center; padding: 3rem; color: var(--muted); }
  .empty .icon { font-size: 3rem; margin-bottom: 1rem; }
  .tag { display: inline-block; background: rgba(124,106,247,0.15); color: var(--accent); font-size: 0.75rem; padding: 2px 10px; border-radius: 99px; margin-bottom: 1rem; font-family: 'Syne', sans-serif; font-weight: 600; letter-spacing: 0.5px; }
</style>
</head>
<body>

<!-- ── AUTH SCREEN ─────────────────────────────────────────────── -->
<div id="auth-screen">
  <div class="auth-box">
    <div class="auth-logo">Edu<span>vanta</span></div>
    <div class="auth-subtitle">Your smart study companion</div>
    <div class="auth-tabs">
      <button class="auth-tab active" onclick="switchAuthTab('login')">Login</button>
      <button class="auth-tab" onclick="switchAuthTab('register')">Register</button>
    </div>
    <div id="auth-error" class="auth-error">Invalid credentials. Please try again.</div>
    <input class="auth-input" id="auth-username" type="text" placeholder="Username" autocomplete="username">
    <input class="auth-input" id="auth-password" type="password" placeholder="Password" autocomplete="current-password"
           onkeydown="if(event.key==='Enter') submitAuth()">
    <button class="auth-btn" onclick="submitAuth()" id="auth-submit-btn">Login →</button>
  </div>
</div>

<!-- ── APP SHELL ───────────────────────────────────────────────── -->
<div id="app-shell">
<nav>
  <div class="logo">Edu<span>vanta</span></div>
  <button class="nav-btn active" onclick="showPage('home', this)">🏠 Home</button>
  <button class="nav-btn" onclick="showPage('videos', this)">📹 Videos</button>
  <button class="nav-btn" onclick="showPage('notes', this)">📝 Notes</button>
  <button class="nav-btn" onclick="showPage('quiz', this)">🧠 Quiz</button>
  <button class="nav-btn" onclick="showPage('timetable', this)">🗓 Timetable</button>
  <button class="nav-btn" onclick="showPage('todo', this)">✅ To-Do</button>
  <button class="nav-btn" onclick="showPage('report', this); loadReport()">📊 Report</button>
  <span class="nav-user" id="nav-username"></span>
  <button class="nav-logout" onclick="logout()">Logout</button>
</nav>

<!-- HOME -->
<div id="page-home" class="page active">
  <div class="hero">
    <div class="tag">Your Smart Study Companion</div>
    <h1>Study Smarter<br>with <span>Eduvanta</span></h1>
    <p id="hero-greeting">Welcome back! Ready to learn?</p>
    <div class="hero-cards">
      <div class="hero-card" onclick="nav('videos')"><div class="icon">📹</div><h3>Video Search</h3></div>
      <div class="hero-card" onclick="nav('notes')"><div class="icon">📝</div><h3>My Notes</h3></div>
      <div class="hero-card" onclick="nav('quiz')"><div class="icon">🧠</div><h3>Quick Quiz</h3></div>
      <div class="hero-card" onclick="nav('timetable')"><div class="icon">🗓</div><h3>Timetable</h3></div>
      <div class="hero-card" onclick="nav('todo')"><div class="icon">✅</div><h3>To-Do List</h3></div>
      <div class="hero-card" onclick="nav('report'); loadReport()"><div class="icon">📊</div><h3>My Report</h3></div>
    </div>
  </div>
</div>

<!-- VIDEOS -->
<div id="page-videos" class="page">
  <div class="section-title">📹 Find <span>Study Videos</span></div>
  <div class="search-row">
    <input class="search-input" id="videoSearch" placeholder="Search any topic… e.g. python, photosynthesis" onkeydown="if(event.key==='Enter') searchVideos()">
    <button class="btn" onclick="searchVideos()">Search</button>
  </div>
  <div id="videoResults"></div>
</div>

<!-- NOTES -->
<div id="page-notes" class="page">
  <div class="section-title">📝 My <span>Notes</span></div>
  <div class="notes-form">
    <input id="noteTitle" placeholder="Note title…">
    <textarea id="noteContent" placeholder="Write your notes here…"></textarea>
    <button class="btn" onclick="saveNote()">Save Note</button>
  </div>
  <div id="notesList"></div>
</div>

<!-- QUIZ -->
<div id="page-quiz" class="page">
  <div class="section-title">🧠 Quick <span>Quiz</span></div>
  <div id="quizArea">
    <div class="quiz-setup">
      <label>Choose a Topic</label>
      <select id="quizTopic">
        <option value="general">🌍 General Knowledge</option>
        <option value="python">🐍 Python Programming</option>
        <option value="math">📐 Mathematics</option>
      </select>
      <button class="btn" onclick="startQuiz()">Start Quiz →</button>
    </div>
  </div>
</div>

<!-- TIMETABLE -->
<div id="page-timetable" class="page">
  <div class="section-title">🗓 Study <span>Timetable</span></div>
  <div class="tt-setup">
    <h3>⚙️ Build Your Schedule</h3>
    <div class="tt-row">
      <div class="tt-field">
        <label>Start Time</label>
        <input type="time" id="tt-start" value="09:00">
      </div>
      <div class="tt-field">
        <label>Total Study Hours</label>
        <input type="number" id="tt-hours" min="1" max="12" value="4" style="width:100px">
      </div>
      <div class="tt-field">
        <label>Session Length (min)</label>
        <input type="number" id="tt-session" min="15" max="120" value="50" style="width:100px">
      </div>
      <div class="tt-field">
        <label>Break Length (min)</label>
        <input type="number" id="tt-break" min="5" max="30" value="10" style="width:100px">
      </div>
    </div>
    <div class="tt-row">
      <div class="tt-field" style="flex:1">
        <label>Subjects (comma-separated)</label>
        <input class="subjects-input" id="tt-subjects" placeholder="e.g. Math, Science, English, History" style="width:100%">
      </div>
    </div>
    <button class="btn" onclick="buildTimetable()">Generate Timetable →</button>
  </div>
  <div id="tt-output"></div>
</div>

<!-- TO-DO -->
<div id="page-todo" class="page">
  <div class="section-title">✅ Study <span>To-Do</span></div>
  <div class="todo-add">
    <input class="todo-input" id="todo-input" placeholder="Add a study task…" onkeydown="if(event.key==='Enter') addTodo()">
    <button class="btn btn-green" onclick="addTodo()">+ Add</button>
  </div>
  <div class="todo-stats" id="todo-stats"></div>
  <div class="todo-list" id="todo-list"><div class="empty"><div class="icon">📋</div>No tasks yet. Add one above!</div></div>
</div>

<!-- PERFORMANCE REPORT -->
<div id="page-report" class="page">
  <div class="section-title">📊 Performance <span>Report</span></div>
  <div class="log-hours-box">
    <h4>⏱ Log Today's Study Session</h4>
    <div class="hours-row">
      <input class="hours-input" type="number" id="hours-log" min="0.5" max="16" step="0.5" placeholder="Hours studied">
      <button class="btn" onclick="logHours()">Log Hours</button>
    </div>
  </div>
  <div id="report-content"><div class="empty"><div class="icon">📊</div>No data yet. Complete quizzes, tasks, and log study hours!</div></div>
</div>

</div><!-- /app-shell -->

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let currentUser = null;
let authMode = 'login';
let quizQuestions = [], quizIndex = 0, quizScore = 0, answered = false;
let currentQuizTopic = 'general';

// ── Boot ──────────────────────────────────────────────────────────────────────
(async function boot() {
  const r = await fetch('/api/me');
  const d = await r.json();
  if (d.username) {
    currentUser = d.username;
    showApp();
  }
})();

function showApp() {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('app-shell').style.display = 'block';
  document.getElementById('nav-username').textContent = '👤 ' + currentUser;
  document.getElementById('hero-greeting').textContent = `Welcome back, ${currentUser}! Ready to learn?`;
  loadTodos();
}

// ── Auth ──────────────────────────────────────────────────────────────────────
function switchAuthTab(mode) {
  authMode = mode;
  document.querySelectorAll('.auth-tab').forEach((t,i) => {
    t.classList.toggle('active', (i === 0 && mode === 'login') || (i === 1 && mode === 'register'));
  });
  document.getElementById('auth-submit-btn').textContent = mode === 'login' ? 'Login →' : 'Create Account →';
  document.getElementById('auth-error').style.display = 'none';
}

async function submitAuth() {
  const username = document.getElementById('auth-username').value.trim();
  const password = document.getElementById('auth-password').value;
  if (!username || !password) { showAuthError('Please enter both username and password.'); return; }
  const url = authMode === 'login' ? '/api/login' : '/api/register';
  const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username, password}) });
  const d = await r.json();
  if (d.error) { showAuthError(d.error); return; }
  currentUser = d.username;
  showApp();
}

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  el.textContent = msg;
  el.style.display = 'block';
}

async function logout() {
  await fetch('/api/logout', {method:'POST'});
  currentUser = null;
  document.getElementById('auth-screen').style.display = 'flex';
  document.getElementById('app-shell').style.display = 'none';
  document.getElementById('auth-username').value = '';
  document.getElementById('auth-password').value = '';
}

// ── Navigation ────────────────────────────────────────────────────────────────
function showPage(name, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  if (btn) btn.classList.add('active');
  if (name === 'notes') loadNotes();
  if (name === 'todo') loadTodos();
}

function nav(name) {
  showPage(name);
  document.querySelectorAll('.nav-btn').forEach(b => {
    if (b.textContent.toLowerCase().includes(name.slice(0,4).toLowerCase())) b.classList.add('active');
  });
}

// ── VIDEOS ────────────────────────────────────────────────────────────────────
async function searchVideos() {
  const topic = document.getElementById('videoSearch').value.trim();
  if (!topic) return;
  const el = document.getElementById('videoResults');
  el.innerHTML = '<div class="loading"><div class="spinner"></div>Searching YouTube…</div>';
  try {
    const res = await fetch(`/api/search?topic=${encodeURIComponent(topic)}`);
    const data = await res.json();
    if (data.error) { el.innerHTML = `<div class="empty"><div class="icon">⚠️</div>${data.error}</div>`; return; }
    if (!data.videos.length) { el.innerHTML = '<div class="empty"><div class="icon">🔍</div>No videos found.</div>'; return; }
    el.innerHTML = `<div class="video-grid">${data.videos.map(v => `
      <a class="video-card" href="${v.url}" target="_blank">
        <img class="video-thumb" src="${v.thumbnail}" alt="${v.title}" loading="lazy">
        <div class="video-info">
          <div class="video-channel">${v.channel}</div>
          <div class="video-title">${v.title}</div>
          <div class="video-meta"><span>⏱ ${v.duration}</span><span>👁 ${v.views}</span></div>
        </div>
      </a>`).join('')}</div>`;
  } catch { el.innerHTML = '<div class="empty"><div class="icon">⚠️</div>Could not connect. Is the server running?</div>'; }
}

// ── NOTES ─────────────────────────────────────────────────────────────────────
async function saveNote() {
  const title = document.getElementById('noteTitle').value.trim();
  const content = document.getElementById('noteContent').value.trim();
  if (!title || !content) { alert('Please fill in both title and content!'); return; }
  await fetch('/api/notes', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title, content}) });
  document.getElementById('noteTitle').value = '';
  document.getElementById('noteContent').value = '';
  loadNotes();
}

async function loadNotes() {
  const res = await fetch('/api/notes');
  const notes = await res.json();
  const el = document.getElementById('notesList');
  if (!notes.length) { el.innerHTML = '<div class="empty"><div class="icon">📭</div>No notes yet.</div>'; return; }
  el.innerHTML = `<div class="notes-grid">${notes.map(n => `
    <div class="note-card">
      <div><h4>${n.title}</h4><p>${n.content}</p></div>
      <button class="note-del" onclick="deleteNote(${n.id})">🗑</button>
    </div>`).join('')}</div>`;
}

async function deleteNote(id) {
  await fetch(`/api/notes/${id}`, {method:'DELETE'});
  loadNotes();
}

// ── QUIZ ──────────────────────────────────────────────────────────────────────
async function startQuiz() {
  currentQuizTopic = document.getElementById('quizTopic').value;
  const res = await fetch(`/api/quiz?topic=${currentQuizTopic}`);
  const data = await res.json();
  quizQuestions = data.questions;
  quizIndex = 0; quizScore = 0;
  showQuestion();
}

function showQuestion() {
  if (quizIndex >= quizQuestions.length) { showResult(); return; }
  answered = false;
  const q = quizQuestions[quizIndex];
  const pct = (quizIndex / quizQuestions.length * 100).toFixed(0);
  document.getElementById('quizArea').innerHTML = `
    <div class="quiz-box">
      <div class="quiz-progress">Question ${quizIndex+1} of ${quizQuestions.length}</div>
      <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
      <div class="quiz-question">${q.q}</div>
      <div class="quiz-options">
        ${q.options.map((opt, i) => `<button class="quiz-option" id="opt${i}" onclick="answer(${i})">${opt}</button>`).join('')}
      </div>
    </div>`;
}

function answer(idx) {
  if (answered) return;
  answered = true;
  const q = quizQuestions[quizIndex];
  const correct = q.answer;
  document.querySelectorAll('.quiz-option').forEach((b, i) => {
    b.disabled = true;
    if (i === correct) b.classList.add('correct');
    else if (i === idx) b.classList.add('wrong');
  });
  if (idx === correct) quizScore++;
  setTimeout(() => { quizIndex++; showQuestion(); }, 1200);
}

async function showResult() {
  const pct = Math.round(quizScore / quizQuestions.length * 100);
  const msg = pct === 100 ? "Perfect score! 🏆" : pct >= 60 ? "Good job! Keep it up 💪" : "Keep studying, you'll get it! 📚";
  // Save to server
  await fetch('/api/quiz/save', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ topic: currentQuizTopic, score: quizScore, total: quizQuestions.length, pct })
  });
  document.getElementById('quizArea').innerHTML = `
    <div class="quiz-result">
      <div class="quiz-score">${quizScore}/${quizQuestions.length}</div>
      <p>${msg}</p>
      <p style="font-size:0.85rem;margin-bottom:1rem;">Score saved to your performance report! 📊</p>
      <button class="btn" onclick="document.getElementById('quizArea').innerHTML='<div class=\\'quiz-setup\\'><label>Choose a Topic</label><select id=\\'quizTopic\\'><option value=\\'general\\'>🌍 General Knowledge</option><option value=\\'python\\'>🐍 Python Programming</option><option value=\\'math\\'>📐 Mathematics</option></select><button class=\\'btn\\' onclick=\\'startQuiz()\\'>Start Quiz →</button></div>'">Try Again</button>
    </div>`;
}

// ── TIMETABLE ─────────────────────────────────────────────────────────────────
function buildTimetable() {
  const startStr = document.getElementById('tt-start').value || '09:00';
  const totalHours = parseFloat(document.getElementById('tt-hours').value) || 4;
  const sessionMin = parseInt(document.getElementById('tt-session').value) || 50;
  const breakMin = parseInt(document.getElementById('tt-break').value) || 10;
  const subjectsRaw = document.getElementById('tt-subjects').value;
  const subjects = subjectsRaw ? subjectsRaw.split(',').map(s=>s.trim()).filter(Boolean) : [];

  const [startH, startM] = startStr.split(':').map(Number);
  let cur = startH * 60 + startM;
  const totalMin = totalHours * 60;
  const slots = [];
  let elapsed = 0;
  let subIdx = 0;

  while (elapsed < totalMin) {
    const remaining = totalMin - elapsed;
    const studyDur = Math.min(sessionMin, remaining);
    const subject = subjects.length ? subjects[subIdx % subjects.length] : '📚 Study Session';
    slots.push({ type:'study', start: cur, dur: studyDur, label: subject });
    cur += studyDur; elapsed += studyDur; subIdx++;
    if (elapsed < totalMin) {
      const bDur = Math.min(breakMin, totalMin - elapsed);
      slots.push({ type:'break', start: cur, dur: bDur, label: '☕ Break' });
      cur += bDur; elapsed += bDur;
    }
  }

  function fmt(min) {
    const h = Math.floor(min/60) % 24;
    const m = min % 60;
    const ampm = h >= 12 ? 'PM' : 'AM';
    return `${h%12||12}:${m.toString().padStart(2,'0')} ${ampm}`;
  }

  const html = slots.map(s => `
    <div class="tt-slot ${s.type}-slot">
      <div class="tt-time">${fmt(s.start)} – ${fmt(s.start+s.dur)}</div>
      <div class="tt-label">${s.label}</div>
      <div class="tt-badge"><span class="badge badge-${s.type}">${s.type === 'study' ? '📖 Study' : '☕ Break'}</span></div>
    </div>`).join('');

  document.getElementById('tt-output').innerHTML = `
    <div style="margin-bottom:0.75rem;color:var(--muted);font-size:0.85rem;">
      ${slots.filter(s=>s.type==='study').length} study sessions · ${slots.filter(s=>s.type==='break').length} breaks · ${totalHours}h total
    </div>
    <div class="timetable-grid">${html}</div>`;

  // Also log hours
  fetch('/api/study-hours', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ hours: totalHours })
  });
}

// ── TO-DO ─────────────────────────────────────────────────────────────────────
async function addTodo() {
  const text = document.getElementById('todo-input').value.trim();
  if (!text) return;
  await fetch('/api/todos', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text}) });
  document.getElementById('todo-input').value = '';
  loadTodos();
}

async function loadTodos() {
  const res = await fetch('/api/todos');
  const todos = await res.json();
  const list = document.getElementById('todo-list');
  const stats = document.getElementById('todo-stats');
  const done = todos.filter(t=>t.done).length;
  const total = todos.length;

  stats.innerHTML = total ? `
    <div class="todo-stat"><strong>${done}</strong>Completed</div>
    <div class="todo-stat"><strong>${total-done}</strong>Remaining</div>
    <div class="todo-stat"><strong>${total ? Math.round(done/total*100) : 0}%</strong>Progress</div>` : '';

  if (!todos.length) { list.innerHTML = '<div class="empty"><div class="icon">📋</div>No tasks yet. Add one above!</div>'; return; }
  list.innerHTML = todos.map(t => `
    <div class="todo-item ${t.done?'done':''}" id="todo-item-${t.id}">
      <button class="todo-check ${t.done?'checked':''}" onclick="toggleTodo(${t.id})"></button>
      <span class="todo-text">${t.text}</span>
      <button class="todo-del" onclick="deleteTodo(${t.id})">🗑</button>
    </div>`).join('');
}

async function toggleTodo(id) {
  await fetch(`/api/todos/${id}/toggle`, {method:'POST'});
  loadTodos();
}

async function deleteTodo(id) {
  await fetch(`/api/todos/${id}`, {method:'DELETE'});
  loadTodos();
}

// ── REPORT ────────────────────────────────────────────────────────────────────
async function logHours() {
  const hours = parseFloat(document.getElementById('hours-log').value);
  if (!hours || hours <= 0) { alert('Enter a valid number of hours!'); return; }
  await fetch('/api/study-hours', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({hours}) });
  document.getElementById('hours-log').value = '';
  loadReport();
}

async function loadReport() {
  const res = await fetch('/api/performance');
  const d = await res.json();
  if (d.error) return;
  const el = document.getElementById('report-content');

  const gradeColor = { A:'var(--green)', B:'var(--accent)', C:'var(--accent2)', D:'var(--red)', F:'var(--red)' }[d.grade] || 'var(--accent)';

  el.innerHTML = `
    <div class="perf-grid">
      <div class="perf-card grade-card">
        <div class="perf-icon">🏅</div>
        <div class="perf-val grade-val" style="color:${gradeColor}">${d.grade}</div>
        <div class="perf-label">Overall Grade</div>
      </div>
      <div class="perf-card">
        <div class="perf-icon">✅</div>
        <div class="perf-val" style="color:var(--green)">${d.todo_pct}%</div>
        <div class="perf-label">Tasks Completed (${d.done_todos}/${d.total_todos})</div>
      </div>
      <div class="perf-card">
        <div class="perf-icon">🧠</div>
        <div class="perf-val">${d.avg_quiz}%</div>
        <div class="perf-label">Avg Quiz Score (${d.quiz_count} quizzes)</div>
      </div>
      <div class="perf-card">
        <div class="perf-icon">⏱</div>
        <div class="perf-val" style="color:var(--accent2)">${d.total_hours}h</div>
        <div class="perf-label">Total Study Hours (${d.sessions} sessions)</div>
      </div>
    </div>
    <div class="perf-msg"><p>${d.message}</p></div>
    <div class="perf-bars">
      <h4>📈 Score Breakdown</h4>
      <div class="bar-row">
        <div class="bar-label"><span>To-Do Completion</span><span>${d.todo_pct}%</span></div>
        <div class="bar-track"><div class="bar-fill bar-green" style="width:${d.todo_pct}%"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-label"><span>Quiz Performance</span><span>${d.avg_quiz}%</span></div>
        <div class="bar-track"><div class="bar-fill bar-purple" style="width:${d.avg_quiz}%"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-label"><span>Study Hours (vs 20h goal)</span><span>${Math.min(d.total_hours/20*100,100).toFixed(0)}%</span></div>
        <div class="bar-track"><div class="bar-fill bar-gold" style="width:${Math.min(d.total_hours/20*100,100)}%"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-label"><span>Overall Score</span><span>${d.composite}%</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:${d.composite}%;background:${gradeColor}"></div></div>
      </div>
    </div>`;
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("\n🎓 EDUVANTA (Enhanced) is running!")
    print("   Open this in your browser → http://localhost:5000\n")
    app.run(debug=True, port=5000)
