from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from extensions import db
from models import User, TeacherProfile, StudentProfile, Payment, Assignment, LiveClass, LibraryBook
from helpers import role_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@role_required("admin")
def dashboard():
    stats = {
        "teachers": TeacherProfile.query.count(),
        "active_teachers": TeacherProfile.query.filter_by(license_status="active").count(),
        "pending_teachers": TeacherProfile.query.filter_by(license_status="free_pending_admin").count(),
        "students": StudentProfile.query.count(),
        "active_students": StudentProfile.query.filter_by(status="active").count(),
        "unassigned_students": StudentProfile.query.filter_by(status="pending_teacher_assignment").count(),
        "assignments": Assignment.query.count(),
        "live_classes": LiveClass.query.count(),
        "revenue": db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0))
                    .filter(Payment.status == "completed").scalar(),
    }
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(8).all()
    unassigned = StudentProfile.query.filter_by(status="pending_teacher_assignment").all()
    return render_template("admin/dashboard.html", stats=stats, recent_payments=recent_payments,
                            unassigned=unassigned)


@admin_bp.route("/teachers")
@role_required("admin")
def teachers():
    q = request.args.get("q", "").strip()
    query = TeacherProfile.query.join(User)
    if q:
        query = query.filter(User.full_name.ilike(f"%{q}%"))
    all_teachers = query.order_by(TeacherProfile.id.desc()).all()
    return render_template("admin/teachers.html", teachers=all_teachers,
                            categories=current_app.config["CATEGORIES"],
                            labels=current_app.config["TIER_LABELS"], q=q)


@admin_bp.route("/teachers/<int:tid>/approve", methods=["POST"])
@role_required("admin")
def approve_teacher(tid):
    t = TeacherProfile.query.get_or_404(tid)
    years = current_app.config["TEACHER_LICENSE_YEARS"]
    t.approved_by_admin = True
    if t.license_status != "active":
        t.license_status = "active"
        t.license_expires_at = datetime.utcnow() + timedelta(days=365 * years)
    db.session.commit()
    flash(f"{t.user.full_name} approved and activated.", "success")
    return redirect(url_for("admin.teachers"))


@admin_bp.route("/teachers/<int:tid>/toggle", methods=["POST"])
@role_required("admin")
def toggle_teacher(tid):
    t = TeacherProfile.query.get_or_404(tid)
    t.user.is_active = not t.user.is_active
    db.session.commit()
    flash(f"{t.user.full_name} is now {'active' if t.user.is_active else 'disabled'}.", "info")
    return redirect(url_for("admin.teachers"))


@admin_bp.route("/teachers/add", methods=["GET", "POST"])
@role_required("admin")
def add_teacher():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password") or "Teach@123"
        tier = request.form.get("tier", "standard")
        subjects = request.form.get("subjects", "").strip()
        categories = request.form.getlist("categories") or ["primary"]
        activate = request.form.get("activate") == "on"

        if User.query.filter_by(email=email).first():
            flash("That email is already registered.", "danger")
            return redirect(url_for("admin.add_teacher"))

        user = User(role="teacher", full_name=full_name, email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        years = current_app.config["TEACHER_LICENSE_YEARS"]
        profile = TeacherProfile(
            user_id=user.id, tier=tier, subjects=subjects,
            categories=",".join(categories),
            license_status="active" if activate else "free_pending_admin",
            approved_by_admin=activate,
            license_expires_at=datetime.utcnow() + timedelta(days=365 * years) if activate else None,
        )
        db.session.add(profile)
        db.session.commit()
        flash(f"Teacher {full_name} added. Temporary password: {password}", "success")
        return redirect(url_for("admin.teachers"))

    return render_template("admin/add_teacher.html", categories=current_app.config["CATEGORIES"],
                            labels=current_app.config["TIER_LABELS"])


@admin_bp.route("/students")
@role_required("admin")
def students():
    q = request.args.get("q", "").strip()
    query = StudentProfile.query.join(User)
    if q:
        query = query.filter(User.full_name.ilike(f"%{q}%"))
    all_students = query.order_by(StudentProfile.id.desc()).all()
    teachers_list = TeacherProfile.query.all()
    return render_template("admin/students.html", students=all_students, teachers=teachers_list,
                            categories=current_app.config["CATEGORIES"], labels=current_app.config["TIER_LABELS"], q=q)


@admin_bp.route("/students/<int:sid>/assign", methods=["POST"])
@role_required("admin")
def assign_student(sid):
    s = StudentProfile.query.get_or_404(sid)
    teacher_id = request.form.get("teacher_id")
    s.teacher_id = int(teacher_id) if teacher_id else None
    if s.teacher_id:
        s.status = "active"
    db.session.commit()
    flash(f"{s.user.full_name} assigned to {s.teacher.user.full_name if s.teacher else 'no teacher'}.", "success")
    return redirect(url_for("admin.students"))


@admin_bp.route("/students/add", methods=["GET", "POST"])
@role_required("admin")
def add_student():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password") or "Learn@123"
        category = request.form.get("category")
        tier = request.form.get("tier")
        teacher_id = request.form.get("teacher_id")
        guardian_name = request.form.get("guardian_name", "").strip()
        guardian_phone = request.form.get("guardian_phone", "").strip()

        if User.query.filter_by(email=email).first():
            flash("That email is already registered.", "danger")
            return redirect(url_for("admin.add_student"))

        user = User(role="student", full_name=full_name, email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        profile = StudentProfile(
            user_id=user.id, category=category, tier=tier,
            teacher_id=int(teacher_id) if teacher_id else None,
            status="active" if teacher_id else "pending_teacher_assignment",
            guardian_name=guardian_name, guardian_phone=guardian_phone,
        )
        db.session.add(profile)
        db.session.commit()
        flash(f"Student {full_name} added. Temporary password: {password}", "success")
        return redirect(url_for("admin.students"))

    teachers_list = TeacherProfile.query.filter_by(license_status="active").all()
    return render_template("admin/add_student.html", categories=current_app.config["CATEGORIES"],
                            labels=current_app.config["TIER_LABELS"], teachers=teachers_list)


@admin_bp.route("/payments")
@role_required("admin")
def payments():
    all_payments = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template("admin/payments.html", payments=all_payments)


@admin_bp.route("/library")
@role_required("admin")
def library():
    books = LibraryBook.query.order_by(LibraryBook.uploaded_at.desc()).all()
    return render_template("admin/library.html", books=books, categories=current_app.config["CATEGORIES"])
