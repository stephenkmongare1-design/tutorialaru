import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from extensions import db
from models import Assignment, Submission, LiveClass, Recording, LibraryBook, TutorMessage
from helpers import role_required, current_user, allowed_file, save_upload
import ai_service

student_bp = Blueprint("student", __name__, url_prefix="/student")


def _profile():
    return current_user().student_profile


@student_bp.before_request
@role_required("student")
def _guard():
    pass


def _needs_setup_redirect(p):
    if not p.category:
        return redirect(url_for("auth.choose_category"))
    if not p.tier:
        return redirect(url_for("auth.choose_tier"))
    if p.status == "pending_payment":
        return redirect(url_for("auth.pay_tuition"))
    return None


@student_bp.route("/")
def dashboard():
    p = _profile()
    redirect_resp = _needs_setup_redirect(p)
    if redirect_resp:
        return redirect_resp

    assignments = []
    upcoming = []
    if p.teacher_id:
        assignments = (Assignment.query.filter_by(teacher_id=p.teacher_id)
                        .order_by(Assignment.created_at.desc()).limit(5).all())
        upcoming = (LiveClass.query.filter_by(teacher_id=p.teacher_id)
                    .filter(LiveClass.scheduled_at >= datetime.utcnow())
                    .order_by(LiveClass.scheduled_at.asc()).limit(5).all())

    my_subs = {s.assignment_id: s for s in Submission.query.filter_by(student_id=p.id).all()}
    return render_template("student/dashboard.html", profile=p, assignments=assignments, upcoming=upcoming,
                            my_subs=my_subs, categories=current_app.config["CATEGORIES"],
                            tier_labels=current_app.config["TIER_LABELS"])


@student_bp.route("/assignments")
def assignments():
    p = _profile()
    redirect_resp = _needs_setup_redirect(p)
    if redirect_resp:
        return redirect_resp
    all_assignments = ([] if not p.teacher_id else
                        Assignment.query.filter_by(teacher_id=p.teacher_id).order_by(Assignment.created_at.desc()).all())
    my_subs = {s.assignment_id: s for s in Submission.query.filter_by(student_id=p.id).all()}
    return render_template("student/assignments.html", assignments=all_assignments, my_subs=my_subs)


def _get_or_create_submission(assignment_id, student_id):
    sub = Submission.query.filter_by(assignment_id=assignment_id, student_id=student_id).first()
    if not sub:
        sub = Submission(assignment_id=assignment_id, student_id=student_id, status="not_started")
        db.session.add(sub)
        db.session.commit()
    return sub


@student_bp.route("/assignments/<int:aid>")
def take_assignment(aid):
    p = _profile()
    a = Assignment.query.get_or_404(aid)
    if a.teacher_id != p.teacher_id:
        flash("This assignment isn't assigned to you.", "danger")
        return redirect(url_for("student.assignments"))
    sub = _get_or_create_submission(a.id, p.id)
    return render_template("student/take_assignment.html", a=a, sub=sub, questions=a.questions())


@student_bp.route("/assignments/<int:aid>/submit", methods=["POST"])
def submit_assignment(aid):
    p = _profile()
    a = Assignment.query.get_or_404(aid)
    if a.teacher_id != p.teacher_id:
        flash("This assignment isn't assigned to you.", "danger")
        return redirect(url_for("student.assignments"))
    sub = _get_or_create_submission(a.id, p.id)

    answers = {}
    for q in a.questions():
        val = request.form.get(f"answer_{q['id']}")
        if val is not None:
            answers[q["id"]] = val
    sub.answers_json = json.dumps(answers)

    file = request.files.get("upload_file")
    if file and file.filename and allowed_file(file.filename, current_app.config["ALLOWED_DOC_EXT"]):
        filename = save_upload(file, "submissions")
        sub.upload_filename = filename

    sub.status = "submitted"
    sub.submitted_at = datetime.utcnow()
    db.session.commit()

    # Auto-mark instantly if it was purely online tick/typed answers with a known answer key
    if not sub.upload_filename and a.questions():
        score, total, details = ai_service.mark_online_submission(a, answers)
        sub.score = score
        sub.max_score = total
        sub.feedback = "Auto-marked instantly against the answer key."
        sub.status = "marked"
        sub.marked_at = datetime.utcnow()
        db.session.commit()
        flash(f"Submitted! You scored {score}/{total}.", "success")
    else:
        flash("Assignment submitted. Your teacher will mark it soon.", "success")

    return redirect(url_for("student.assignments"))


# ---------------------------------------------------------------------------
# Live classes / recordings / library
# ---------------------------------------------------------------------------

@student_bp.route("/live")
def live():
    p = _profile()
    classes = ([] if not p.teacher_id else
               LiveClass.query.filter_by(teacher_id=p.teacher_id).order_by(LiveClass.scheduled_at.desc()).all())
    return render_template("student/live.html", classes=classes, now=datetime.utcnow())


@student_bp.route("/recordings")
def recordings():
    p = _profile()
    recs = ([] if not p.teacher_id else
            Recording.query.filter_by(teacher_id=p.teacher_id).order_by(Recording.uploaded_at.desc()).all())
    return render_template("student/recordings.html", recordings=recs)


@student_bp.route("/library")
def library():
    p = _profile()
    books = LibraryBook.query.filter_by(category=p.category).order_by(LibraryBook.uploaded_at.desc()).all()
    return render_template("student/library.html", books=books)


# ---------------------------------------------------------------------------
# AI Tutor
# ---------------------------------------------------------------------------

@student_bp.route("/ai-tutor")
def ai_tutor():
    u = current_user()
    history = TutorMessage.query.filter_by(user_id=u.id).order_by(TutorMessage.created_at.asc()).all()
    return render_template("student/ai_tutor.html", history=history, configured=ai_service.ai_configured())


@student_bp.route("/ai-tutor/send", methods=["POST"])
def ai_tutor_send():
    u = current_user()
    p = _profile()
    message = request.form.get("message", "").strip()
    if not message:
        return redirect(url_for("student.ai_tutor"))
    db.session.add(TutorMessage(user_id=u.id, sender="user", content=message))
    db.session.commit()
    history = TutorMessage.query.filter_by(user_id=u.id).order_by(TutorMessage.created_at.asc()).all()
    cat_label = current_app.config["CATEGORIES"].get(p.category, "school")
    reply = ai_service.tutor_reply(history[:-1], message, role="student", category_label=cat_label)
    db.session.add(TutorMessage(user_id=u.id, sender="ai", content=reply))
    db.session.commit()
    return redirect(url_for("student.ai_tutor"))
