"""
web_panel/app.py - Panel administracyjny Vinted-Notification (Flask, port 8080).

Funkcje:
- Dashboard ze statystykami
- Zarządzanie queries (dodaj / edytuj / usuń / włącz-wyłącz)
- Podgląd znalezionych przedmiotów
- Logi w czasie rzeczywistym
- Ustawienia globalne
"""
import os
import sys

# Ścieżka do src na poziomie projektu
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, flash, abort
)

import src.database as db
from src.discord_sender import COLOR_PRESETS, send_system_message
from src.proxy_manager import proxy_manager
from src.logger import get_logger

logger = get_logger("web_panel")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET", "vinted-notification-secret-key-change-me")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

import time as _time

def _row_to_dict(row) -> dict:
    """Konwertuje sqlite3.Row do słownika."""
    if row is None:
        return {}
    return dict(row)


def _rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# TTL cache — redukuje odczyty SQLite z dashboardu (RPi3B: -75% DB reads)
_response_cache: dict = {}

def _cached(key: str, ttl: float, fn):
    """Prosty TTL cache — wywolaj fn() tylko gdy dane starsze niż ttl sekund."""
    now = _time.time()
    entry = _response_cache.get(key)
    if entry and now - entry["ts"] < ttl:
        return entry["data"]
    data = fn()
    _response_cache[key] = {"data": data, "ts": now}
    return data


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@app.route("/")
def index():
    stats = _cached("dash_stats", 5, db.get_stats)
    recent_items = _cached("dash_items", 5, lambda: _rows_to_list(db.get_items(limit=10)))
    recent_logs = _cached("dash_logs", 5, lambda: _rows_to_list(db.get_logs(limit=8)))
    queries = _cached("dash_queries", 5, lambda: _rows_to_list(db.get_all_queries(active_only=False)))
    return render_template(
        "index.html",
        stats=stats,
        recent_items=recent_items,
        recent_logs=recent_logs,
        queries=queries,
    )


# ─────────────────────────────────────────────
# QUERIES
# ─────────────────────────────────────────────

@app.route("/queries")
def queries():
    all_queries = _rows_to_list(db.get_all_queries(active_only=False))
    return render_template(
        "queries.html",
        queries=all_queries,
        color_presets=COLOR_PRESETS,
    )


@app.route("/queries/add", methods=["GET", "POST"])
def add_query():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()
        webhook = request.form.get("webhook_url", "").strip()
        channel = request.form.get("channel_name", "general").strip()
        color = request.form.get("embed_color", "5763719").strip()
        discord_channel_id = request.form.get("discord_channel_id", "").strip()

        errors = []
        if not name:
            errors.append("Nazwa jest wymagana")
        if not url or not url.startswith("http"):
            errors.append("Podaj prawidłowy URL Vinted")
        if not webhook or not webhook.startswith("https://discord.com/api/webhooks/"):
            errors.append("Podaj prawidłowy URL webhooka Discord")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "query_form.html",
                action="add",
                form_data=request.form,
                color_presets=COLOR_PRESETS,
                discord_mode=db.get_config("discord_mode", "webhook"),
            )

        from src.core import normalize_query_url
        try:
            normalized = normalize_query_url(url)
            if db.query_exists(normalized):
                flash("To zapytanie już istnieje w bazie", "warning")
                return redirect(url_for("queries"))

            qid = db.add_query(
                name=name,
                url=url,
                discord_webhook_url=webhook,
                channel_name=channel,
                embed_color=color,
                discord_channel_id=discord_channel_id,
            )
            flash(f'✅ Dodano query "{name}"', "success")
            logger.info(f"Dodano query: {name}")
            return redirect(url_for("queries"))

        except Exception as e:
            flash(f"Błąd: {str(e)}", "error")
            logger.error(f"Błąd dodawania query: {e}")

    return render_template(
        "query_form.html",
        action="add",
        form_data={},
        color_presets=COLOR_PRESETS,
        discord_mode=db.get_config("discord_mode", "webhook"),
    )


@app.route("/queries/<int:query_id>/edit", methods=["GET", "POST"])
def edit_query(query_id: int):
    query = _row_to_dict(db.get_query_by_id(query_id))
    if not query:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()
        webhook = request.form.get("webhook_url", "").strip()
        channel = request.form.get("channel_name", "general").strip()
        color = request.form.get("embed_color", "5763719").strip()
        active = request.form.get("active") == "1"
        discord_channel_id = request.form.get("discord_channel_id", "").strip()

        errors = []
        if not name:
            errors.append("Nazwa jest wymagana")
        if not url or not url.startswith("http"):
            errors.append("Podaj prawidłowy URL Vinted")
        if not webhook or not webhook.startswith("https://discord.com/api/webhooks/"):
            errors.append("Podaj prawidłowy URL webhooka Discord")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "query_form.html",
                action="edit",
                form_data=request.form,
                query_id=query_id,
                color_presets=COLOR_PRESETS,
                discord_mode=db.get_config("discord_mode", "webhook"),
            )
        else:
            try:
                db.update_query(
                    query_id=query_id,
                    name=name,
                    url=url,
                    discord_webhook_url=webhook,
                    channel_name=channel,
                    embed_color=color,
                    active=active,
                    discord_channel_id=discord_channel_id,
                )
                flash(f'✅ Zaktualizowano query "{name}"', "success")
                return redirect(url_for("queries"))
            except Exception as e:
                flash(f"Błąd: {str(e)}", "error")

    return render_template(
        "query_form.html",
        action="edit",
        form_data=query,
        query_id=query_id,
        color_presets=COLOR_PRESETS,
        discord_mode=db.get_config("discord_mode", "webhook"),
    )


@app.route("/queries/<int:query_id>/delete", methods=["POST"])
def delete_query(query_id: int):
    query = _row_to_dict(db.get_query_by_id(query_id))
    if not query:
        abort(404)
    db.delete_query(query_id)
    flash(f'🗑️ Usunięto query "{query.get("name", "")}"', "success")
    return redirect(url_for("queries"))


@app.route("/queries/<int:query_id>/toggle", methods=["POST"])
def toggle_query(query_id: int):
    """API endpoint do włączania/wyłączania query (AJAX)."""
    new_state = db.toggle_query(query_id)
    return jsonify({"active": new_state, "query_id": query_id})

@app.route("/queries/toggle-all", methods=["POST"])
def toggle_all_queries():
    """Włącza lub wyłącza wszystkie zapytania naraz."""
    action = request.form.get("action", "enable")
    activate = (action == "enable")
    db.set_all_queries_active(activate)
    summary = db.get_queries_summary()
    if activate:
        flash(f"✅ Włączono wszystkie zapytania ({summary['total']} szt.)", "success")
        db.add_log("INFO", "panel", f"Włączono wszystkie zapytania ({summary['total']} szt.)")
    else:
        flash(f"⏸️ Wyłączono wszystkie zapytania ({summary['total']} szt.)", "warning")
        db.add_log("INFO", "panel", f"Wyłączono wszystkie zapytania ({summary['total']} szt.)")
    return redirect(url_for("queries"))


@app.route("/queries/<int:query_id>/test", methods=["POST"])
def test_query_webhook(query_id: int):
    """Wysyła testową wiadomość na webhook przypisany do query."""
    query = _row_to_dict(db.get_query_by_id(query_id))
    if not query:
        abort(404)

    webhook = query.get("discord_webhook_url", "")
    name = query.get("name", "")

    success = send_system_message(
        webhook_url=webhook,
        message=f"🧪 Test webhooka dla query: **{name}**\nKanał: #{query.get('channel_name', '')}",
        level="INFO"
    )

    if success:
        flash(f'✅ Wysłano test na webhook dla "{name}"', "success")
    else:
        flash(f'❌ Błąd wysyłki testu. Sprawdź URL webhooka.', "error")

    return redirect(url_for("queries"))


# ─────────────────────────────────────────────
# ITEMS
# ─────────────────────────────────────────────

@app.route("/items")
def items():
    query_id = request.args.get("query_id", type=int)
    limit = min(request.args.get("limit", 100, type=int), 500)
    all_items = _rows_to_list(db.get_items(limit=limit, query_id=query_id))
    queries = _rows_to_list(db.get_all_queries(active_only=False))
    return render_template(
        "items.html",
        items=all_items,
        queries=queries,
        selected_query=query_id,
        limit=limit,
    )


# ─────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────

@app.route("/logs")
def logs():
    level_filter = request.args.get("level", "ALL")
    limit = min(request.args.get("limit", 200, type=int), 1000)
    log_entries = _rows_to_list(db.get_logs(limit=limit, level=level_filter))
    return render_template(
        "logs.html",
        logs=log_entries,
        level_filter=level_filter,
        limit=limit,
    )


@app.route("/logs/clear", methods=["POST"])
def clear_logs():
    db.clear_logs()
    flash("🗑️ Logi wyczyszczone", "success")
    return redirect(url_for("logs"))


@app.route("/api/logs")
def api_logs():
    """API endpoint – pobiera nowe logi (polling co 5s z frontendu)."""
    since_id = request.args.get("since_id", 0, type=int)
    level = request.args.get("level", "ALL")

    with db.get_connection() as conn:
        if level and level != "ALL":
            rows = conn.execute(
                "SELECT * FROM logs WHERE id>? AND level=? ORDER BY id DESC LIMIT 50",
                (since_id, level.upper())
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM logs WHERE id>? ORDER BY id DESC LIMIT 50",
                (since_id,)
            ).fetchall()

    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        scan_interval = request.form.get("scan_interval", "60")
        items_per_query = request.form.get("items_per_query", "20")
        new_item_window = request.form.get("new_item_window", "5")

        try:
            query_delay = request.form.get("query_delay", "5")
            db.set_config("scan_interval",   str(max(10, int(scan_interval))))
            db.set_config("items_per_query", str(max(5, min(50, int(items_per_query)))))
            db.set_config("new_item_window", str(max(5, min(60, int(new_item_window)))))
            db.set_config("query_delay",     str(max(2, min(30, int(query_delay)))))
            proxy_list          = request.form.get("proxy_list", "")
            proxy_list_url      = request.form.get("proxy_list_url", "")
            proxy_check_enabled = "true" if request.form.get("proxy_check_enabled") else "false"
            db.set_config("proxy_list",          proxy_list.strip())
            db.set_config("proxy_list_url",      proxy_list_url.strip())
            db.set_config("proxy_check_enabled", proxy_check_enabled)
            # Wymuś przeładowanie proxy po zmianie konfiguracji
            proxy_manager.invalidate()
            flash("✅ Ustawienia zapisane", "success")
        except ValueError:
            flash("❌ Nieprawidłowe wartości", "error")

        return redirect(url_for("settings"))

    config = {
        "scan_interval": db.get_config("scan_interval", "60"),
        "items_per_query": db.get_config("items_per_query", "20"),
        "new_item_window": db.get_config("new_item_window", "5"),
        "query_delay": db.get_config("query_delay", "5"),
        "proxy_list": db.get_config("proxy_list", ""),
        "proxy_list_url": db.get_config("proxy_list_url", ""),
        "proxy_check_enabled": db.get_config("proxy_check_enabled", "false"),
        "discord_mode": db.get_config("discord_mode", "webhook"),
        "discord_bot_token": db.get_config("discord_bot_token", ""),
        "version": db.get_config("version", "2.0.0"),
    }
    return render_template("settings.html", config=config)


# ─────────────────────────────────────────────
# API - Stats (dla dashboardu)
# ─────────────────────────────────────────────

@app.route("/api/proxy-stats")
def api_proxy_stats():
    """Statystyki puli proxy — dla dashboardu."""
    return jsonify(proxy_manager.get_stats())


@app.route("/api/stats")
def api_stats():
    return jsonify(_cached("api_stats", 3, db.get_stats))


@app.route("/metrics")
def metrics():
    """Prometheus-compatible metrics endpoint."""
    try:
        from main import _format_metrics
        from flask import Response
        return Response(_format_metrics(), mimetype="text/plain; charset=utf-8")
    except ImportError:
        return "# metrics unavailable\n", 200, {"Content-Type": "text/plain"}


def run_panel(host: str = "0.0.0.0", port: int = 8080, debug: bool = False):
    """Uruchamia panel webowy."""
    logger.info(f"Panel webowy dostępny na http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run_panel(debug=True)
