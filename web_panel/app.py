"""
web_panel/app.py - Flask panel webowy.
WERSJA: 3.6 - Wsparcie dla wielu URLi na zapytanie
"""
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import sqlite3
import os
import time
import threading
import json

app = Flask(__name__)
app.secret_key = os.urandom(24)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "vinted_notification.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_config_defaults():
    """Inicjalizuje domyślne wartości konfiguracji."""
    conn = get_db()
    c = conn.cursor()
    
    defaults = {
        ("scan_interval", "20"),
        ("items_per_query", "15"),
        ("new_item_window", "5"),
        ("query_delay", "2"),
        ("discord_bot_token", ""),
        ("proxy_list", ""),
    }
    
    for key, value in defaults:
        c.execute("SELECT 1 FROM config WHERE key = ?", (key,))
        if not c.fetchone():
            c.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, value))
    
    conn.commit()
    conn.close()

@app.route("/")
def dashboard():
    conn = get_db()
    stats = {
        "queries": conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
        "items": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "logs": conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0],
    }
    recent_items = conn.execute("SELECT * FROM items ORDER BY timestamp DESC LIMIT 10").fetchall()
    recent_logs = conn.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 10").fetchall()
    conn.close()
    return render_template("dashboard.html", stats=stats, items=recent_items, logs=recent_logs)

@app.route("/queries")
def queries():
    conn = get_db()
    all_queries = conn.execute("SELECT * FROM queries ORDER BY id DESC").fetchall()
    
    # Pobierz liczbę URLi dla każdego zapytania
    queries_with_urls = []
    for q in all_queries:
        url_count = conn.execute("SELECT COUNT(*) FROM query_urls WHERE query_id = ?", (q["id"],)).fetchone()[0]
        query_dict = dict(q)
        query_dict["url_count"] = url_count
        queries_with_urls.append(query_dict)
    
    conn.close()
    return render_template("queries.html", queries=queries_with_urls)

@app.route("/query/add", methods=["GET", "POST"])
def add_query():
    if request.method == "POST":
        name = request.form["name"]
        webhook = request.form["webhook_url"]
        channel = request.form.get("channel_name", name)
        color = request.form.get("embed_color", "5763719")
        active = 1 if request.form.get("active") else 0
        
        # Obsługa wielu URLi (oddzielone enterem lub przecinkiem)
        urls_raw = request.form.get("urls", "")
        urls = [u.strip() for u in urls_raw.replace(",", "\n").split("\n") if u.strip()]
        
        if not urls:
            flash("❌ Dodaj przynajmniej jeden URL!", "error")
            return redirect(url_for("add_query"))
        
        import src.database as db
        db.add_query(name, webhook, channel, color, urls, active)
        
        flash("✅ Dodano zapytanie!", "success")
        return redirect(url_for("queries"))
    
    return render_template("query_form.html")

@app.route("/query/edit/<int:id>", methods=["GET", "POST"])
def edit_query(id):
    conn = get_db()
    
    if request.method == "POST":
        name = request.form["name"]
        webhook = request.form["webhook_url"]
        channel = request.form.get("channel_name", name)
        color = request.form.get("embed_color", "5763719")
        active = 1 if request.form.get("active") else 0
        
        # Obsługa wielu URLi
        urls_raw = request.form.get("urls", "")
        urls = [u.strip() for u in urls_raw.replace(",", "\n").split("\n") if u.strip()]
        
        if not urls:
            flash("❌ Dodaj przynajmniej jeden URL!", "error")
            return redirect(url_for("edit_query", id=id))
        
        import src.database as db
        db.update_query(id, name, webhook, channel, color, urls, active)
        
        flash("✅ Zaktualizowano zapytanie!", "success")
        return redirect(url_for("queries"))
    
    query = conn.execute("SELECT * FROM queries WHERE id = ?", (id,)).fetchone()
    urls = conn.execute("SELECT url FROM query_urls WHERE query_id = ?", (id,)).fetchall()
    conn.close()
    
    return render_template("query_form.html", query=query, urls=[u["url"] for u in urls])

@app.route("/query/delete/<int:id>")
def delete_query(id):
    import src.database as db
    db.delete_query(id)
    flash("🗑️ Usunięto zapytanie!", "success")
    return redirect(url_for("queries"))

@app.route("/query/toggle/<int:id>")
def toggle_query(id):
    import src.database as db
    db.toggle_query(id)
    return redirect(url_for("queries"))

@app.route("/items")
def items():
    conn = get_db()
    all_items = conn.execute("SELECT * FROM items ORDER BY timestamp DESC LIMIT 100").fetchall()
    conn.close()
    return render_template("items.html", items=all_items)

@app.route("/logs")
def logs():
    conn = get_db()
    all_logs = conn.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 100").fetchall()
    conn.close()
    return render_template("logs.html", logs=all_logs)

@app.route("/settings", methods=["GET", "POST"])
def settings():
    conn = get_db()
    if request.method == "POST":
        for key in ["scan_interval", "items_per_query", "new_item_window", "query_delay", "discord_bot_token", "proxy_list"]:
            value = request.form.get(key, "")
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        flash("✅ Zapisano ustawienia!", "success")
        return redirect(url_for("settings"))
    
    config = {row["key"]: row["value"] for row in conn.execute("SELECT * FROM config").fetchall()}
    conn.close()
    
    return render_template("settings.html", config={
        "scan_interval": config.get("scan_interval", "20"),
        "items_per_query": config.get("items_per_query", "15"),
        "new_item_window": config.get("new_item_window", "5"),
        "query_delay": config.get("query_delay", "2"),
        "discord_bot_token": config.get("discord_bot_token", ""),
        "proxy_list": config.get("proxy_list", ""),
    })

@app.route("/api/stats")
def api_stats():
    conn = get_db()
    stats = {
        "queries": conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
        "active_queries": conn.execute("SELECT COUNT(*) FROM queries WHERE active = 1").fetchone()[0],
        "items": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "logs": conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0],
    }
    conn.close()
    return jsonify(stats)

def run_panel(host="0.0.0.0", port=8080, debug=False):
    init_config_defaults()
    app.run(host=host, port=port, debug=debug, threaded=True)

if __name__ == "__main__":
    run_panel()
