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

    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

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
        c.setdefault("id", f"card-{random.randint(100000, 999999)}")
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
        "answer": c["answer"],
        "quiz_type": c["quiz_type"],
        "study_date": c["study_date"],
        "wrong_count": c["wrong_count"],
        "correct_count": c["correct_count"],
        "created_at": c["created_at"],
    }


def make_card(study_date, title, question, answer, quiz_type):
    return {
        "id": f"card-{random.randint(100000,999999)}-{int(datetime.now().timestamp())}-{random.randint(10,99)}",
        "title": title,
        "question": question,
        "answer": answer,
        "quiz_type": quiz_type,
        "study_date": study_date,
        "wrong_count": 0,
        "correct_count": 0,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def note_to_cards(note_text, study_date, title):
    cards = []
    lines = [line.strip() for line in note_text.splitlines() if line.strip()]
    tree_mode = []

    for raw in lines:
        level = 0
        text = raw.strip()

        if re.match(r"^\d+\.\d+\.\d+\s+", text):
            level = 2
            text = re.sub(r"^\d+\.\d+\.\d+\s+", "", text).strip()
        elif re.match(r"^\d+\.\d+\s+", text):
            level = 1
            text = re.sub(r"^\d+\.\d+\s+", "", text).strip()
        elif re.match(r"^\d+\.\s+", text):
            level = 0
            text = re.sub(r"^\d+\.\s+", "", text).strip()
        elif re.match(r"^\d+\)\s+", text):
            level = 1
            text = re.sub(r"^\d+\)\s+", "", text).strip()
        elif re.match(r"^\(\d+\)\s+", text):
            level = 2
            text = re.sub(r"^\(\d+\)\s+", "", text).strip()
        elif re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", text):
            level = 2
            text = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", text).strip()
        elif text.startswith("-- "):
            level = 2
            text = text[3:].strip()
        elif text.startswith("- "):
            level = 1
            text = text[2:].strip()

        if text:
            tree_mode.append((level, text))

    has_hierarchy = any(level > 0 for level, _ in tree_mode)
    if has_hierarchy:
        main_to_subs = {}
        sub_to_details = {}
        main_orphan_details = {}
        current_main = ""
        current_sub = ""

        for level, text in tree_mode:
            if level == 0:
                current_main = text
                current_sub = ""
                main_to_subs.setdefault(current_main, [])
            elif level == 1:
                if not current_main:
                    continue
                current_sub = text
                if current_sub not in main_to_subs[current_main]:
                    main_to_subs[current_main].append(current_sub)
                sub_to_details.setdefault((current_main, current_sub), [])
            else:
                if not current_main:
                    continue
                if not current_sub:
                    bucket = main_orphan_details.setdefault(current_main, [])
                    if text not in bucket:
                        bucket.append(text)
                else:
                    details = sub_to_details.setdefault((current_main, current_sub), [])
                    if text not in details:
                        details.append(text)

        for main, subs in main_to_subs.items():
            if subs:
                cards.append(
                    make_card(
                        study_date=study_date,
                        title=title,
                        question=f"{main}의 하위 항목을 모두 쓰세요 (쉼표 구분)",
                        answer=", ".join(subs),
                        quiz_type="multi",
                    )
                )

        for (main, sub), details in sub_to_details.items():
            if details:
                cards.append(
                    make_card(
                        study_date=study_date,
                        title=title,
                        question=f"{main} > {sub}의 세부 항목을 모두 쓰세요 (쉼표 구분)",
                        answer=", ".join(details),
                        quiz_type="multi",
                    )
                )

        for main, details in main_orphan_details.items():
            if details:
                cards.append(
                    make_card(
                        study_date=study_date,
                        title=title,
                        question=f"{main}의 세부 항목을 모두 쓰세요 (쉼표 구분)",
                        answer=", ".join(details),
                        quiz_type="multi",
                    )
                )

        if cards:
            return cards

    for line in lines:
        clean = re.sub(r"^[\-*0-9\.\)\s]+", "", line).strip()
        if not clean:
            continue

        if ":" in clean:
            left, right = clean.split(":", 1)
            keyword = left.strip()
            desc = right.strip()
            if keyword and desc:
                cards.append(make_card(study_date, title, f"{keyword}: ( )", desc, "blank"))
                cards.append(make_card(study_date, title, f"{desc}\n위 설명에 해당하는 용어는?", keyword, "short"))
                continue

    return cards


def create_story_card(study_date, title, story_text, answer_text):
    return make_card(
        study_date=study_date,
        title=title,
        question=f"스토리 빈칸/순서 맞추기\n{story_text}",
        answer=answer_text,
        quiz_type="story",
    )


def create_initials_card(study_date, title, initials_text, answer_text):
    return make_card(
        study_date=study_date,
        title=title,
        question=f"앞글자 확장하기: {initials_text}",
        answer=answer_text,
        quiz_type="initials",
    )


def hwpx_to_text(file_stream):
    lines = []
    with zipfile.ZipFile(file_stream) as zf:
        xml_files = [n for n in zf.namelist() if n.startswith("Contents/section") and n.endswith(".xml")]
        xml_files.sort()
        for name in xml_files:
            try:
                raw = zf.read(name)
                root = ET.fromstring(raw)
            except Exception:
                continue
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    lines.append(elem.text.strip())
    return "\n".join(lines)


@app.get("/")
def index():
    return """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>기술사 암기 공부</title>
</head>
<body>
  <h1>기술사 암기 공부 앱</h1>
  <p>배포 정상 확인용 간단 페이지입니다. API는 그대로 동작합니다.</p>
</body>
</html>
"""


@app.get("/api/cards")
def api_cards():
    data = load_data()
    ensure_schema(data)
    save_data(data)
    return jsonify({"cards": [sanitize(c) for c in data["cards"]], "stats": data["stats"]})


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.post("/api/notes/import")
def api_notes_import():
    payload = request.get_json(silent=True) or {}
    study_date = (payload.get("study_date") or datetime.now().strftime("%Y-%m-%d")).strip()
    title = (payload.get("title") or "").strip()
    note_text = (payload.get("note_text") or "").strip()
    if not note_text:
        return jsonify({"ok": False, "error": "note_text required"}), 400

    new_cards = note_to_cards(note_text, study_date, title)
    if not new_cards:
        return jsonify({"ok": False, "error": "생성 가능한 문장이 없습니다."}), 400

    data = load_data()
    ensure_schema(data)
    data["cards"].extend(new_cards)
    save_data(data)
    return jsonify({"ok": True, "created_count": len(new_cards)})


@app.post("/api/quiz/story")
def api_quiz_story():
    payload = request.get_json(silent=True) or {}
    study_date = (payload.get("study_date") or datetime.now().strftime("%Y-%m-%d")).strip()
    title = (payload.get("title") or "").strip()
    story_text = (payload.get("story_text") or "").strip()
    answer_text = (payload.get("answer_text") or "").strip()
    if not story_text or not answer_text:
        return jsonify({"ok": False, "error": "story_text and answer_text required"}), 400

    data = load_data()
    ensure_schema(data)
    data["cards"].append(create_story_card(study_date, title, story_text, answer_text))
    save_data(data)
    return jsonify({"ok": True})


@app.post("/api/quiz/initials")
def api_quiz_initials():
    payload = request.get_json(silent=True) or {}
    study_date = (payload.get("study_date") or datetime.now().strftime("%Y-%m-%d")).strip()
    title = (payload.get("title") or "").strip()
    initials_text = (payload.get("initials_text") or "").strip()
    answer_text = (payload.get("answer_text") or "").strip()
    if not initials_text or not answer_text:
        return jsonify({"ok": False, "error": "initials_text and answer_text required"}), 400

    data = load_data()
    ensure_schema(data)
    data["cards"].append(create_initials_card(study_date, title, initials_text, answer_text))
    save_data(data)
    return jsonify({"ok": True})


@app.post("/api/notes/upload")
def api_notes_upload():
    study_date = (request.form.get("study_date") or datetime.now().strftime("%Y-%m-%d")).strip()
    title = (request.form.get("title") or "").strip()
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"ok": False, "error": "file required"}), 400

    filename = (upload.filename or "").lower()
    try:
        if filename.endswith(".hwpx"):
            note_text = hwpx_to_text(upload.stream)
        elif filename.endswith(".txt") or filename.endswith(".md"):
            note_text = upload.read().decode("utf-8", errors="ignore")
        else:
            return jsonify({"ok": False, "error": "지원하지 않는 파일 형식입니다. (.hwpx, .txt, .md)"}), 400
    except Exception:
        return jsonify({"ok": False, "error": "파일을 읽는 중 오류가 발생했습니다."}), 400

    note_text = (note_text or "").strip()
    if not note_text:
        return jsonify({"ok": False, "error": "파일에서 텍스트를 찾지 못했습니다."}), 400

    new_cards = note_to_cards(note_text, study_date, title)
    if not new_cards:
        return jsonify({"ok": False, "error": "생성 가능한 문장을 찾지 못했습니다."}), 400

    data = load_data()
    ensure_schema(data)
    data["cards"].extend(new_cards)
    save_data(data)
    return jsonify({"ok": True, "created_count": len(new_cards)})


@app.delete("/api/cards/<card_id>")
def api_delete(card_id):
    data = load_data()
    ensure_schema(data)
    old = len(data["cards"])
    data["cards"] = [c for c in data["cards"] if c.get("id") != card_id]
    if len(data["cards"]) == old:
        return jsonify({"ok": False, "error": "not found"}), 404
    save_data(data)
    return jsonify({"ok": True})


@app.post("/api/quiz-result")
def api_quiz_result():
    payload = request.get_json(silent=True) or {}
    card_id = payload.get("id")
    correct = bool(payload.get("correct"))
    if not card_id:
        return jsonify({"ok": False, "error": "id required"}), 400

    data = load_data()
    ensure_schema(data)
    target = None
    for c in data["cards"]:
        if c.get("id") == card_id:
            target = c
            break

    if not target:
        return jsonify({"ok": False, "error": "not found"}), 404

    if correct:
        target["correct_count"] += 1
        data["stats"]["correct"] += 1
    else:
        target["wrong_count"] += 1
        data["stats"]["wrong"] += 1

    save_data(data)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
