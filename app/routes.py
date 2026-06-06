import csv
import base64
import json
import os
from functools import wraps
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

main = Blueprint("main", __name__)
CSV_PATH = Path(__file__).resolve().parent / "tunisie_destinations.csv"


def _init_firestore_client():
    """Initialize Firebase from env on cloud, with local file fallback."""
    try:
        if not firebase_admin._apps:
            raw_json = (os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
            raw_json_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64")
            cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
            google_creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

            if raw_json:
                try:
                    cred = credentials.Certificate(json.loads(raw_json))
                except json.JSONDecodeError as exc:
                    print(
                        "FIREBASE_SERVICE_ACCOUNT_JSON is set but not valid JSON. "
                        f"Error: {exc}"
                    )
                    raw_json = ""

            if raw_json:
                pass
            elif raw_json_b64:
                decoded = base64.b64decode(raw_json_b64).decode("utf-8")
                cred = credentials.Certificate(json.loads(decoded))
            else:
                if not cred_path and google_creds_path:
                    cred_path = google_creds_path

                if not cred_path:
                    cred_path = os.path.join(
                        os.path.dirname(__file__),
                        "tunisia-tourism-firebase-adminsdk-seadi-18c763db2c.json",
                    )

                # Resolve relative paths against both project root and app package.
                path_candidates = [
                    Path(cred_path),
                    Path.cwd() / cred_path,
                    Path(__file__).resolve().parent / cred_path,
                    Path(__file__).resolve().parent.parent / cred_path,
                ]
                resolved_path = None
                for candidate in path_candidates:
                    if candidate.exists():
                        resolved_path = candidate
                        break

                if resolved_path is None:
                    print(
                        "Firebase credentials file not found. Tried: "
                        + ", ".join(str(p) for p in path_candidates)
                    )
                    return None

                cred = credentials.Certificate(str(resolved_path))

            firebase_admin.initialize_app(cred)

        return firestore.client()
    except Exception as exc:
        print(f"Firebase init error: {exc}")
        return None


db = _init_firestore_client()


def login_required(route_func):
    @wraps(route_func)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("main.signin"))
        return route_func(*args, **kwargs)

    return wrapper


def admin_required(route_func):
    @wraps(route_func)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("main.signin"))
        if session.get("role") != "admin":
            return redirect(url_for("main.profile"))
        return route_func(*args, **kwargs)

    return wrapper


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_admin_email(email):
    admin_emails = {
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "").split(",")
        if e.strip()
    }
    return email.lower() in admin_emails


def _ensure_db():
    if db is None:
        return False, (
            "Database is not configured. Set one of: FIREBASE_SERVICE_ACCOUNT_JSON, "
            "FIREBASE_SERVICE_ACCOUNT_B64, FIREBASE_CREDENTIALS_PATH, or GOOGLE_APPLICATION_CREDENTIALS."
        )
    return True, ""


def _seed_attractions_if_empty():
    """Seed attractions from CSV once so the app is demo-ready after deploy."""
    if db is None or not CSV_PATH.exists():
        return

    try:
        first = next(db.collection("attractions").limit(1).stream(), None)
    except Exception as exc:
        print(f"Skipping attraction seed because Firestore is unavailable: {exc}")
        return

    if first is not None:
        return

    with open(CSV_PATH, "r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            name = (row.get("name") or "Attraction").strip()
            category = (row.get("category") or "General").strip()
            city = (row.get("location") or "Tunisia").strip()
            budget_text = (row.get("budget") or "medium").lower()

            if "low" in budget_text:
                budget_min, budget_max = 10.0, 35.0
            elif "high" in budget_text:
                budget_min, budget_max = 90.0, 220.0
            else:
                budget_min, budget_max = 35.0, 90.0

            try:
                db.collection("attractions").add(
                    {
                        "name": name,
                        "city": city,
                        "region": city,
                        "category": category,
                        "budget_min": budget_min,
                        "budget_max": budget_max,
                        "duration_hours": 2.0,
                        "description": f"Visit {name} in {city}.",
                        "lat": 0.0,
                        "lon": 0.0,
                        "image_url": "",
                        "created_by": "seed",
                        "created_at": firestore.SERVER_TIMESTAMP,
                    }
                )
            except Exception as exc:
                print(f"Stopping seed because Firestore write failed: {exc}")
                return


def _fetch_attractions(filters=None):
    docs = db.collection("attractions").stream()
    attractions = []
    filters = filters or {}

    for doc in docs:
        item = doc.to_dict()
        item["id"] = doc.id

        city = (item.get("city") or "").lower()
        category = (item.get("category") or "").lower()
        name = (item.get("name") or "").lower()
        q = (filters.get("q") or "").lower()

        if filters.get("city") and city != filters["city"].lower():
            continue
        if filters.get("category") and category != filters["category"].lower():
            continue
        if q and q not in name and q not in city and q not in category:
            continue

        max_budget = _safe_float(item.get("budget_max"), 10**9)
        budget_filter = _safe_float(filters.get("budget"), 0)
        if budget_filter > 0 and max_budget > budget_filter:
            continue

        attractions.append(item)

    attractions.sort(key=lambda x: (x.get("city", ""), x.get("name", "")))
    return attractions


def _reviews_for_attraction(attraction_id):
    reviews_query = db.collection("attraction_reviews").where(
        "attraction_id", "==", attraction_id
    )
    reviews = []
    for doc in reviews_query.stream():
        review = doc.to_dict()
        review["id"] = doc.id
        reviews.append(review)
    reviews.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return reviews


def _build_itinerary(attractions, days, total_budget):
    if not attractions:
        return

    selected = []
    budget_per_day = total_budget / max(days, 1)

    for day in range(1, days + 1):
        remaining_hours = 8.0
        day_plan = []

        for attr in attractions:
            duration = _safe_float(attr.get("duration_hours"), 2.0)
            min_cost = _safe_float(attr.get("budget_min"), 0.0)
            max_cost = _safe_float(attr.get("budget_max"), min_cost)
            estimated_cost = (min_cost + max_cost) / 2

            if attr.get("id") in selected:
                continue
            if duration > remaining_hours:
                continue
            if estimated_cost > budget_per_day:
                continue

            day_plan.append({
                "name": attr.get("name"),
                "city": attr.get("city"),
                "duration_hours": duration,
                "estimated_cost": round(estimated_cost, 2),
            })
            selected.append(attr.get("id"))
            remaining_hours -= duration

            if len(day_plan) >= 3:
                break

        if day_plan:
            yield {
                "day": day,
                "activities": day_plan,
            }


def _assistant_reply(message, city=None, budget=0):
    attractions = _fetch_attractions(
        {
            "city": city,
            "budget": budget,
        }
    )
    if not attractions:
        return (
            "I could not find attractions with your filters yet. "
            "Try another city or ask the admin to add attractions."
        )

    msg = (message or "").lower()
    top = attractions[:3]

    if "itinerary" in msg or "plan" in msg:
        names = ", ".join([a.get("name", "Unknown") for a in top])
        return (
            "Suggested one-day plan: "
            f"Start with {names}. Keep a 2-hour buffer for transport and meals."
        )

    if "budget" in msg or "cheap" in msg:
        cheapest = sorted(
            top,
            key=lambda x: _safe_float(x.get("budget_min"), 0.0),
        )
        names = ", ".join([a.get("name", "Unknown") for a in cheapest])
        return f"Budget-friendly options: {names}."

    names = ", ".join([a.get("name", "Unknown") for a in top])
    return f"Top matches for your request: {names}."


@main.route("/")
def home():
    return render_template("home.html")


@main.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    ok, message = _ensure_db()
    if not ok:
        return jsonify({"error": message}), 500

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not email or not password:
        return jsonify({"error": "Username, email, and password are required."}), 400

    user_ref = db.collection("users").document(username)
    if user_ref.get().exists:
        return jsonify({"error": "Username already exists."}), 400

    duplicate_email = db.collection("users").where("email", "==", email).limit(1).stream()
    if any(True for _ in duplicate_email):
        return jsonify({"error": "There is already an account with this email."}), 400

    role = "admin" if _is_admin_email(email) else "visitor"
    user_ref.set(
        {
            "username": username,
            "email": email,
            "password": generate_password_hash(password),
            "role": role,
        }
    )

    session["username"] = username
    session["role"] = role
    return jsonify({"success": True})


@main.route("/signin", methods=["GET", "POST"])
def signin():
    if request.method == "GET":
        return render_template("signin.html")

    ok, message = _ensure_db()
    if not ok:
        return jsonify({"error": message}), 500

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    query = db.collection("users").where("email", "==", email).limit(1).stream()
    user_doc = next(query, None)
    if not user_doc:
        return jsonify({"error": "User not found."}), 400

    user_data = user_doc.to_dict()
    if not check_password_hash(user_data.get("password", ""), password):
        return jsonify({"error": "Invalid password."}), 400

    session["username"] = user_data.get("username", user_doc.id)
    session["role"] = user_data.get("role", "visitor")
    return jsonify({"success": True})


@main.route("/signout")
def signout():
    session.clear()
    return redirect(url_for("main.home"))


@main.route("/profile")
@login_required
def profile():
    return render_template(
        "profile.html",
        username=session.get("username"),
        role=session.get("role", "visitor"),
    )


@main.route("/admin/attractions", methods=["GET", "POST"])
@admin_required
def admin_attractions():
    ok, message = _ensure_db()
    if not ok:
        return render_template("profile.html", username=session.get("username"), role=session.get("role"), error=message)

    if request.method == "POST":
        form = request.form
        db.collection("attractions").add(
            {
                "name": form.get("name"),
                "city": form.get("city"),
                "region": form.get("region"),
                "category": form.get("category"),
                "budget_min": _safe_float(form.get("budget_min"), 0.0),
                "budget_max": _safe_float(form.get("budget_max"), 0.0),
                "duration_hours": _safe_float(form.get("duration_hours"), 2.0),
                "description": form.get("description"),
                "lat": _safe_float(form.get("lat"), 0.0),
                "lon": _safe_float(form.get("lon"), 0.0),
                "image_url": form.get("image_url"),
                "created_by": session.get("username"),
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )
        return redirect(url_for("main.admin_attractions"))

    attractions = _fetch_attractions()
    return render_template(
        "admin_attractions.html",
        username=session.get("username"),
        attractions=attractions,
        edit_item=None,
    )


@main.route("/admin/attractions/<attraction_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_attraction(attraction_id):
    ok, message = _ensure_db()
    if not ok:
        return render_template("profile.html", username=session.get("username"), role=session.get("role"), error=message)

    ref = db.collection("attractions").document(attraction_id)
    snapshot = ref.get()
    if not snapshot.exists:
        return redirect(url_for("main.admin_attractions"))

    if request.method == "POST":
        form = request.form
        ref.update(
            {
                "name": form.get("name"),
                "city": form.get("city"),
                "region": form.get("region"),
                "category": form.get("category"),
                "budget_min": _safe_float(form.get("budget_min"), 0.0),
                "budget_max": _safe_float(form.get("budget_max"), 0.0),
                "duration_hours": _safe_float(form.get("duration_hours"), 2.0),
                "description": form.get("description"),
                "lat": _safe_float(form.get("lat"), 0.0),
                "lon": _safe_float(form.get("lon"), 0.0),
                "image_url": form.get("image_url"),
            }
        )
        return redirect(url_for("main.admin_attractions"))

    attractions = _fetch_attractions()
    edit_item = snapshot.to_dict()
    edit_item["id"] = snapshot.id
    return render_template(
        "admin_attractions.html",
        username=session.get("username"),
        attractions=attractions,
        edit_item=edit_item,
    )


@main.route("/admin/attractions/<attraction_id>/delete", methods=["POST"])
@admin_required
def delete_attraction(attraction_id):
    ok, _ = _ensure_db()
    if ok:
        db.collection("attractions").document(attraction_id).delete()
    return redirect(url_for("main.admin_attractions"))


@main.route("/attractions")
def attractions():
    ok, message = _ensure_db()
    if not ok:
        return render_template("attractions.html", attractions=[], filters={}, error=message)

    filters = {
        "q": request.args.get("q", "").strip(),
        "city": request.args.get("city", "").strip(),
        "category": request.args.get("category", "").strip(),
        "budget": request.args.get("budget", "").strip(),
    }
    items = _fetch_attractions(filters)
    return render_template(
        "attractions.html",
        attractions=items,
        filters=filters,
        error=None,
    )


@main.route("/attractions/<attraction_id>")
def attraction_detail(attraction_id):
    ok, message = _ensure_db()
    if not ok:
        return render_template("attraction_detail.html", attraction=None, reviews=[], avg_rating=None, error=message)

    snapshot = db.collection("attractions").document(attraction_id).get()
    if not snapshot.exists:
        return redirect(url_for("main.attractions"))

    attraction = snapshot.to_dict()
    attraction["id"] = snapshot.id
    reviews = _reviews_for_attraction(attraction_id)
    ratings = [_safe_float(r.get("rating"), 0.0) for r in reviews]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    return render_template(
        "attraction_detail.html",
        attraction=attraction,
        reviews=reviews,
        avg_rating=avg_rating,
        username=session.get("username"),
        error=None,
    )


@main.route("/attractions/<attraction_id>/reviews", methods=["POST"])
@login_required
def add_review(attraction_id):
    ok, _ = _ensure_db()
    if not ok:
        return redirect(url_for("main.attraction_detail", attraction_id=attraction_id))

    rating = int(request.form.get("rating", 5))
    comment = (request.form.get("comment") or "").strip()

    db.collection("attraction_reviews").add(
        {
            "attraction_id": attraction_id,
            "username": session.get("username"),
            "rating": max(1, min(5, rating)),
            "comment": comment,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )
    return redirect(url_for("main.attraction_detail", attraction_id=attraction_id))


@main.route("/itinerary", methods=["GET", "POST"])
def itinerary():
    ok, message = _ensure_db()
    if not ok:
        return render_template("itinerary.html", plan=[], estimated_total=0, error=message)

    if request.method == "GET":
        return render_template("itinerary.html", plan=[], estimated_total=0, error=None)

    city = request.form.get("city", "").strip()
    category = request.form.get("category", "").strip()
    days = int(request.form.get("days", 1) or 1)
    budget = _safe_float(request.form.get("budget"), 0.0)

    items = _fetch_attractions({"city": city, "category": category})
    plan = list(_build_itinerary(items, max(days, 1), max(budget, 0.0)))
    estimated_total = round(
        sum(a["estimated_cost"] for day in plan for a in day["activities"]),
        2,
    )

    return render_template(
        "itinerary.html",
        plan=plan,
        estimated_total=estimated_total,
        error=None,
        form_values={
            "city": city,
            "category": category,
            "days": days,
            "budget": budget,
        },
    )


@main.route("/assistant")
def assistant_page():
    return render_template("assistant.html")


@main.route("/assistant/chat", methods=["POST"])
def assistant_chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "")
    city = payload.get("city", "")
    budget = _safe_float(payload.get("budget"), 0.0)

    ok, db_message = _ensure_db()
    if not ok:
        return jsonify({"reply": db_message}), 500

    return jsonify({"reply": _assistant_reply(message, city=city, budget=budget)})


@main.route("/local_experiences")
def local_experiences_legacy():
    return redirect(url_for("main.attractions"))


@main.route("/find_places", methods=["GET", "POST"])
def find_places_legacy():
    return redirect(url_for("main.attractions"))


@main.route("/places", methods=["GET", "POST"])
def places_legacy():
    return redirect(url_for("main.attractions"))


_seed_attractions_if_empty()
