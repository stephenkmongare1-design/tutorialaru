"""
Central place for every AI-powered feature in the platform:
  - AI Tutor chat (students get help learning; teachers get help setting questions)
  - Turning a teacher's uploaded PDF/image assignment into interactive
    tick/click questions the student can answer on a phone or laptop
  - AI marking of a student's submitted answers (typed, or a photo/PDF
    of handwritten work)

Everything degrades gracefully if no ANTHROPIC_API_KEY is configured -
the rest of the app still works, these features just explain that AI
is not configured yet instead of crashing.
"""
import base64
import io
import json
import re

from anthropic import Anthropic
from flask import current_app
import fitz  # PyMuPDF
from PIL import Image

_client_cache = {}


def _client():
    key = current_app.config.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    if key not in _client_cache:
        _client_cache[key] = Anthropic(api_key=key)
    return _client_cache[key]


def _model():
    return current_app.config.get("ANTHROPIC_MODEL", "claude-sonnet-5")


def ai_configured():
    return bool(current_app.config.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------------
# File -> image helpers (so PDFs and photos can both be sent to the model)
# ---------------------------------------------------------------------------

def file_to_images_b64(filepath, max_pages=6):
    """Return a list of {media_type, data} dicts, one per page/image,
    base64-encoded, resized to keep requests small."""
    out = []
    lower = filepath.lower()
    if lower.endswith(".pdf"):
        doc = fitz.open(filepath)
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("png")
            out.append(_encode_image_bytes(img_bytes, "image/png"))
        doc.close()
    else:
        with open(filepath, "rb") as f:
            raw = f.read()
        media_type = "image/jpeg" if lower.endswith((".jpg", ".jpeg")) else "image/png"
        out.append(_encode_image_bytes(raw, media_type, resize=True))
    return out


def _encode_image_bytes(raw, media_type, resize=False):
    if resize or media_type == "image/png":
        try:
            im = Image.open(io.BytesIO(raw))
            im.thumbnail((1600, 1600))
            buf = io.BytesIO()
            fmt = "PNG" if media_type == "image/png" else "JPEG"
            im.convert("RGB" if fmt == "JPEG" else im.mode).save(buf, format=fmt)
            raw = buf.getvalue()
        except Exception:
            pass
    return {"media_type": media_type, "data": base64.standard_b64encode(raw).decode("utf-8")}


def _extract_json(text):
    """Pull the first JSON object/array out of a model response, even if
    it added stray commentary around it."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# 1. AI Tutor chat (student learning help + teacher assistant)
# ---------------------------------------------------------------------------

TUTOR_SYSTEM_STUDENT = (
    "You are a friendly, patient AI tutor inside a Kenyan CBC tutoring platform. "
    "The student you are talking to is in {category}. Explain concepts step by step, "
    "in simple language appropriate for their level, use short examples, and check their "
    "understanding with a small follow-up question when it helps. Keep answers focused and "
    "not too long. Never do a student's assignment for them wholesale - guide them to the "
    "answer instead, unless they are just asking to understand a concept."
)

TUTOR_SYSTEM_TEACHER = (
    "You are an AI teaching assistant for a teacher on a tutoring platform. Help them "
    "set exam/assignment questions, suggest rubrics, explain curriculum topics, and mark "
    "student work when they give you the correct answers plus the student's answers. "
    "Be concise, practical, and format question sets clearly with numbering."
)


def tutor_reply(history, user_message, role, category_label=None):
    client = _client()
    if not client:
        return ("AI Tutor is not configured yet. Ask your admin to add an ANTHROPIC_API_KEY "
                "in the .env file to switch this on.")

    system = (TUTOR_SYSTEM_STUDENT.format(category=category_label or "school")
              if role == "student" else TUTOR_SYSTEM_TEACHER)

    messages = []
    for h in history[-12:]:
        messages.append({"role": "user" if h.sender == "user" else "assistant", "content": h.content})
    messages.append({"role": "user", "content": user_message})

    resp = client.messages.create(
        model=_model(),
        max_tokens=1000,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# ---------------------------------------------------------------------------
# 2. Teacher: generate questions for a topic
# ---------------------------------------------------------------------------

def generate_questions(topic, category_label, count, question_type):
    client = _client()
    if not client:
        return None, "AI is not configured. Add an ANTHROPIC_API_KEY to enable this."

    prompt = (
        f"Create {count} {question_type} assignment questions on the topic '{topic}' "
        f"for a {category_label} student following the Kenyan CBC curriculum.\n\n"
        "Return ONLY valid JSON: a list of objects, each with:\n"
        '  "type": "mcq" or "short_answer",\n'
        '  "question": "...",\n'
        '  "options": ["A ...", "B ...", "C ...", "D ..."]  (only for mcq),\n'
        '  "answer": "the correct option letter or the correct short answer"\n'
        "No commentary, no markdown fences, just the JSON array."
    )
    resp = client.messages.create(
        model=_model(),
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    data = _extract_json(text)
    if data is None:
        return None, "The AI response could not be parsed. Please try again."
    return data, None


# ---------------------------------------------------------------------------
# 3. Convert an uploaded PDF/image assignment into interactive questions
# ---------------------------------------------------------------------------

def parse_assignment_file(filepath):
    """Reads a teacher's uploaded assignment (pdf/image) and returns a
    structured question list students can tick/answer online."""
    client = _client()
    if not client:
        return None, "AI is not configured. Add an ANTHROPIC_API_KEY to enable this."

    try:
        images = file_to_images_b64(filepath)
    except Exception as e:
        return None, f"Could not read the file: {e}"

    if not images:
        return None, "No readable pages/images found in the file."

    content = [{
        "type": "text",
        "text": (
            "This is a school assignment/worksheet. Read every question carefully and "
            "convert it into structured JSON so a student can answer it on a phone or "
            "laptop screen.\n\n"
            "Return ONLY a JSON array. Each item must have:\n"
            '  "number": the question number as shown,\n'
            '  "type": "mcq" | "true_false" | "short_answer" | "fill_blank",\n'
            '  "question": the full question text (include the passage/instructions if needed),\n'
            '  "options": ["A ...","B ...","C ...","D ..."]  (mcq only, else omit or empty list),\n'
            '  "answer": the correct answer if determinable from the sheet, else null\n\n'
            "Keep the original numbering and wording as closely as possible. "
            "If a question cannot be represented on-screen (e.g. a diagram to be drawn), "
            'still include it with type "short_answer" and a note in the question text that '
            "a written/drawn answer is expected.\n"
            "No commentary outside the JSON array."
        ),
    }]
    for img in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
        })

    resp = client.messages.create(
        model=_model(),
        max_tokens=4000,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    data = _extract_json(text)
    if data is None:
        return None, "The AI could not confidently extract questions from this file. Try a clearer scan/photo."
    # attach stable ids
    for i, q in enumerate(data):
        q["id"] = f"q{i+1}"
    return data, None


# ---------------------------------------------------------------------------
# 4. Mark a student's submission
# ---------------------------------------------------------------------------

def mark_online_submission(assignment, submission_answers):
    """Auto-mark tick/typed answers against the AI-extracted answer key."""
    questions = assignment.questions()
    total = 0
    score = 0
    details = []
    for q in questions:
        qid = q.get("id")
        correct = (q.get("answer") or "").strip().lower()
        given = (submission_answers.get(qid) or "").strip().lower()
        total += 1
        is_correct = None
        if correct:
            is_correct = (given == correct) or (given and given in correct) or (correct in given and given)
            if is_correct:
                score += 1
        details.append({
            "id": qid, "question": q.get("question"), "given": submission_answers.get(qid, ""),
            "correct": q.get("answer"), "is_correct": is_correct,
        })
    return score, total, details


def mark_uploaded_answer(question_context, correct_answer, filepath):
    """Teacher gives the AI the correct answer + a pdf/image of the student's
    handwritten answers; AI grades it and returns feedback."""
    client = _client()
    if not client:
        return None, "AI is not configured. Add an ANTHROPIC_API_KEY to enable this."

    try:
        images = file_to_images_b64(filepath)
    except Exception as e:
        return None, f"Could not read the file: {e}"
    if not images:
        return None, "No readable pages/images found."

    content = [{
        "type": "text",
        "text": (
            f"Assignment / question context:\n{question_context}\n\n"
            f"Correct answer(s) / marking guide provided by the teacher:\n{correct_answer}\n\n"
            "The attached image(s) show a student's handwritten or typed answers. "
            "Mark the work fairly against the marking guide. Return ONLY JSON with:\n"
            '  "score": number of marks awarded,\n'
            '  "max_score": total marks available,\n'
            '  "feedback": 2-4 sentences of constructive feedback for the student,\n'
            '  "per_question": [{"question": "...", "awarded": true/false/"partial", "comment": "..."}]\n'
            "No commentary outside the JSON."
        ),
    }]
    for img in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
        })

    resp = client.messages.create(
        model=_model(),
        max_tokens=2000,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    data = _extract_json(text)
    if data is None:
        return None, "The AI could not produce a structured mark for this submission."
    return data, None
