import json
import os
import random
import re
import zipfile
from datetime import datetime
from urllib import parse, request as urlrequest
from xml.etree import ElementTree as ET

from flask import Flask, jsonify, request


DATA_FILE = "study_cards.json"
app = Flask(__name__)


def supabase_enabled():
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))


def supabase_request(method, path, query=None, payload=None):
    base_url = os.environ["SUPABASE_URL"].rstrip("/")
    api_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    table = os.environ.get("SUPABASE_TABLE", "study_app_state")
    final_path = path.replace("{table}", table)
    qs = f"?{parse.urlencode(query)}" if query else ""
    url = f"{base_url}{final_path}{qs}"
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(url=url, data=body, method=method)
    req.add_header("apikey", api_key)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=representation,resolution=merge-duplicates")
    with urlrequest.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def load_data_supabase():
    rows = supabase_request(
        "GET",
        "/rest/v1/{table}",
        query={"id": "eq.1", "select": "data"},
    )
    if not rows:
        return {"cards": [], "stats": {"correct": 0, "wrong": 0}}
    return rows[0].get("data") or {"cards": [], "stats": {"correct": 0, "wrong": 0}}


def save_data_supabase(data):
    supabase_request(
        "POST",
        "/rest/v1/{table}",
        payload=[{"id": 1, "data": data, "updated_at": datetime.utcnow().isoformat()}],
    )


def load_data():
    if supabase_enabled():
        try:
            return load_data_supabase()
        except Exception:
            pass
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"cards": [], "stats": {"correct": 0, "wrong": 0}}


def save_data(data):
    if supabase_enabled():
        try:
            save_data_supabase(data)
            return
        except Exception:
            pass
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_schema(data):
    data.setdefault("cards", [])
    data.setdefault("stats", {"correct": 0, "wrong": 0})
    for c in data["cards"]:
        c.setdefault("id", f"card-{random.randint(100000,999999)}")
        c.setdefault("title", "")
        c.setdefault("question", "")
        c.setdefault("answer", "")
        c.setdefault("quiz_type", "short")
        c.setdefault("study_date", datetime.now().strftime("%Y-%m-%d"))
        c.setdefault("wrong_count", 0)
        c.setdefault("correct_count", 0)
        c.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def sanitize(c):
    return {
        "id": c["id"],
        "title": c["title"],
        "question": c["question"],
