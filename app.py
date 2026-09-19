import os
import re
import time
import traceback
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template_string, Response, stream_with_context
from google import genai

load_dotenv()

app = Flask(__name__)

api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("Please set GOOGLE_API_KEY in your .env file")

client = genai.Client(api_key=api_key)

FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-1.5-flash"]


# ---------- Fast local cleanup ----------
def clean_symbols(text):
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u2026", "...")
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "")
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


TONES = {
    "casual": "Write in a relaxed, friendly, conversational tone. Contractions are fine.",
    "professional": "Write in a clear, confident, professional tone. No slang.",
    "academic": "Write in a formal, precise, academic tone. Avoid contractions.",
    "simple": "Write in very plain English. Short sentences. Easy for anyone to read.",
    "storytelling": "Write in an engaging, narrative, storytelling tone.",
}

LEVELS = {
    "light": "Lightly edit. Keep the original sentence structure and wording as much as possible. Only smooth out obvious robotic phrasing.",
    "medium": "Rewrite at the sentence level. Vary sentence length. Make it sound like a person wrote it.",
    "heavy": "Fully rewrite. Restructure sentences. Add natural rhythm and variation. Make it undeniably human while keeping every fact and idea.",
}


def build_prompt(text, tone, level, custom):
    tone_instruction = TONES.get(tone, TONES["professional"])
    level_instruction = LEVELS.get(level, LEVELS["medium"])
    extra = f"\nAdditional instructions from the user: {custom.strip()}" if custom and custom.strip() else ""
    return f"""You are an expert editor who makes AI-generated text sound human.

Tone: {tone_instruction}
Strength: {level_instruction}{extra}

Rules:
- Keep every fact and idea. Do not add new information.
- Do not add commentary, headings, or explanation. Return only the rewritten text.
- Avoid em-dashes, smart quotes, and other robotic punctuation.
- Match the original language (if the input is Spanish, output Spanish, etc.).

Text to rewrite:
{text}"""


HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AIrefiner</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✨</text></svg>">
  <style>
    :root {
      --bg: #fafafa;
      --text: #1a1a1a;
      --muted: #666;
      --panel: #ffffff;
      --border: #e5e5e5;
      --input-bg: #ffffff;
      --btn-primary: #111;
      --btn-primary-text: #ffffff;
      --btn-secondary: #eeeeee;
      --btn-secondary-text: #111111;
      --chip-bg: #f3f3f3;
      --accent: #0a7c2f;
    }
    [data-theme="dark"] {
      --bg: #121212;
      --text: #e8e8e8;
      --muted: #9a9a9a;
      --panel: #1e1e1e;
      --border: #333333;
      --input-bg: #181818;
      --btn-primary: #f0f0f0;
      --btn-primary-text: #111111;
      --btn-secondary: #2a2a2a;
      --btn-secondary-text: #e8e8e8;
      --chip-bg: #262626;
      --accent: #4ade80;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, Segoe UI, Arial, sans-serif;
      max-width: 950px; margin: 30px auto; padding: 20px;
      color: var(--text); background: var(--bg); transition: background 0.2s, color 0.2s;
    }
    header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    h1 { margin: 0; font-size: 28px; }
    p.sub { color: var(--muted); margin: 4px 0 20px; }
    .themeBtn {
      background: var(--btn-secondary); color: var(--btn-secondary-text);
      border: none; padding: 8px 14px; border-radius: 8px;
      cursor: pointer; font-size: 14px; font-weight: 600;
    }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
    .box { position: relative; }
    textarea {
      width: 100%; height: 240px; padding: 12px; font-size: 15px;
      border: 1px solid var(--border); border-radius: 8px; resize: vertical;
      font-family: inherit; background: var(--input-bg); color: var(--text);
    }
    .counter {
      font-size: 12px; color: var(--muted); text-align: right;
      margin-top: 4px;
    }
    .controls {
      display: flex; flex-wrap: wrap; gap: 16px; align-items: center;
      margin: 14px 0; padding: 14px; background: var(--panel);
      border: 1px solid var(--border); border-radius: 8px;
    }
    .controls label { font-size: 14px; font-weight: 600; }
    select, input[type=text] {
      padding: 6px 10px; border-radius: 6px; border: 1px solid var(--border);
      background: var(--input-bg); color: var(--text); font-size: 14px;
    }
    .custom-row {
      margin: 0 0 14px; padding: 14px; background: var(--panel);
      border: 1px solid var(--border); border-radius: 8px;
    }
    .custom-row label { font-size: 14px; font-weight: 600; display: block; margin-bottom: 6px; }
    .custom-row input[type=text] { width: 100%; }
    .row { display: flex; align-items: center; gap: 10px; margin-top: 6px; flex-wrap: wrap; }
    button {
      padding: 10px 18px; font-size: 15px; font-weight: 600;
      border: none; border-radius: 8px; cursor: pointer;
    }
    .primary { background: var(--btn-primary); color: var(--btn-primary-text); }
    .primary:disabled { opacity: 0.5; cursor: not-allowed; }
    .secondary { background: var(--btn-secondary); color: var(--btn-secondary-text); }
    .status { font-size: 13px; color: var(--muted); margin-left: 8px; }
    .history {
      margin-top: 30px; padding: 14px; background: var(--panel);
      border: 1px solid var(--border); border-radius: 8px;
    }
    .history h3 { margin: 0 0 10px; font-size: 16px; }
    .history .empty { color: var(--muted); font-size: 13px; }
    .histItem {
      display: block; width: 100%; text-align: left; padding: 10px;
      margin-bottom: 6px; background: var(--chip-bg); color: var(--text);
      border: 1px solid var(--border); border-radius: 6px;
      cursor: pointer; font-size: 13px; font-weight: 400;
    }
    .histItem:hover { border-color: var(--accent); }
    .histMeta { color: var(--muted); font-size: 11px; margin-top: 4px; }
  </style>
</head>
<body>
  <header>
    <h1>AIrefiner</h1>
    <button class="themeBtn" onclick="toggleTheme()" id="themeBtn">🌙 Dark</button>
  </header>
  <p class="sub">Paste AI text, pick a tone, refine it into natural human writing.</p>

  <div class="grid">
    <div class="box">
      <textarea id="input" placeholder="Paste AI text here..."></textarea>
      <div class="counter" id="inCounter">0 chars · 0 words</div>
    </div>
    <div class="box">
      <textarea id="output" placeholder="Result appears here..." readonly></textarea>
      <div class="counter" id="outCounter">0 chars · 0 words</div>
    </div>
  </div>

  <div class="controls">
    <label>Tone
      <select id="tone">
        <option value="casual">Casual</option>
        <option value="professional" selected>Professional</option>
        <option value="academic">Academic</option>
        <option value="simple">Simple</option>
        <option value="storytelling">Storytelling</option>
      </select>
    </label>

    <label>Strength
      <input type="range" id="level" min="0" max="2" value="1" step="1">
      <span id="levelLabel">Medium</span>
    </label>

    <label>
      <input type="checkbox" id="quickFix" checked>
      Quick symbol cleanup
    </label>
  </div>

  <div class="custom-row">
    <label for="custom">Custom instructions (optional)</label>
    <input type="text" id="custom" placeholder="e.g. avoid the word 'delve', keep it under 100 words">
  </div>

  <div class="row">
    <button class="primary" id="goBtn" onclick="humanize()">Humanize</button>
    <button class="secondary" onclick="copyOutput()">Copy</button>
    <button class="secondary" onclick="downloadOutput()">Download .txt</button>
    <button class="secondary" onclick="clearAll()">Clear</button>
    <span class="status" id="status"></span>
  </div>

  <div class="history">
    <h3>History <button class="secondary" style="float:right;padding:4px 10px;font-size:12px" onclick="clearHistory()">Clear</button></h3>
    <div id="histList"><div class="empty">No history yet. Your last 20 refinements will appear here.</div></div>
  </div>

  <script>
    // ----- Theme -----
    function applyTheme(t) {
      document.documentElement.setAttribute('data-theme', t);
      document.getElementById('themeBtn').textContent = t === 'dark' ? '☀️ Light' : '🌙 Dark';
    }
    function toggleTheme() {
      const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      localStorage.setItem('theme', cur);
      applyTheme(cur);
    }
    (function initTheme() {
      const saved = localStorage.getItem('theme');
      const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      applyTheme(saved || (prefersDark ? 'dark' : 'light'));
    })();

    // ----- Counters -----
    function count(el, target) {
      const txt = el.value || '';
      const chars = txt.length;
      const words = txt.trim() ? txt.trim().split(/\s+/).length : 0;
      document.getElementById(target).textContent = chars + ' chars · ' + words + ' words';
    }
    const inputEl = document.getElementById('input');
    const outputEl = document.getElementById('output');
    inputEl.addEventListener('input', () => count(inputEl, 'inCounter'));
    outputEl.addEventListener('input', () => count(outputEl, 'outCounter'));

    // ----- Strength slider -----
    const levels = ["light", "medium", "heavy"];
    const levelNames = ["Light", "Medium", "Heavy"];
    const levelSlider = document.getElementById('level');
    levelSlider.oninput = () => { document.getElementById('levelLabel').textContent = levelNames[levelSlider.value]; };

    // ----- History -----
    const HIST_KEY = 'airefiner_history';
    function getHistory() {
      try { return JSON.parse(localStorage.getItem(HIST_KEY) || '[]'); } catch(e) { return []; }
    }
    function saveHistory(entry) {
      const h = getHistory();
      h.unshift(entry);
      localStorage.setItem(HIST_KEY, JSON.stringify(h.slice(0, 20)));
      renderHistory();
    }
    function clearHistory() {
      if (!confirm('Clear all history?')) return;
      localStorage.removeItem(HIST_KEY);
      renderHistory();
    }
    function renderHistory() {
      const list = document.getElementById('histList');
      const h = getHistory();
      if (!h.length) {
        list.innerHTML = '<div class="empty">No history yet. Your last 20 refinements will appear here.</div>';
        return;
      }
      list.innerHTML = '';
      h.forEach((item, i) => {
        const btn = document.createElement('button');
        btn.className = 'histItem';
        const preview = (item.input || '').slice(0, 100) + ((item.input || '').length > 100 ? '…' : '');
        btn.innerHTML = preview + '<div class="histMeta">' + (item.tone||'') + ' · ' + (item.level||'') + ' · ' + new Date(item.ts).toLocaleString() + '</div>';
        btn.onclick = () => {
          inputEl.value = item.input || '';
          outputEl.value = item.output || '';
          count(inputEl, 'inCounter');
          count(outputEl, 'outCounter');
          window.scrollTo({top: 0, behavior: 'smooth'});
        };
        list.appendChild(btn);
      });
    }
    renderHistory();

    // ----- Main action -----
    async function humanize() {
      const status = document.getElementById('status');
      const btn = document.getElementById('goBtn');
      const text = inputEl.value;
      if (!text.trim()) { status.textContent = 'Paste some text first.'; return; }

      btn.disabled = true;
      status.textContent = 'Thinking...';
      outputEl.value = '';
      count(outputEl, 'outCounter');

      const payload = {
        text: text,
        tone: document.getElementById('tone').value,
        level: levels[levelSlider.value],
        quick_fix: document.getElementById('quickFix').checked,
        custom: document.getElementById('custom').value
      };

      let usedStream = false;
      try {
        const res = await fetch('/humanize_stream', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        if (res.ok && res.body && res.body.getReader) {
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          usedStream = true;
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            outputEl.value += decoder.decode(value, {stream: true});
            count(outputEl, 'outCounter');
            outputEl.scrollTop = outputEl.scrollHeight;
          }
          status.textContent = 'Done.';
        }
      } catch (e) {
        usedStream = false;
      }

      // Fallback to non-streaming if stream failed entirely
      if (!usedStream || !outputEl.value) {
        try {
          const res = await fetch('/humanize', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (data.result) {
            outputEl.value = data.result;
            count(outputEl, 'outCounter');
            status.textContent = 'Done.';
          } else {
            outputEl.value = 'Error: ' + (data.error || 'Unknown error');
            status.textContent = 'Failed.';
          }
        } catch (e) {
          outputEl.value = 'Error: ' + e.message;
          status.textContent = 'Failed.';
        }
      }

      if (outputEl.value && !outputEl.value.startsWith('Error')) {
        saveHistory({
          input: text,
          output: outputEl.value,
          tone: payload.tone,
          level: payload.level,
          ts: Date.now()
        });
      }

      btn.disabled = false;
    }

    function copyOutput() {
      if (!outputEl.value) return;
      outputEl.select();
      document.execCommand('copy');
      document.getElementById('status').textContent = 'Copied.';
    }

    function downloadOutput() {
      if (!outputEl.value) return;
      const blob = new Blob([outputEl.value], {type: 'text/plain;charset=utf-8'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'airefiner-' + new Date().toISOString().slice(0,19).replace(/[:T]/g,'-') + '.txt';
      a.click();
      URL.revokeObjectURL(a.href);
      document.getElementById('status').textContent = 'Downloaded.';
    }

    function clearAll() {
      inputEl.value = '';
      outputEl.value = '';
      count(inputEl, 'inCounter');
      count(outputEl, 'outCounter');
      document.getElementById('status').textContent = '';
    }
  </script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


def _prepare(payload):
    text = (payload.get("text") or "").strip()
    tone = payload.get("tone", "professional")
    level = payload.get("level", "medium")
    quick_fix = bool(payload.get("quick_fix", True))
    custom = payload.get("custom", "")

    if quick_fix:
        text = clean_symbols(text)

    prompt = build_prompt(text, tone, level, custom)
    return text, prompt


@app.route("/humanize", methods=["POST"])
def humanize():
    data = request.get_json() or {}
    text, prompt = _prepare(data)

    if not text:
        return jsonify({"error": "No text provided"}), 400

    last_error = None
    for model_name in FALLBACK_MODELS:
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                result = (response.text or "").strip()
                return jsonify({"result": result})
            except Exception as e:
                last_error = e
                err = str(e).lower()
                is_busy = any(k in err for k in ("503", "unavailable", "429", "rate", "overloaded"))
                if is_busy:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break

    traceback.print_exc()
    return jsonify({"error": f"All models busy. Last error: {last_error}"}), 503


@app.route("/humanize_stream", methods=["POST"])
def humanize_stream():
    data = request.get_json() or {}
    text, prompt = _prepare(data)

    if not text:
        return jsonify({"error": "No text provided"}), 400

    def generate():
        last_error = None
        for model_name in FALLBACK_MODELS:
            for attempt in range(2):
                try:
                    stream = client.models.generate_content_stream(
                        model=model_name, contents=prompt
                    )
                    iterator = iter(stream)
                    first = next(iterator)
                    if first.text:
                        yield first.text
                    for chunk in iterator:
                        if chunk.text:
                            yield chunk.text
                    return
                except StopIteration:
                    return
                except Exception as e:
                    last_error = e
                    err = str(e).lower()
                    is_busy = any(k in err for k in ("503", "unavailable", "429", "rate", "overloaded"))
                    if is_busy:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    break
        yield f"\n\n[Error: all models busy. {last_error}]"

    return Response(
        stream_with_context(generate()),
        mimetype="text/plain; charset=utf-8",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


if __name__ == "__main__":
    app.run(debug=True)