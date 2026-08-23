import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from extensions import db
from models import (TeacherProfile, StudentProfile, Assignment, Submission, LiveClass,
                     Recording, LibraryBook, TutorMessage)
from helpers import role_required, current_user, allowed_file, save_upload
import ai_service

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _profile():
    return current_user().teacher_profile


def _my_categories():
    p = _profile()
    return (p.categories or "").split(",") if p.categories else []


@teacher_bp.before_request
@role_required("teacher")
def _guard():
    pass


@teacher_bp.route("/")
def dashboard():
    p = _profile()
    students = p.students.filter_by(status="active").all() if p else []
    assignments = Assignment.query.filter_by(teacher_id=p.id).order_by(Assignment.created_at.desc()).limit(5).all()
    upcoming = (LiveClass.query.filter_by(teacher_id=p.id)
                .filter(LiveClass.scheduled_at >= datetime.utcnow())
                .order_by(LiveClass.scheduled_at.asc()).limit(5).all())
    pending_marking = (Submission.query.join(Assignment)
                        .filter(Assignment.teacher_id == p.id, Submission.status == "submitted").count())
    return render_template("teacher/dashboard.html", profile=p, students=students, assignments=assignments,
                            upcoming=upcoming, pending_marking=pending_marking,
                            categories=current_app.config["CATEGORIES"])


@teacher_bp.route("/students")
def students():
    p = _profile()
    all_students = p.students.all()
    return render_template("teacher/students.html", profile=p, students=all_students,
                            categories=current_app.config["CATEGORIES"])


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

@teacher_bp.route("/assignments")
def assignments():
    p = _profile()
    all_assignments = Assignment.query.filter_by(teacher_id=p.id).order_by(Assignment.created_at.desc()).all()
    return render_template("teacher/assignments.html", assignments=all_assignments, profile=p,
                            categories=current_app.config["CATEGORIES"])


@teacher_bp.route("/assignments/new", methods=["GET", "POST"])
def new_assignment():
    p = _profile()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category")
        instructions = request.form.get("instructions", "").strip()
        due_date = request.form.get("due_date")

        a = Assignment(teacher_id=p.id, title=title, category=category, instructions=instructions)
        if due_date:
            try:
                a.due_date = datetime.fromisoformat(due_date)
            except ValueError:
                pass

        file = request.files.get("source_file")
        if file and file.filename and allowed_file(file.filename, current_app.config["ALLOWED_DOC_EXT"]):
            filename = save_upload(file, "assignments")
            a.source_filename = filename
            a.parse_status = "processing"

        db.session.add(a)
        db.session.commit()

        if a.source_filename and request.form.get("auto_parse") == "on":
            filepath = f"{current_app.config['UPLOAD_FOLDER']}/assignments/{a.source_filename}"
            data, err = ai_service.parse_assignment_file(filepath)
            if data:
                a.questions_json = json.dumps(data)
                a.parse_status = "done"
            else:
                a.parse_status = "failed"
                flash(f"AI parsing note: {err}", "warning")
            db.session.commit()

        flash("Assignment created and sent to your students.", "success")
        return redirect(url_for("teacher.assignment_detail", aid=a.id))

    return render_template("teacher/new_assignment.html", categories=current_app.config["CATEGORIES"])


@teacher_bp.route("/assignments/<int:aid>")
def assignment_detail(aid):
    p = _profile()
    a = Assignment.query.filter_by(id=aid, teacher_id=p.id).first_or_404()
    subs = Submission.query.filter_by(assignment_id=a.id).all()
    return render_template("teacher/assignment_detail.html", a=a, submissions=subs)


@teacher_bp.route("/assignments/<int:aid>/reparse", methods=["POST"])
def reparse_assignment(aid):
    p = _profile()
    a = Assignment.query.filter_by(id=aid, teacher_id=p.id).first_or_404()
    if not a.source_filename:
        flash("No source file to parse.", "danger")
        return redirect(url_for("teacher.assignment_detail", aid=aid))
    filepath = f"{current_app.config['UPLOAD_FOLDER']}/assignments/{a.source_filename}"
    a.parse_status = "processing"
    db.session.commit()
    data, err = ai_service.parse_assignment_file(filepath)
    if data:
        a.questions_json = json.dumps(data)
        a.parse_status = "done"
        flash("Assignment converted into interactive questions.", "success")
    else:
        a.parse_status = "failed"
        flash(f"Could not parse: {err}", "danger")
    db.session.commit()
    return redirect(url_for("teacher.assignment_detail", aid=aid))


@teacher_bp.route("/assignments/<int:aid>/generate", methods=["GET", "POST"])
def generate_questions(aid):
    p = _profile()
    a = Assignment.query.filter_by(id=aid, teacher_id=p.id).first_or_404()
    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        count = int(request.form.get("count", 5))
        qtype = request.form.get("qtype", "mcq")
        cat_label = current_app.config["CATEGORIES"].get(a.category, a.category)
        data, err = ai_service.generate_questions(topic, cat_label, count, qtype)
        if data:
            for i, q in enumerate(data):
                q["id"] = f"q{i+1}"
            a.questions_json = json.dumps(data)
            a.parse_status = "done"
            db.session.commit()
            flash("AI-generated questions added to this assignment.", "success")
        else:
            flash(f"Could not generate questions: {err}", "danger")
        return redirect(url_for("teacher.assignment_detail", aid=aid))
    return render_template("teacher/generate_questions.html", a=a)


@teacher_bp.route("/submissions/<int:sub_id>/mark", methods=["POST"])
def mark_submission(sub_id):
    sub = Submission.query.get_or_404(sub_id)
    a = sub.assignment
    p = _profile()
    if a.teacher_id != p.id:
        flash("Not authorized.", "danger")
        return redirect(url_for("teacher.assignments"))

    if sub.upload_filename:
        context = f"Assignment: {a.title}\nInstructions: {a.instructions or ''}"
        guide = request.form.get("marking_guide", "").strip() or "Use your best judgement based on the assignment."
        filepath = f"{current_app.config['UPLOAD_FOLDER']}/submissions/{sub.upload_filename}"
        data, err = ai_service.mark_uploaded_answer(context, guide, filepath)
        if data:
            sub.score = data.get("score")
            sub.max_score = data.get("max_score")
            sub.feedback = data.get("feedback")
            sub.status = "marked"
            sub.marked_at = datetime.utcnow()
            db.session.commit()
            flash("AI marking complete. Review before it's final.", "success")
        else:
            flash(f"Could not mark: {err}", "danger")
    else:
        score, total, details = ai_service.mark_online_submission(a, sub.answers())
        sub.score = score
        sub.max_score = total
        sub.feedback = "Auto-marked against the answer key."
        sub.status = "marked"
        sub.marked_at = datetime.utcnow()
        db.session.commit()
        flash("Submission auto-marked.", "success")

    return redirect(url_for("teacher.assignment_detail", aid=a.id))


# ---------------------------------------------------------------------------
# AI Tutor / teaching assistant
# ---------------------------------------------------------------------------

@teacher_bp.route("/ai-tutor")
def ai_tutor():
    u = current_user()
    history = TutorMessage.query.filter_by(user_id=u.id).order_by(TutorMessage.created_at.asc()).all()
    return render_template("teacher/ai_tutor.html", history=history, configured=ai_service.ai_configured())


@teacher_bp.route("/ai-tutor/send", methods=["POST"])
def ai_tutor_send():
    u = current_user()
    message = request.form.get("message", "").strip()
    if not message:
        return redirect(url_for("teacher.ai_tutor"))
    db.session.add(TutorMessage(user_id=u.id, sender="user", content=message))
    db.session.commit()
    history = TutorMessage.query.filter_by(user_id=u.id).order_by(TutorMessage.created_at.asc()).all()
    reply = ai_service.tutor_reply(history[:-1], message, role="teacher")
    db.session.add(TutorMessage(user_id=u.id, sender="ai", content=reply))
    db.session.commit()
    return redirect(url_for("teacher.ai_tutor"))


@teacher_bp.route("/ai-tutor/mark-tool", methods=["GET", "POST"])
def ai_mark_tool():
    """Standalone quick tool: teacher pastes correct answer + uploads a
    pdf/image of the student's answers, gets instant AI marking, without
    it needing to be tied to a formal Assignment record."""
    result = None
    if request.method == "POST":
        context = request.form.get("context", "").strip()
        correct_answer = request.form.get("correct_answer", "").strip()
        file = request.files.get("answer_file")
        if file and file.filename and allowed_file(file.filename, current_app.config["ALLOWED_DOC_EXT"]):
            filename = save_upload(file, "submissions")
            filepath = f"{current_app.config['UPLOAD_FOLDER']}/submissions/{filename}"
            data, err = ai_service.mark_uploaded_answer(context, correct_answer, filepath)
            if data:
                result = data
            else:
                flash(f"Could not mark: {err}", "danger")
        else:
            flash("Please attach a PDF or image of the student's answers.", "danger")
    return render_template("teacher/ai_mark_tool.html", result=result)


# ---------------------------------------------------------------------------
# Live classes
# ---------------------------------------------------------------------------

@teacher_bp.route("/live", methods=["GET", "POST"])
def live():
    p = _profile()
    if request.method == "POST":
        lc = LiveClass(
            teacher_id=p.id, title=request.form.get("title", "").strip(),
            category=request.form.get("category"), description=request.form.get("description", "").strip(),
            meeting_link=request.form.get("meeting_link", "").strip(),
            duration_minutes=int(request.form.get("duration_minutes") or 60),
        )
        scheduled_at = request.form.get("scheduled_at")
        if scheduled_at:
            try:
                lc.scheduled_at = datetime.fromisoformat(scheduled_at)
            except ValueError:
                pass
        db.session.add(lc)
        db.session.commit()
        flash("Live class scheduled. Your students will see it on their dashboard.", "success")
        return redirect(url_for("teacher.live"))

    upcoming = LiveClass.query.filter_by(teacher_id=p.id).order_by(LiveClass.scheduled_at.desc()).all()
    return render_template("teacher/live.html", classes=upcoming, categories=current_app.config["CATEGORIES"])


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------

@teacher_bp.route("/recordings", methods=["GET", "POST"])
def recordings():
    p = _profile()
    if request.method == "POST":
        file = request.files.get("video_file")
        if not (file and file.filename and allowed_file(file.filename, current_app.config["ALLOWED_VIDEO_EXT"])):
            flash("Please upload a valid video file (mp4, webm, mov, mkv).", "danger")
            return redirect(url_for("teacher.recordings"))
        filename = save_upload(file, "recordings")
        rec = Recording(teacher_id=p.id, title=request.form.get("title", "").strip(),
                         category=request.form.get("category"), description=request.form.get("description", "").strip(),
                         filename=filename)
        db.session.add(rec)
        db.session.commit()
        flash("Class recording uploaded.", "success")
        return redirect(url_for("teacher.recordings"))

    all_recs = Recording.query.filter_by(teacher_id=p.id).order_by(Recording.uploaded_at.desc()).all()
    return render_template("teacher/recordings.html", recordings=all_recs, categories=current_app.config["CATEGORIES"])


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

@teacher_bp.route("/library", methods=["GET", "POST"])
def library():
    p = _profile()
    if request.method == "POST":
        file = request.files.get("book_file")
        if not (file and file.filename and allowed_file(file.filename, current_app.config["ALLOWED_BOOK_EXT"])):
            flash("Please upload a valid book file (pdf or epub).", "danger")
            return redirect(url_for("teacher.library"))
        filename = save_upload(file, "library")
        book = LibraryBook(teacher_id=p.id, title=request.form.get("title", "").strip(),
                            author=request.form.get("author", "").strip(),
                            category=request.form.get("category"), filename=filename)
        db.session.add(book)
        db.session.commit()
        flash("Book added to the library.", "success")
        return redirect(url_for("teacher.library"))

    my_books = LibraryBook.query.filter_by(teacher_id=p.id).order_by(LibraryBook.uploaded_at.desc()).all()
    all_books = LibraryBook.query.order_by(LibraryBook.uploaded_at.desc()).all()
    return render_template("teacher/library.html", my_books=my_books, all_books=all_books,
                            categories=current_app.config["CATEGORIES"])
