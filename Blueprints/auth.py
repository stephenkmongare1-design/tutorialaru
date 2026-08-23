from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from extensions import db
from models import User, TeacherProfile, StudentProfile, Payment
from helpers import current_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def landing():
    if session.get("user_id"):
        return redirect(url_for(f"{session.get('role')}.dashboard"))
    return render_template("auth/landing.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Incorrect email or password.", "danger")
            return redirect(url_for("auth.login"))
        if not user.is_active:
            flash("This account has been disabled. Contact the admin.", "danger")
            return redirect(url_for("auth.login"))
        session["user_id"] = user.id
        session["role"] = user.role
        session["name"] = user.full_name
        flash(f"Welcome back, {user.full_name.split()[0]}!", "success")
        return redirect(url_for(f"{user.role}.dashboard"))
    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.landing"))


@auth_bp.route("/register")
def register_choice():
    return render_template("auth/register_choice.html")


# ---------------------------------------------------------------------------
# Student registration: account -> category -> teacher tier -> matched
# teacher -> pay tuition -> active
# ---------------------------------------------------------------------------

@auth_bp.route("/register/student", methods=["GET", "POST"])
def register_student():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        guardian_name = request.form.get("guardian_name", "").strip()
        guardian_phone = request.form.get("guardian_phone", "").strip()

        if not all([full_name, email, password]):
            flash("Name, email and password are required.", "danger")
            return redirect(url_for("auth.register_student"))
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return redirect(url_for("auth.register_student"))

        user = User(role="student", full_name=full_name, email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        profile = StudentProfile(
            user_id=user.id, status="pending_payment",
            guardian_name=guardian_name, guardian_phone=guardian_phone,
        )
        db.session.add(profile)
        db.session.commit()

        session["user_id"] = user.id
        session["role"] = "student"
        session["name"] = user.full_name
        flash("Account created! Now choose your class category.", "success")
        return redirect(url_for("auth.choose_category"))

    return render_template("auth/register_student.html")


@auth_bp.route("/register/student/category", methods=["GET", "POST"])
def choose_category():
    user = current_user()
    if not user or user.role != "student":
        return redirect(url_for("auth.login"))
    profile = user.student_profile
    if request.method == "POST":
        category = request.form.get("category")
        if category not in current_app.config["CATEGORIES"]:
            flash("Please choose a valid category.", "danger")
            return redirect(url_for("auth.choose_category"))
        profile.category = category
        db.session.commit()
        return redirect(url_for("auth.choose_tier"))
    return render_template("auth/choose_category.html", categories=current_app.config["CATEGORIES"], profile=profile)


@auth_bp.route("/register/student/tier", methods=["GET", "POST"])
def choose_tier():
    user = current_user()
    if not user or user.role != "student":
        return redirect(url_for("auth.login"))
    profile = user.student_profile
    if not profile.category:
        return redirect(url_for("auth.choose_category"))

    if request.method == "POST":
        tier = request.form.get("tier")
        if tier not in current_app.config["TIER_PRICES"]:
            flash("Please choose a valid teacher type.", "danger")
            return redirect(url_for("auth.choose_tier"))
        profile.tier = tier
        profile.status = "pending_payment"
        db.session.commit()
        return redirect(url_for("auth.pay_tuition"))

    return render_template(
        "auth/choose_tier.html", profile=profile,
        prices=current_app.config["TIER_PRICES"], labels=current_app.config["TIER_LABELS"],
    )


@auth_bp.route("/register/student/pay", methods=["GET", "POST"])
def pay_tuition():
    user = current_user()
    if not user or user.role != "student":
        return redirect(url_for("auth.login"))
    profile = user.student_profile
    if not profile.tier:
        return redirect(url_for("auth.choose_tier"))

    amount = current_app.config["TIER_PRICES"][profile.tier]

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        # --- MVP payment simulation -------------------------------------
        # In production, replace this block with a real M-Pesa Daraja
        # STK Push request, and only mark the payment 'completed' once
        # the callback confirms success. For this MVP we record the
        # payment as completed immediately so the flow can be tested
        # end-to-end without live payment credentials.
        payment = Payment(
            user_id=user.id, purpose="tuition", amount=amount,
            method="mpesa", phone=phone, reference=f"TUT-{user.id}-{int(datetime.utcnow().timestamp())}",
            status="completed",
        )
        db.session.add(payment)
        profile.status = "pending_teacher_assignment"
        db.session.commit()

        _auto_assign_teacher(profile)
        db.session.commit()

        flash("Payment received! Your account is now active.", "success")
        return redirect(url_for("student.dashboard"))

    return render_template("auth/pay_tuition.html", profile=profile, amount=amount,
                            label=current_app.config["TIER_LABELS"][profile.tier])


def _auto_assign_teacher(student_profile):
    """Try to auto-match an active teacher of the right tier/category.
    If none is available yet, the student stays 'pending_teacher_assignment'
    and an admin assigns one manually."""
    candidates = (TeacherProfile.query
                  .filter_by(tier=student_profile.tier, license_status="active")
                  .filter(TeacherProfile.categories.contains(student_profile.category))
                  .all())
    if not candidates:
        return
    best = min(candidates, key=lambda t: t.student_count())
    student_profile.teacher_id = best.id
    student_profile.status = "active"


# ---------------------------------------------------------------------------
# Teacher registration: account -> licensing (pay 1500/3yrs, or free +
# admin approval)
# ---------------------------------------------------------------------------

@auth_bp.route("/register/teacher", methods=["GET", "POST"])
def register_teacher():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        subjects = request.form.get("subjects", "").strip()
        bio = request.form.get("bio", "").strip()
        tier = request.form.get("tier", "standard")
        categories = request.form.getlist("categories")

        if not all([full_name, email, password]):
            flash("Name, email and password are required.", "danger")
            return redirect(url_for("auth.register_teacher"))
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return redirect(url_for("auth.register_teacher"))
        if tier not in current_app.config["TIER_PRICES"]:
            tier = "standard"
        if not categories:
            categories = ["primary"]

        user = User(role="teacher", full_name=full_name, email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        profile = TeacherProfile(
            user_id=user.id, tier=tier, subjects=subjects, bio=bio,
            categories=",".join(categories), license_status="pending",
        )
        db.session.add(profile)
        db.session.commit()

        session["user_id"] = user.id
        session["role"] = "teacher"
        session["name"] = user.full_name
        flash("Account created! Choose how you'd like to activate your teaching license.", "success")
        return redirect(url_for("auth.teacher_license"))

    return render_template("auth/register_teacher.html", categories=current_app.config["CATEGORIES"],
                            prices=current_app.config["TIER_PRICES"], labels=current_app.config["TIER_LABELS"])


@auth_bp.route("/register/teacher/license", methods=["GET", "POST"])
def teacher_license():
    user = current_user()
    if not user or user.role != "teacher":
        return redirect(url_for("auth.login"))
    profile = user.teacher_profile
    fee = current_app.config["TEACHER_LICENSE_FEE"]
    years = current_app.config["TEACHER_LICENSE_YEARS"]

    if request.method == "POST":
        choice = request.form.get("choice")
        if choice == "pay":
            phone = request.form.get("phone", "").strip()
            payment = Payment(
                user_id=user.id, purpose="license", amount=fee, method="mpesa",
                phone=phone, reference=f"LIC-{user.id}-{int(datetime.utcnow().timestamp())}",
                status="completed",
            )
            db.session.add(payment)
            profile.license_status = "active"
            profile.approved_by_admin = True
            profile.license_paid_at = datetime.utcnow()
            profile.license_expires_at = datetime.utcnow() + timedelta(days=365 * years)
            db.session.commit()
            flash("License activated! You're all set to start teaching.", "success")
            return redirect(url_for("teacher.dashboard"))
        else:
            profile.license_status = "free_pending_admin"
            db.session.commit()
            flash("You're in! You can explore the system now. Talk to the admin so your own "
                  "students can be registered under you.", "info")
            return redirect(url_for("teacher.dashboard"))

    return render_template("auth/teacher_license.html", profile=profile, fee=fee, years=years)
