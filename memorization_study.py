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

    # 계층형 입력 우선 처리:
    # 대제목
    # - 소제목
    # -- 세부제목
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
        else:
            level = 0
            text = text.strip()
        if text:
            tree_mode.append((level, text))

    has_hierarchy = any(level > 0 for level, _ in tree_mode)
    if has_hierarchy:
        current_main = ""
        current_sub = ""
        seen_main = set()
        seen_sub = set()
        seen_detail = set()

        for level, text in tree_mode:
            if level == 0:
                current_main = text
                current_sub = ""
                if current_main not in seen_main:
                    cards.append(
                        make_card(
                            study_date=study_date,
                            title=title,
                            question="( )",
                            answer=current_main,
                            quiz_type="blank",
                        )
                    )
                    seen_main.add(current_main)
            elif level == 1:
                if not current_main:
                    current_main = "분류"
                current_sub = text
                key = f"{current_main}::{current_sub}"
                if key not in seen_sub:
                    cards.append(
                        make_card(
                            study_date=study_date,
                            title=title,
                            question=f"{current_main}의 소제목: ( )",
                            answer=current_sub,
                            quiz_type="blank",
                        )
                    )
                    seen_sub.add(key)
            else:
                if not current_main:
                    current_main = "분류"
                if not current_sub:
                    current_sub = "하위 항목"
                key = f"{current_main}::{current_sub}::{text}"
                if key not in seen_detail:
                    cards.append(
                        make_card(
                            study_date=study_date,
                            title=title,
                            question=f"{current_main} > {current_sub}의 세부제목: ( )",
                            answer=text,
                            quiz_type="blank",
                        )
                    )
                    seen_detail.add(key)

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
                cards.append(
                    make_card(
                        study_date=study_date,
                        title=title,
                        question=f"{keyword}: ( )",
                        answer=desc,
                        quiz_type="blank",
                    )
                )
                cards.append(
                    make_card(
                        study_date=study_date,
                        title=title,
                        question=f"{desc}\n위 설명에 해당하는 용어는?",
                        answer=keyword,
                        quiz_type="short",
                    )
                )
                continue

        words = clean.split()
        if len(words) >= 2:
            key = words[0]
            rest = " ".join(words[1:])
            cards.append(
                make_card(
                    study_date=study_date,
                    title=title,
                    question=f"( ) {rest}",
                    answer=key,
                    quiz_type="blank",
                )
            )
            cards.append(
                make_card(
                    study_date=study_date,
                    title=title,
                    question=clean,
                    answer=clean,
                    quiz_type="short",
                )
            )

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
            texts = []
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    texts.append(elem.text.strip())
            for t in texts:
                if t:
                    lines.append(t)
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
      --card:#fff; --ink:#0f172a; --muted:#64748b; --line:#e2e8f0;
      --accent:#0284c7; --ok:#16a34a; --bad:#dc2626;
    }
    *{box-sizing:border-box}
    body{margin:0;background:linear-gradient(180deg,#ecfeff,#f8fafc);font-family:"Pretendard","Noto Sans KR",sans-serif;color:var(--ink)}
    .wrap{max-width:960px;margin:0 auto;padding:16px}
    .panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin-bottom:12px;box-shadow:0 10px 30px rgba(2,6,23,.05)}
    .row{display:flex;gap:8px;flex-wrap:wrap}
    input,select,textarea,button{padding:10px 12px;border-radius:10px;border:1px solid var(--line);font-size:14px}
    input,select,textarea{flex:1;min-width:140px}
    textarea{min-height:150px;resize:vertical}
    button{background:var(--accent);border:none;color:#fff;font-weight:700;cursor:pointer}
    button.sub{background:#64748b}
    button.ok{background:var(--ok)}
    button.bad{background:var(--bad)}
    h1{margin:2px 0 8px;font-size:22px}
    h2{margin:0 0 10px;font-size:17px}
    .muted{color:var(--muted);font-size:13px}
    .item{border:1px solid var(--line);border-radius:12px;padding:10px;margin-bottom:8px;background:#fcfdff}
    .hidden{display:none}
    .q{font-size:20px;font-weight:700;margin:6px 0 12px}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <h1>기술사 암기 공부 앱</h1>
      <div class="muted">요약 서브노트를 날짜별로 올리면 퀴즈가 자동 생성됩니다.</div>
    </div>

    <div class="panel">
      <h2>요약 서브노트 올리기</h2>
      <div class="row">
        <input id="studyDate" type="date" />
        <input id="noteTitle" placeholder="노트 제목 (예: 소방설비 이론)" />
      </div>
      <div class="row" style="margin-top:8px">
        <textarea id="noteText" placeholder="예시 1) 용어: 설명
내화구조: 화재 시 일정 시간 구조 안전성을 유지하는 구조
피난계획: 재실자의 안전한 대피를 위한 계획

예시 2) 계층형(권장)
화재안전기준
- 경보설비
-- 자동화재탐지설비
-- 비상경보설비
- 소화설비
-- 스프링클러설비"></textarea>
      </div>
      <div class="row" style="margin-top:8px">
        <button onclick="importNote()">노트 업로드 + 퀴즈 자동 생성</button>
      </div>
      <div id="importResult" class="muted" style="margin-top:8px"></div>
    </div>

    <div class="panel">
      <h2>스토리형 퀴즈 등록</h2>
      <div class="row">
        <input id="storyDate" type="date" />
        <input id="storyTitle" placeholder="제목 (예: 대피 시나리오)" />
      </div>
      <div class="row" style="margin-top:8px">
        <textarea id="storyText" placeholder="스토리(서술문) 입력"></textarea>
      </div>
      <div class="row" style="margin-top:8px">
        <input id="storyAnswer" placeholder="정답 목록 (예: 신고, 초기소화, 대피유도, 인원점검)" />
        <button onclick="addStoryQuiz()">스토리형 추가</button>
      </div>
      <div id="storyResult" class="muted" style="margin-top:8px"></div>
    </div>

    <div class="panel">
      <h2>앞글자형 퀴즈 등록</h2>
      <div class="row">
        <input id="initialsDate" type="date" />
        <input id="initialsTitle" placeholder="제목 (예: 점검 절차)" />
      </div>
      <div class="row" style="margin-top:8px">
        <input id="initialsText" placeholder="앞글자 (예: 신초대인)" />
        <input id="initialsAnswer" placeholder="정답 목록 (예: 신고, 초기소화, 대피유도, 인원점검)" />
        <button onclick="addInitialsQuiz()">앞글자형 추가</button>
      </div>
      <div id="initialsResult" class="muted" style="margin-top:8px"></div>
    </div>

    <div class="panel">
      <h2>파일로 업로드 (PC/모바일)</h2>
      <div class="muted">지원 형식: .hwpx, .txt, .md</div>
      <div class="row" style="margin-top:8px">
        <input id="fileDate" type="date" />
        <input id="fileTitle" placeholder="파일 노트 제목 (선택)" />
      </div>
      <div class="row" style="margin-top:8px">
        <input id="noteFile" type="file" accept=".hwpx,.txt,.md" />
        <button onclick="uploadFileNote()">파일 업로드 + 자동 문제 생성</button>
      </div>
      <div id="fileUploadResult" class="muted" style="margin-top:8px"></div>
    </div>

    <div class="panel">
      <h2>날짜별 퀴즈</h2>
      <div class="row">
        <input id="quizDate" type="date" />
        <button onclick="startQuiz(false)">해당 날짜 랜덤 퀴즈</button>
        <button class="sub" onclick="startQuiz(true)">오답 위주</button>
      </div>
      <div id="quizBox" class="hidden" style="margin-top:10px;border:1px dashed #cbd5e1;border-radius:14px;padding:12px">
        <div id="quizMeta" class="muted"></div>
        <div id="quizTitle" class="muted" style="margin-top:6px"></div>
        <div id="quizQuestion" class="q"></div>
        <input id="userAnswer" placeholder="정답 입력" />
        <div class="row" style="margin-top:8px">
          <button onclick="checkAnswer()">채점</button>
          <button class="sub" onclick="showCorrect()">정답 보기</button>
        </div>
        <div id="judge" class="muted" style="margin-top:8px"></div>
        <div class="row" style="margin-top:10px">
          <button class="ok" onclick="nextQuiz(true)">맞음 기록</button>
          <button class="bad" onclick="nextQuiz(false)">틀림 기록</button>
        </div>
      </div>
    </div>

    <div class="panel">
      <h2>통계</h2>
      <div id="stats" class="muted"></div>
    </div>

    <div class="panel">
      <h2>등록 문제 목록</h2>
      <div id="cards"></div>
    </div>
  </div>

<script>
let cards = [];
let stats = {correct:0, wrong:0};
let quizPool = [];
let idx = 0;

function todayStr(){
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth()+1).padStart(2,'0');
  const day = String(d.getDate()).padStart(2,'0');
  return `${y}-${m}-${day}`;
}

function normalize(s){
  return (s || "").toLowerCase().replace(/\\s+/g,'').trim();
}

async function loadAll(){
  const res = await fetch('/api/cards');
  const data = await res.json();
  cards = data.cards;
  stats = data.stats;
  renderStats();
  renderCards();
}

function renderStats(){
  const solved = stats.correct + stats.wrong;
  const acc = solved ? (stats.correct * 100 / solved).toFixed(1) : '0.0';
  document.getElementById('stats').innerText =
    `누적 정답 ${stats.correct} | 누적 오답 ${stats.wrong} | 정답률 ${acc}% | 총 문제 ${cards.length}개`;
}

function renderCards(){
  const box = document.getElementById('cards');
  if(!cards.length){
    box.innerHTML = '<div class="muted">등록된 문제가 없습니다.</div>';
    return;
  }
  const quizTypeName = (q) => {
    if(q === 'blank') return '괄호채우기';
    if(q === 'short') return '단답형';
    if(q === 'story') return '스토리형';
    if(q === 'initials') return '앞글자형';
    return q || '기타';
  };
  box.innerHTML = cards
    .sort((a,b)=> (b.study_date+b.created_at).localeCompare(a.study_date+a.created_at))
    .map(c => `
      <div class="item">
        <strong>[${c.study_date}] ${escapeHtml(c.title || '(제목 없음)')}</strong><br/>
        <span class="muted">${quizTypeName(c.quiz_type)} | 정답 ${c.correct_count} | 오답 ${c.wrong_count}</span>
        <div style="margin-top:6px">${escapeHtml(c.question)}</div>
        <button class="sub" style="margin-top:8px" onclick="deleteCard('${c.id}')">삭제</button>
      </div>
    `).join('');
}

async function importNote(){
  const study_date = document.getElementById('studyDate').value || todayStr();
  const title = document.getElementById('noteTitle').value.trim();
  const note_text = document.getElementById('noteText').value.trim();
  if(!note_text){
    alert('노트 내용을 입력해주세요.');
    return;
  }
  const res = await fetch('/api/notes/import', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({study_date, title, note_text})
  });
  const result = await res.json();
  if(!res.ok){
    alert(result.error || '업로드에 실패했습니다.');
    return;
  }
  document.getElementById('importResult').innerText = `업로드 완료: ${result.created_count}문제가 생성되었습니다.`;
  document.getElementById('noteText').value = '';
  await loadAll();
}

async function addStoryQuiz(){
  const study_date = document.getElementById('storyDate').value || todayStr();
  const title = document.getElementById('storyTitle').value.trim();
  const story_text = document.getElementById('storyText').value.trim();
  const answer_text = document.getElementById('storyAnswer').value.trim();
  if(!story_text || !answer_text){
    alert('스토리와 정답을 입력해주세요.');
    return;
  }
  const res = await fetch('/api/quiz/story', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({study_date, title, story_text, answer_text})
  });
  const result = await res.json();
  if(!res.ok){
    alert(result.error || '추가 실패');
    return;
  }
  document.getElementById('storyResult').innerText = '스토리형 퀴즈 1개 추가 완료';
  document.getElementById('storyText').value = '';
  document.getElementById('storyAnswer').value = '';
  await loadAll();
}

async function addInitialsQuiz(){
  const study_date = document.getElementById('initialsDate').value || todayStr();
  const title = document.getElementById('initialsTitle').value.trim();
  const initials_text = document.getElementById('initialsText').value.trim();
  const answer_text = document.getElementById('initialsAnswer').value.trim();
  if(!initials_text || !answer_text){
    alert('앞글자와 정답을 입력해주세요.');
    return;
  }
  const res = await fetch('/api/quiz/initials', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({study_date, title, initials_text, answer_text})
  });
  const result = await res.json();
  if(!res.ok){
    alert(result.error || '추가 실패');
    return;
  }
  document.getElementById('initialsResult').innerText = '앞글자형 퀴즈 1개 추가 완료';
  document.getElementById('initialsText').value = '';
  document.getElementById('initialsAnswer').value = '';
  await loadAll();
}

async function uploadFileNote(){
  const study_date = document.getElementById('fileDate').value || todayStr();
  const title = document.getElementById('fileTitle').value.trim();
  const fileInput = document.getElementById('noteFile');
  if(!fileInput.files || !fileInput.files.length){
    alert('업로드할 파일을 선택해주세요.');
    return;
  }
  const form = new FormData();
  form.append('study_date', study_date);
  form.append('title', title);
  form.append('file', fileInput.files[0]);

  const res = await fetch('/api/notes/upload', {
    method:'POST',
    body: form
  });
  const result = await res.json();
  if(!res.ok){
    alert(result.error || '파일 업로드에 실패했습니다.');
    return;
  }
  document.getElementById('fileUploadResult').innerText =
    `업로드 완료: ${result.created_count}문제가 생성되었습니다.`;
  fileInput.value = '';
  await loadAll();
}

async function deleteCard(id){
  await fetch('/api/cards/' + encodeURIComponent(id), {method:'DELETE'});
  await loadAll();
}

function startQuiz(wrongOnly){
  const date = document.getElementById('quizDate').value;
  if(!date){
    alert('퀴즈 날짜를 먼저 선택해주세요.');
    return;
  }
  let pool = cards.filter(c => c.study_date === date);
  if(wrongOnly){
    pool = pool.filter(c => c.wrong_count > c.correct_count);
  }
  if(!pool.length){
    alert('해당 날짜 문제가 없습니다.');
    return;
  }
  quizPool = shuffle(pool);
  idx = 0;
  document.getElementById('quizBox').classList.remove('hidden');
  renderQuiz();
}

function renderQuiz(){
  if(idx >= quizPool.length){
    alert('해당 날짜 퀴즈 완료');
    document.getElementById('quizBox').classList.add('hidden');
    return;
  }
  const c = quizPool[idx];
  let typeName = '단답형';
  if(c.quiz_type === 'blank') typeName = '괄호채우기';
  if(c.quiz_type === 'story') typeName = '스토리형';
  if(c.quiz_type === 'initials') typeName = '앞글자형';
  document.getElementById('quizMeta').innerText = `${idx + 1} / ${quizPool.length} | ${typeName}`;
  document.getElementById('quizTitle').innerText = c.title || '';
  document.getElementById('quizQuestion').innerText = c.question;
  document.getElementById('userAnswer').value = '';
  document.getElementById('judge').innerText = '';
}

function checkAnswer(){
  const c = quizPool[idx];
  const userAnswer = document.getElementById('userAnswer').value;
  const ok = normalize(userAnswer) === normalize(c.answer);
  document.getElementById('judge').innerText = ok ? '정답입니다.' : `오답입니다. 정답: ${c.answer}`;
}

function showCorrect(){
  const c = quizPool[idx];
  document.getElementById('judge').innerText = `정답: ${c.answer}`;
}

async function nextQuiz(correct){
  const c = quizPool[idx];
  await fetch('/api/quiz-result', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id:c.id, correct})
  });
  idx += 1;
  await loadAll();
  renderQuiz();
}

function shuffle(arr){
  const c = [...arr];
  for(let i=c.length-1;i>0;i--){
    const j = Math.floor(Math.random()*(i+1));
    [c[i],c[j]] = [c[j],c[i]];
  }
  return c;
}

function escapeHtml(text){
  return (text || "")
    .replaceAll('&','&amp;')
    .replaceAll('<','&lt;')
    .replaceAll('>','&gt;')
    .replaceAll('"','&quot;')
    .replaceAll("'","&#039;");
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
        return jsonify({"ok": False, "error": "생성 가능한 문장이 없습니다. 줄바꿈으로 내용을 나눠 입력해주세요."}), 400

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
