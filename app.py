import os
import re
import traceback
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template_string
from google import genai

load_dotenv()

app = Flask(__name__)

api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("Please set GOOGLE_API_KEY in your .env file")

client = genai.Client(api_key=api_key)

MODEL = "gemini-3.6-flash"

# ---------- Fast local cleanup (no AI needed) ----------
def clean_symbols(text):
    text = text.replace("\u2014", "-").replace("\u2013", "-")   # em/en dash
    text = text.replace("\u201c", '"').replace("\u201d", '"')   # smart double quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")   # smart single quotes
    text = text.replace("\u2026", "...")                        # ellipsis
    text = text.replace("\u00a0", " ")                          # non-breaking space
    text = text.replace("\u200b", "")                           # zero-width space
    text = re.sub(r" {2,}", " ", text)                          # double spaces
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)                # space before punct
    return text.strip()


# ---------- Tone + level instructions ----------
TONES = {
    "casual": "Write in a relaxed, friendly, conversational tone. Contractions are fine.",
    "professional": "Write in a clear, confident, professional tone. No slang.",
    "academic": "Write in a formal, precise, academic tone. Avoid contractions.",
    "simple": "Write in very plain English. Short sentences. Easy for anyone to read.",
    "storytelling": "Write in an engaging, narrative, storytelling tone.",
}

LEVELS = {
    "light": (
        "Lightly edit. Keep the original sentence structure and wording as much as possible. "
        "Only smooth out obvious robotic phrasing."
    ),
    "medium": (
        "Rewrite at the sentence level. Vary sentence length. Make it sound like a person wrote it."
    ),
    "heavy": (
        "Fully rewrite. Restructure sentences. Add natural rhythm and variation. "
        "Make it undeniably human while keeping every fact and idea."
    ),
}


HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Free AI Refiner</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, Segoe UI, Arial, sans-serif;
      max-width: 900px; margin: 30px auto; padding: 20px;
      color: #1a1a1a; background: #fafafa;
    }
    h1 { margin-bottom: 4px; }
    p.sub { color: #666; margin-top: 0; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
    textarea {
      width: 100%; height: 240px; padding: 12px; font-size: 15px;
      border: 1px solid #ddd; border-radius: 8px; resize: vertical;
      font-family: inherit; background: white;
    }
    .controls {
      display: flex; flex-wrap: wrap; gap: 16px; align-items: center;
      margin: 14px 0; padding: 14px; background: white;
      border: 1px solid #eee; border-radius: 8px;
    }
    .controls label { font-size: 14px; color: #333; font-weight: 600; }
    select, input[type=range] { font-size: 14px; }
    select { padding: 6px 10px; border-radius: 6px; border: 1px solid #ccc; }
    button {
      padding: 10px 18px; font-size: 15px; font-weight: 600;
      border: none; border-radius: 8px; cursor: pointer;
    }
    .primary { background: #111; color: white; }
    .primary:disabled { background: #888; cursor: not-allowed; }
    .secondary { background: #eee; color: #111; }
    .status { font-size: 13px; color: #666; margin-left: 8px; }
    .row { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
    .tick { color: #0a7c2f; font-weight: 600; font-size: 13px; }
  </style>
</head>
<body>
  <h1>Free AI Refiner</h1>
  <p class="sub">Paste AI text. Pick a tone and strength. Click AI Refiner.</p>

  <div class="grid">
    <textarea id="input" placeholder="Paste AI text here..."></textarea>
    <textarea id="output" placeholder="Result appears here..." readonly></textarea>
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
      Quick symbol cleanup first
    </label>
  </div>

  <div class="row">
    <button class="primary" id="goBtn" onclick="humanize()">Humanize</button>
    <button class="secondary" onclick="copyOutput()">Copy result</button>
    <span class="status" id="status"></span>
  </div>

  <script>
    const levels = ["light", "medium", "heavy"];
    const levelNames = ["Light", "Medium", "Heavy"];
    const levelSlider = document.getElementById('level');
    const levelLabel = document.getElementById('levelLabel');
    levelSlider.oninput = () => { levelLabel.textContent = levelNames[levelSlider.value]; };

    async function humanize() {
      const input = document.getElementById('input').value;
      const output = document.getElementById('output');
      const status = document.getElementById('status');
      const btn = document.getElementById('goBtn');

      if (!input.trim()) {
        status.textContent = 'Paste some text first.';
        return;
      }

      btn.disabled = true;
      status.textContent = 'Thinking...';

      try {
        const res = await fetch('/humanize', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            text: input,
            tone: document.getElementById('tone').value,
            level: levels[levelSlider.value],
            quick_fix: document.getElementById('quickFix').checked
          })
        });
        const data = await res.json();
        if (data.result) {
          output.value = data.result;
          status.textContent = 'Done.';
        } else {
          output.value = 'Error: ' + (data.error || 'Unknown error');
          status.textContent = 'Failed.';
        }
      } catch (e) {
        output.value = 'Error: ' + e.message;
        status.textContent = 'Failed.';
      } finally {
        btn.disabled = false;
      }
    }

    function copyOutput() {
      const output = document.getElementById('output');
      if (!output.value) return;
      output.select();
      document.execCommand('copy');
      document.getElementById('status').textContent = 'Copied.';
    }
  </script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/humanize", methods=["POST"])
def humanize():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    tone = data.get("tone", "professional")
    level = data.get("level", "medium")
    quick_fix = bool(data.get("quick_fix", True))

    if not text:
        return jsonify({"error": "No text provided"}), 400

    # Step 1: fast local symbol cleanup (free, instant)
    if quick_fix:
        text = clean_symbols(text)

    # Step 2: build prompt
    tone_instruction = TONES.get(tone, TONES["professional"])
    level_instruction = LEVELS.get(level, LEVELS["medium"])

    prompt = f"""You are an expert editor who makes AI-generated text sound human.

Tone: {tone_instruction}
Strength: {level_instruction}

Rules:
- Keep every fact and idea. Do not add new information.
- Do not add commentary, headings, or explanation. Return only the rewritten text.
- Avoid em-dashes, smart quotes, and other robotic punctuation.
- Match the original language (if the input is Spanish, output Spanish, etc.).

Text to rewrite:
{text}"""

    # Step 3: call the AI
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt
        )
        result = (response.text or "").strip()
        return jsonify({"result": result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)