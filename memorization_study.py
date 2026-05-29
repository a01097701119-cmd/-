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


def empty_data():
    return {"cards": [], "stats": {"correct": 0, "wrong": 0}}


def load_data_supabase():
    rows = supabase_request("GET", "/rest/v1/{table}", query={"id": "eq.1", "select": "data"})
    if not rows:
        return empty_data()
    return rows[0].get("data") or empty_data()


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

    return empty_data()


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
        "id": f"card-{random.randint(100000, 999999)}-{int(datetime.now().timestamp())}-{random.randint(10, 99)}",
        "title": title,
        "question": question,
        "answer": answer,
        "quiz_type": quiz_type,
        "study_date": study_date,
        "wrong_count": 0,
        "correct_count": 0,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def parse_outline_line(raw):
    text = raw.strip()
    patterns = [
        (r"^\d+\.\d+\.\d+\s+", 3),
        (r"^\d+\.\d+\s+", 2),
        (r"^\d+\.\s+", 1),
        (r"^\d+\)\s+", 1),
        (r"^\(\d+\)\s+", 2),
        (r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", 3),
        (r"^--\s+", 2),
        (r"^-\s+", 1),
    ]
    for pattern, level in patterns:
        if re.match(pattern, text):
            return level, re.sub(pattern, "", text).strip()
    return 0, text


def note_to_cards(note_text, study_date, title):
    cards = []
    lines = [line.strip() for line in note_text.splitlines() if line.strip()]
    outline = []

    for line in lines:
        level, text = parse_outline_line(line)
        if text:
            outline.append({"level": level, "text": text, "children": []})

    has_outline = any(item["level"] > 0 for item in outline)
    if has_outline:
        stack = []
        roots = []
        for item in outline:
            while stack and stack[-1]["level"] >= item["level"]:
                stack.pop()
            if stack:
                stack[-1]["children"].append(item)
            else:
                roots.append(item)
            stack.append(item)

        def add_node_cards(node, path):
            children = [child["text"] for child in node["children"]]
            if children:
                label = " > ".join(path + [node["text"]])
                cards.append(
                    make_card(
                        study_date=study_date,
                        title=title,
                        question=f"{label}의 하위 항목을 모두 쓰세요 (쉼표 구분)",
                        answer=", ".join(children),
                        quiz_type="multi",
                    )
                )
            for child in node["children"]:
                add_node_cards(child, path + [node["text"]])

        for root in roots:
            add_node_cards(root, [])

        if cards:
            return cards

    for line in lines:
        clean = re.sub(r"^[\-*0-9\.\)\s]+", "", line).strip()
        if not clean:
            continue

        if ":" in clean:
            keyword, desc = [part.strip() for part in clean.split(":", 1)]
            if keyword and desc:
                cards.append(make_card(study_date, title, f"{keyword}: ( )", desc, "blank"))
                cards.append(make_card(study_date, title, f"{desc}\n위 설명에 해당하는 용어는?", keyword, "short"))

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
                root = ET.fromstring(zf.read(name))
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
  <style>
    :root{
      --bg:#f7fafc; --card:#fff; --ink:#111827; --muted:#6b7280;
      --line:#d8dee8; --accent:#0369a1; --ok:#15803d; --bad:#b91c1c;
    }
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);font-family:"Pretendard","Noto Sans KR","Apple SD Gothic Neo",sans-serif;color:var(--ink)}
    .wrap{max-width:1080px;margin:0 auto;padding:14px}
    header{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;padding:10px 0 14px;border-bottom:1px solid var(--line);margin-bottom:14px}
    h1{font-size:22px;margin:0}
    h2{font-size:16px;margin:0 0 10px}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
    .wide{grid-column:1 / -1}
    .row{display:flex;gap:8px;flex-wrap:wrap}
    input,textarea,button{font-size:14px;border-radius:6px;border:1px solid var(--line);padding:10px}
    input,textarea{min-width:160px;flex:1;background:#fff}
    textarea{min-height:150px;resize:vertical;width:100%}
    button{border:none;background:var(--accent);color:#fff;font-weight:700;cursor:pointer}
    button.sub{background:#64748b}
    button.ok{background:var(--ok)}
    button.bad{background:var(--bad)}
    .muted{color:var(--muted);font-size:13px}
    .item{border:1px solid var(--line);border-radius:6px;padding:10px;margin-bottom:8px;background:#fbfdff}
    .hidden{display:none}
    .question{font-size:20px;font-weight:800;margin:8px 0 10px;white-space:pre-wrap}
    @media(max-width:760px){.grid{grid-template-columns:1fr}header{display:block}}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>기술사 암기 공부</h1>
        <div class="muted">날짜별 노트, 파일 업로드, 다중정답 퀴즈</div>
      </div>
      <div id="stats" class="muted"></div>
    </header>

    <div class="grid">
      <section>
        <h2>노트 붙여넣기</h2>
        <div class="row">
          <input id="studyDate" type="date" />
          <input id="noteTitle" placeholder="제목" />
        </div>
        <textarea id="noteText" placeholder="1. 화재안전기준
1) 경보설비
(1) 자동화재탐지설비
① 감지기
② 수신기"></textarea>
        <button onclick="importNote()">문제 자동 생성</button>
        <div id="importResult" class="muted"></div>
      </section>

      <section>
        <h2>파일 업로드</h2>
        <div class="row">
          <input id="fileDate" type="date" />
          <input id="fileTitle" placeholder="제목" />
        </div>
        <div class="row">
          <input id="noteFile" type="file" accept=".hwpx,.txt,.md" />
          <button onclick="uploadFileNote()">업로드</button>
        </div>
        <div id="fileUploadResult" class="muted"></div>
      </section>

      <section>
        <h2>스토리형</h2>
        <div class="row">
          <input id="storyDate" type="date" />
          <input id="storyTitle" placeholder="제목" />
        </div>
        <textarea id="storyText" placeholder="스토리 입력"></textarea>
        <div class="row">
          <input id="storyAnswer" placeholder="정답 목록, 쉼표 구분" />
          <button onclick="addStoryQuiz()">추가</button>
        </div>
        <div id="storyResult" class="muted"></div>
      </section>

      <section>
        <h2>앞글자형</h2>
        <div class="row">
          <input id="initialsDate" type="date" />
          <input id="initialsTitle" placeholder="제목" />
        </div>
        <div class="row">
          <input id="initialsText" placeholder="앞글자" />
          <input id="initialsAnswer" placeholder="정답 목록, 쉼표 구분" />
          <button onclick="addInitialsQuiz()">추가</button>
        </div>
        <div id="initialsResult" class="muted"></div>
      </section>

      <section class="wide">
        <h2>날짜별 퀴즈</h2>
        <div class="row">
          <input id="quizDate" type="date" />
          <button onclick="startQuiz(false)">랜덤 퀴즈</button>
          <button class="sub" onclick="startQuiz(true)">오답 위주</button>
        </div>
        <div id="quizBox" class="hidden item">
          <div id="quizMeta" class="muted"></div>
          <div id="quizTitle" class="muted"></div>
          <div id="quizQuestion" class="question"></div>
          <input id="userAnswer" placeholder="정답 입력" />
          <div class="row" style="margin-top:8px">
            <button onclick="checkAnswer()">채점</button>
            <button class="sub" onclick="showCorrect()">정답 보기</button>
            <button class="ok" onclick="nextQuiz(true)">맞음 기록</button>
            <button class="bad" onclick="nextQuiz(false)">틀림 기록</button>
          </div>
          <div id="judge" class="muted"></div>
        </div>
      </section>

      <section class="wide">
        <h2>등록 문제 목록</h2>
        <div id="cards"></div>
      </section>
    </div>
  </div>

<script>
let cards = [];
let stats = {correct:0, wrong:0};
let quizPool = [];
let idx = 0;

function todayStr(){
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

function normalize(s){
  return (s || '').toLowerCase().replace(/\\s+/g,'').trim();
}

function parseMulti(text){
  return (text || '').split(/[,:\\n]/).map(v => normalize(v)).filter(Boolean).sort();
}

async function loadAll(){
  const res = await fetch('/api/cards');
  const data = await res.json();
  cards = data.cards;
  stats = data.stats;
  renderStats();
  renderCards();
}

function typeName(t){
  return {blank:'괄호채우기', short:'단답형', story:'스토리형', initials:'앞글자형', multi:'다중정답형'}[t] || t || '기타';
}

function renderStats(){
  const solved = stats.correct + stats.wrong;
  const acc = solved ? (stats.correct * 100 / solved).toFixed(1) : '0.0';
  document.getElementById('stats').innerText = `문제 ${cards.length}개 | 정답 ${stats.correct} | 오답 ${stats.wrong} | ${acc}%`;
}

function renderCards(){
  const box = document.getElementById('cards');
  if(!cards.length){
    box.innerHTML = '<div class="muted">등록된 문제가 없습니다.</div>';
    return;
  }
  box.innerHTML = cards
    .sort((a,b)=> (b.study_date+b.created_at).localeCompare(a.study_date+a.created_at))
    .map(c => `<div class="item"><strong>[${c.study_date}] ${escapeHtml(c.title || '(제목 없음)')}</strong><br>
      <span class="muted">${typeName(c.quiz_type)} | 정답 ${c.correct_count} | 오답 ${c.wrong_count}</span>
      <div style="margin-top:6px;white-space:pre-wrap">${escapeHtml(c.question)}</div>
      <button class="sub" style="margin-top:8px" onclick="deleteCard('${c.id}')">삭제</button></div>`)
    .join('');
}

async function postJson(url, payload){
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const data = await res.json();
  if(!res.ok) throw new Error(data.error || '처리 실패');
  return data;
}

async function importNote(){
  try{
    const result = await postJson('/api/notes/import', {
      study_date: document.getElementById('studyDate').value || todayStr(),
      title: document.getElementById('noteTitle').value.trim(),
      note_text: document.getElementById('noteText').value.trim()
    });
    document.getElementById('importResult').innerText = `생성 완료: ${result.created_count}문제`;
    document.getElementById('noteText').value = '';
    await loadAll();
  }catch(e){ alert(e.message); }
}

async function addStoryQuiz(){
  try{
    await postJson('/api/quiz/story', {
      study_date: document.getElementById('storyDate').value || todayStr(),
      title: document.getElementById('storyTitle').value.trim(),
      story_text: document.getElementById('storyText').value.trim(),
      answer_text: document.getElementById('storyAnswer').value.trim()
    });
    document.getElementById('storyResult').innerText = '추가 완료';
    document.getElementById('storyText').value = '';
    document.getElementById('storyAnswer').value = '';
    await loadAll();
  }catch(e){ alert(e.message); }
}

async function addInitialsQuiz(){
  try{
    await postJson('/api/quiz/initials', {
      study_date: document.getElementById('initialsDate').value || todayStr(),
      title: document.getElementById('initialsTitle').value.trim(),
      initials_text: document.getElementById('initialsText').value.trim(),
      answer_text: document.getElementById('initialsAnswer').value.trim()
    });
    document.getElementById('initialsResult').innerText = '추가 완료';
    document.getElementById('initialsText').value = '';
    document.getElementById('initialsAnswer').value = '';
    await loadAll();
  }catch(e){ alert(e.message); }
}

async function uploadFileNote(){
  const fileInput = document.getElementById('noteFile');
  if(!fileInput.files.length){ alert('파일을 선택해주세요.'); return; }
  const form = new FormData();
  form.append('study_date', document.getElementById('fileDate').value || todayStr());
  form.append('title', document.getElementById('fileTitle').value.trim());
  form.append('file', fileInput.files[0]);
  const res = await fetch('/api/notes/upload', {method:'POST', body:form});
  const result = await res.json();
  if(!res.ok){ alert(result.error || '업로드 실패'); return; }
  document.getElementById('fileUploadResult').innerText = `생성 완료: ${result.created_count}문제`;
  fileInput.value = '';
  await loadAll();
}

function startQuiz(wrongOnly){
  const date = document.getElementById('quizDate').value;
  if(!date){ alert('날짜를 선택해주세요.'); return; }
  let pool = cards.filter(c => c.study_date === date);
  if(wrongOnly) pool = pool.filter(c => c.wrong_count > c.correct_count);
  if(!pool.length){ alert('해당 날짜 문제가 없습니다.'); return; }
  quizPool = shuffle(pool);
  idx = 0;
  document.getElementById('quizBox').classList.remove('hidden');
  renderQuiz();
}

function renderQuiz(){
  if(idx >= quizPool.length){
    alert('퀴즈 완료');
    document.getElementById('quizBox').classList.add('hidden');
    return;
  }
  const c = quizPool[idx];
  document.getElementById('quizMeta').innerText = `${idx + 1} / ${quizPool.length} | ${typeName(c.quiz_type)}`;
  document.getElementById('quizTitle').innerText = c.title || '';
  document.getElementById('quizQuestion').innerText = c.question;
  document.getElementById('userAnswer').value = '';
  document.getElementById('judge').innerText = '';
}

function checkAnswer(){
  const c = quizPool[idx];
  const input = document.getElementById('userAnswer').value;
  let ok = false;
  if(c.quiz_type === 'multi'){
    const mine = parseMulti(input);
    const answer = parseMulti(c.answer);
    ok = mine.length === answer.length && mine.every((v, i) => v === answer[i]);
  }else{
    ok = normalize(input) === normalize(c.answer);
  }
  document.getElementById('judge').innerText = ok ? '정답입니다.' : `오답입니다. 정답: ${c.answer}`;
}

function showCorrect(){
  const c = quizPool[idx];
  document.getElementById('judge').innerText = `정답: ${c.answer}`;
}

async function nextQuiz(correct){
  const c = quizPool[idx];
  await postJson('/api/quiz-result', {id:c.id, correct});
  idx += 1;
  await loadAll();
  renderQuiz();
}

async function deleteCard(id){
  await fetch('/api/cards/' + encodeURIComponent(id), {method:'DELETE'});
  await loadAll();
}

function shuffle(arr){
  const copy = [...arr];
  for(let i=copy.length-1;i>0;i--){
    const j = Math.floor(Math.random()*(i+1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function escapeHtml(text){
  return (text || '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#039;");
}

document.getElementById('studyDate').value = todayStr();
document.getElementById('fileDate').value = todayStr();
document.getElementById('storyDate').value = todayStr();
document.getElementById('initialsDate').value = todayStr();
loadAll();
</script>
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
