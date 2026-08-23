import os
import json
import uuid
from datetime import datetime, timedelta, time

import streamlit as st
from werkzeug.utils import secure_filename

# Streamlit Cloud exposes secrets through st.secrets. Copy simple secret values
# into the environment before importing config.py/app.py, because the existing
# TutorAI configuration reads environment variables.
try:
    for _key, _value in st.secrets.items():
        if isinstance(_value, (str, int, float)):
            os.environ.setdefault(_key, str(_value))
except Exception:
    pass

# Reuse the existing database models and AI service.
# The Flask app is only used to initialise SQLAlchemy/config; Streamlit is the UI.
from app import app as flask_app
from extensions import db
from models import (
    User, TeacherProfile, StudentProfile, Payment, Assignment,
    Submission, LiveClass, Recording, LibraryBook, TutorMessage,
)
import ai_service


st.set_page_config(
    page_title="TutorAI",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- TutorAI visual system ----------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}
[data-testid="stAppViewContainer"] {
    background: #f7f9fc;
}
[data-testid="stHeader"] {
    background: rgba(255,255,255,0.88);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #102a43 0%, #163b5c 100%);
}
[data-testid="stSidebar"] * {
    color: #f7fbff !important;
}
[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: 10px;
}
.hero {
    background: linear-gradient(135deg, #12395b 0%, #1677a8 55%, #2aa7a0 100%);
    padding: 30px 34px;
    border-radius: 22px;
    color: white;
    margin-bottom: 22px;
    box-shadow: 0 14px 40px rgba(18,57,91,.16);
}
.hero h1 { margin: 0; font-size: 34px; font-weight: 800; }
.hero p { margin: 8px 0 0; opacity: .88; font-size: 15px; }
.brand {
    display:flex; align-items:center; gap:12px; margin-bottom:20px;
}
.brand-icon {
    width:42px;height:42px;border-radius:12px;
    display:flex;align-items:center;justify-content:center;
    background:#2aa7a0;color:white;font-size:22px;font-weight:800;
}
.brand-name {font-size:20px;font-weight:800;color:white;}
.card {
    background:white;
    border:1px solid #e7edf3;
    border-radius:18px;
    padding:20px;
    box-shadow:0 6px 24px rgba(20,50,80,.05);
    height:100%;
}
.card-title {font-size:14px;color:#60758a;font-weight:600;margin-bottom:6px;}
.card-value {font-size:29px;font-weight:800;color:#16324a;}
.card-sub {font-size:12px;color:#7c8c9a;margin-top:4px;}
.section-title {font-size:22px;font-weight:800;color:#17344d;margin:12px 0 14px;}
.pill {
    display:inline-block;padding:5px 10px;border-radius:999px;
    background:#e8f7f5;color:#177c76;font-size:12px;font-weight:700;
}
.login-shell {
    max-width: 520px;
    margin: 7vh auto 0 auto;
    background:white;
    padding:34px;
    border-radius:24px;
    border:1px solid #e5ebf1;
    box-shadow:0 18px 55px rgba(20,50,80,.10);
}
.small-muted {color:#74879a;font-size:13px;}
</style>
""", unsafe_allow_html=True)

CATEGORIES = flask_app.config["CATEGORIES"]
TIER_PRICES = flask_app.config["TIER_PRICES"]
TIER_LABELS = flask_app.config["TIER_LABELS"]
UPLOAD_FOLDER = flask_app.config["UPLOAD_FOLDER"]


def init_app():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    for folder in ("assignments", "submissions", "recordings", "library", "avatars"):
        os.makedirs(os.path.join(UPLOAD_FOLDER, folder), exist_ok=True)
    # create_app() already calls create_all(), but this is harmless and protects
    # against a Streamlit process starting after the DB file was removed.
    with flask_app.app_context():
        db.create_all()
        seed_admin()


def seed_admin():
    email = flask_app.config["ADMIN_EMAIL"]
    if not User.query.filter_by(email=email).first():
        user = User(
            role="admin",
            full_name="System Admin",
            email=email,
            phone="",
        )
        user.set_password(flask_app.config["ADMIN_PASSWORD"])
        db.session.add(user)
        db.session.commit()


def login(email, password):
    with flask_app.app_context():
        user = User.query.filter_by(email=email.strip().lower()).first()
        if user and user.is_active and user.check_password(password):
            return {"id": user.id, "role": user.role}
    return None


def current_user():
    uid = st.session_state.get("user_id")
    if not uid:
        return None
    with flask_app.app_context():
        u = db.session.get(User, uid)
        if not u:
            return None
        return {
            "id": u.id,
            "role": u.role,
            "full_name": u.full_name,
            "email": u.email,
        }


def save_uploaded(uploaded_file, subfolder):
    original = secure_filename(uploaded_file.name or "upload")
    filename = f"{uuid.uuid4().hex[:10]}_{original}"
    folder = os.path.join(UPLOAD_FOLDER, subfolder)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return filename, path


def logout():
    for key in ("user_id", "role"):
        st.session_state.pop(key, None)
    st.rerun()


def brand_sidebar():
    st.markdown(
        '<div class="brand"><div class="brand-icon">🎓</div><div class="brand-name">TutorAI</div></div>',
        unsafe_allow_html=True,
    )


def hero(title, subtitle):
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def metric_cards(items):
    cols = st.columns(len(items))
    for col, (label, value, sub) in zip(cols, items):
        with col:
            st.markdown(
                f'<div class="card"><div class="card-title">{label}</div>'
                f'<div class="card-value">{value}</div><div class="card-sub">{sub}</div></div>',
                unsafe_allow_html=True,
            )


def section_title(title, subtitle=None):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="small-muted">{subtitle}</div>', unsafe_allow_html=True)


def header(user):
    hero(
        f"Good to see you, {user['full_name'].split()[0]} 👋",
        f"Your TutorAI {user['role']} workspace — learn, teach, and manage everything in one place.",
    )


def render_login():
    st.markdown(
        '<div class="login-shell">'
        '<div style="text-align:center;font-size:42px;">🎓</div>'
        '<h1 style="text-align:center;color:#16324a;margin-bottom:4px;">TutorAI</h1>'
        '<p style="text-align:center;color:#74879a;margin-bottom:25px;">'
        'Smart learning for teachers and students</p>',
        unsafe_allow_html=True,
    )
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password", placeholder="••••••••")
        submitted = st.form_submit_button("Sign in to TutorAI", use_container_width=True, type="primary")

    if submitted:
        result = login(email, password)
        if result:
            st.session_state.update(result)
            st.rerun()
        else:
            st.error("Invalid email/password, or this account is disabled.")

    st.markdown(
        f'<div style="margin-top:18px;text-align:center" class="small-muted">'
        f'Admin account: <b>{flask_app.config["ADMIN_EMAIL"]}</b></div></div>',
        unsafe_allow_html=True,
    )


def admin_dashboard():
    with flask_app.app_context():
        teachers = TeacherProfile.query.count()
        active_teachers = TeacherProfile.query.filter_by(license_status="active").count()
        students = StudentProfile.query.count()
        active_students = StudentProfile.query.filter_by(status="active").count()
        assignments = Assignment.query.count()
        payments = Payment.query.filter_by(status="completed").count()

    section_title("Admin dashboard", "Overview of your TutorAI platform.")
    metric_cards([
        ("Teachers", teachers, f"{active_teachers} active"),
        ("Students", students, f"{active_students} active"),
        ("Assignments", assignments, "Across all teachers"),
        ("Payments", payments, "Completed"),
    ])

    st.write("")
    section_title("Recent payments")
    with flask_app.app_context():
        rows = Payment.query.order_by(Payment.created_at.desc()).limit(20).all()
        data = [
            {
                "Date": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "",
                "User": p.user.full_name if p.user else "",
                "Purpose": p.purpose,
                "Amount (KES)": p.amount,
                "Status": p.status,
            }
            for p in rows
        ]
    if data:
        st.dataframe(data, use_container_width=True, hide_index=True)
    else:
        st.info("No payments yet.")


def admin_manage_users():
    st.subheader("Manage users")
    with flask_app.app_context():
        teachers = TeacherProfile.query.order_by(TeacherProfile.id.desc()).all()
        students = StudentProfile.query.order_by(StudentProfile.id.desc()).all()

    tab1, tab2, tab3 = st.tabs(["Teachers", "Students", "Add user"])

    with tab1:
        for t in teachers:
            u = t.user
            cols = st.columns([2, 2, 1, 1])
            cols[0].write(f"**{u.full_name}**")
            cols[1].write(u.email)
            cols[2].write(t.license_status)
            if cols[3].button("Toggle", key=f"toggle_t_{t.id}"):
                with flask_app.app_context():
                    obj = db.session.get(TeacherProfile, t.id)
                    obj.user.is_active = not obj.user.is_active
                    db.session.commit()
                st.rerun()

    with tab2:
        with flask_app.app_context():
            active_teachers = TeacherProfile.query.filter_by(license_status="active").all()
            students = StudentProfile.query.order_by(StudentProfile.id.desc()).all()

        for s in students:
            u = s.user
            cols = st.columns([2, 2, 2, 2])
            cols[0].write(f"**{u.full_name}**")
            cols[1].write(u.email)
            cols[2].write(CATEGORIES.get(s.category, s.category or ""))
            teacher_names = {"Unassigned": None}
            for t in active_teachers:
                teacher_names[f"{t.user.full_name} (#{t.id})"] = t.id
            options = list(teacher_names)
            current = next(
                (name for name, tid in teacher_names.items() if tid == s.teacher_id),
                "Unassigned",
            )
            choice = cols[3].selectbox(
                "Teacher",
                options,
                index=options.index(current),
                key=f"teacher_{s.id}",
                label_visibility="collapsed",
            )
            new_tid = teacher_names[choice]
            if new_tid != s.teacher_id:
                with flask_app.app_context():
                    obj = db.session.get(StudentProfile, s.id)
                    obj.teacher_id = new_tid
                    obj.status = "active" if new_tid else "pending_teacher_assignment"
                    db.session.commit()
                st.rerun()

    with tab3:
        role = st.selectbox("Role", ["teacher", "student"])
        with st.form("add_user"):
            full_name = st.text_input("Full name")
            email = st.text_input("Email").strip().lower()
            phone = st.text_input("Phone")
            password = st.text_input("Temporary password", type="password")
            category = st.selectbox("Category", list(CATEGORIES), format_func=CATEGORIES.get) if role == "student" else None
            tier = st.selectbox("Teacher/student tier", list(TIER_PRICES), format_func=lambda x: f"{TIER_LABELS[x]} — KES {TIER_PRICES[x]:,}")
            add = st.form_submit_button("Create user", use_container_width=True)

        if add:
            if not full_name or not email or not password:
                st.error("Name, email and password are required.")
            else:
                with flask_app.app_context():
                    if User.query.filter_by(email=email).first():
                        st.error("That email is already registered.")
                    else:
                        user = User(role=role, full_name=full_name, email=email, phone=phone)
                        user.set_password(password)
                        db.session.add(user)
                        db.session.flush()
                        if role == "teacher":
                            profile = TeacherProfile(
                                user_id=user.id,
                                tier=tier,
                                license_status="active",
                                approved_by_admin=True,
                                license_expires_at=datetime.utcnow() + timedelta(
                                    days=365 * flask_app.config["TEACHER_LICENSE_YEARS"]
                                ),
                            )
                            db.session.add(profile)
                        else:
                            profile = StudentProfile(
                                user_id=user.id,
                                category=category,
                                tier=tier,
                                status="pending_teacher_assignment",
                            )
                            db.session.add(profile)
                        db.session.commit()
                st.success(f"{role.title()} created successfully.")
                st.rerun()


def tutor_chat(user):
    with flask_app.app_context():
        profile = user["role"] == "student" and db.session.get(User, user["id"]).student_profile
        category_label = CATEGORIES.get(profile.category) if profile else None
        history = (
            TutorMessage.query.filter_by(user_id=user["id"])
            .order_by(TutorMessage.created_at.asc()).all()
        )

    st.subheader("🤖 AI Tutor")
    if not ai_service.ai_configured():
        st.warning("AI is not configured. Add ANTHROPIC_API_KEY to Streamlit Secrets.")

    for msg in history[-20:]:
        with st.chat_message("user" if msg.sender == "user" else "assistant"):
            st.write(msg.content)

    prompt = st.chat_input("Ask your tutor something…")
    if prompt:
        with flask_app.app_context():
            db.session.add(TutorMessage(user_id=user["id"], sender="user", content=prompt))
            db.session.commit()
            history = (
                TutorMessage.query.filter_by(user_id=user["id"])
                .order_by(TutorMessage.created_at.asc()).all()
            )
            reply = ai_service.tutor_reply(
                history[:-1], prompt, role=user["role"], category_label=category_label
            )
            db.session.add(TutorMessage(user_id=user["id"], sender="ai", content=reply))
            db.session.commit()
        st.rerun()


def teacher_dashboard(user):
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).teacher_profile
        student_count = profile.student_count()
        assignments = Assignment.query.filter_by(teacher_id=profile.id).count()
        classes = LiveClass.query.filter_by(teacher_id=profile.id).count()

    section_title("Teacher dashboard", "Everything you need to manage your classroom.")
    metric_cards([
        ("My students", student_count, "Assigned learners"),
        ("Assignments", assignments, "Created by you"),
        ("Live classes", classes, "Scheduled sessions"),
    ])
    st.success(
        f"License: {profile.license_status}"
        + (f" · expires {profile.license_expires_at:%Y-%m-%d}" if profile.license_expires_at else "")
    )


def teacher_generate(user):
    st.subheader("✨ AI question generator")
    topic = st.text_input("Topic", placeholder="Fractions, photosynthesis, grammar…")
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).teacher_profile
    category = st.selectbox("Student level", list(CATEGORIES), format_func=CATEGORIES.get)
    count = st.slider("Number of questions", 1, 20, 5)
    qtype = st.selectbox("Question type", ["mixed", "multiple-choice", "short-answer"])
    if st.button("Generate questions", type="primary"):
        if not topic.strip():
            st.error("Enter a topic.")
            return
        with flask_app.app_context():
            data, err = ai_service.generate_questions(topic, CATEGORIES[category], count, qtype)
        if err:
            st.error(err)
        else:
            st.session_state["generated_questions"] = data

    data = st.session_state.get("generated_questions")
    if data:
        st.json(data)


def teacher_create_assignment(user):
    st.subheader("📝 Create assignment")
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).teacher_profile

    title = st.text_input("Assignment title")
    category = st.selectbox("Category", list(CATEGORIES), format_func=CATEGORIES.get)
    instructions = st.text_area("Instructions")
    due = st.date_input("Due date")
    upload = st.file_uploader(
        "Optional PDF/image to convert into interactive questions",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
    )

    if st.button("Create assignment", type="primary"):
        if not title.strip():
            st.error("Enter an assignment title.")
            return

        filename = None
        filepath = None
        questions = st.session_state.pop("generated_questions", None)

        with flask_app.app_context():
            if upload:
                filename, filepath = save_uploaded(upload, "assignments")
                questions, err = ai_service.parse_assignment_file(filepath)
                if err:
                    st.error(err)
                    return

            assignment = Assignment(
                teacher_id=profile.id,
                title=title.strip(),
                category=category,
                instructions=instructions,
                source_filename=filename,
                questions_json=json.dumps(questions or []),
                parse_status="done" if questions else "none",
                due_date=datetime.combine(due, datetime.min.time()),
            )
            db.session.add(assignment)
            db.session.commit()
        st.success("Assignment created.")
        st.rerun()


def teacher_assignments(user):
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).teacher_profile
        assignments = Assignment.query.filter_by(teacher_id=profile.id).order_by(Assignment.created_at.desc()).all()

    st.subheader("📚 Your assignments")
    for a in assignments:
        with st.expander(f"{a.title} · {CATEGORIES.get(a.category, a.category)}"):
            st.write(a.instructions or "No instructions.")
            st.write(f"Questions: {len(a.questions())}")
            if a.due_date:
                st.write(f"Due: {a.due_date:%Y-%m-%d}")
            if a.questions():
                st.json(a.questions())


def teacher_live_classes(user):
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).teacher_profile
    st.subheader("🎥 Live classes")
    with st.form("live_class"):
        title = st.text_input("Title")
        category = st.selectbox("Category", list(CATEGORIES), format_func=CATEGORIES.get)
        description = st.text_area("Description")
        meeting_link = st.text_input("Meeting link (Zoom/Meet)")
        scheduled_date = st.date_input("Scheduled date")
        scheduled_time = st.time_input("Scheduled time", value=time(18, 0))
        duration = st.number_input("Duration (minutes)", 15, 300, 60)
        create = st.form_submit_button("Schedule")
    if create:
        with flask_app.app_context():
            lc = LiveClass(
                teacher_id=profile.id,
                title=title,
                category=category,
                description=description,
                meeting_link=meeting_link,
                scheduled_at=datetime.combine(scheduled_date, scheduled_time),
                duration_minutes=int(duration),
            )
            db.session.add(lc)
            db.session.commit()
        st.success("Live class scheduled.")
        st.rerun()

    with flask_app.app_context():
        classes = LiveClass.query.filter_by(teacher_id=profile.id).order_by(LiveClass.scheduled_at.desc()).all()
    for c in classes:
        st.write(f"**{c.title}** — {c.scheduled_at or 'No time'}")
        if c.meeting_link:
            st.link_button("Open meeting", c.meeting_link)


def student_dashboard(user):
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).student_profile
        teacher_name = profile.teacher.user.full_name if profile.teacher else "Not assigned"
        assignments = Assignment.query.filter_by(
            teacher_id=profile.teacher_id
        ).count() if profile.teacher_id else 0
    section_title("Student dashboard", "Track your learning and stay on top of your work.")
    metric_cards([
        ("Level", CATEGORIES.get(profile.category, profile.category or ""), "Current category"),
        ("Teacher", teacher_name, "Assigned teacher"),
        ("Assignments", assignments, "Available to complete"),
    ])
    st.info(f"Account status: {profile.status}")


def student_assignments(user):
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).student_profile
        if not profile.teacher_id:
            st.warning("You have not been assigned to a teacher yet.")
            return
        assignments = Assignment.query.filter_by(
            teacher_id=profile.teacher_id
        ).order_by(Assignment.created_at.desc()).all()

    st.subheader("📝 Assignments")
    for assignment in assignments:
        questions = assignment.questions()
        with st.expander(f"{assignment.title} · {len(questions)} questions"):
            st.write(assignment.instructions or "")
            if not questions:
                st.info("This assignment has no interactive questions.")
                continue

            with st.form(f"assignment_{assignment.id}"):
                answers = {}
                for q in questions:
                    qid = q.get("id")
                    st.markdown(f"**{q.get('number', qid)}. {q.get('question','')}**")
                    opts = q.get("options") or []
                    if q.get("type") == "mcq" and opts:
                        answers[qid] = st.radio("Answer", opts, key=f"{assignment.id}_{qid}")
                    elif q.get("type") == "true_false":
                        answers[qid] = st.radio("Answer", ["True", "False"], key=f"{assignment.id}_{qid}")
                    else:
                        answers[qid] = st.text_input("Your answer", key=f"{assignment.id}_{qid}")
                submit = st.form_submit_button("Submit answers")
            if submit:
                with flask_app.app_context():
                    submission = Submission.query.filter_by(
                        assignment_id=assignment.id, student_id=profile.id
                    ).first()
                    if not submission:
                        submission = Submission(
                            assignment_id=assignment.id,
                            student_id=profile.id,
                        )
                        db.session.add(submission)
                    submission.answers_json = json.dumps(answers)
                    score, total, details = ai_service.mark_online_submission(assignment, answers)
                    submission.score = score
                    submission.max_score = total
                    submission.status = "marked"
                    submission.feedback = json.dumps(details)
                    submission.submitted_at = datetime.utcnow()
                    submission.marked_at = datetime.utcnow()
                    db.session.commit()
                st.success(f"Submitted and marked: {score}/{total}")
                st.rerun()


def student_results(user):
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).student_profile
        submissions = Submission.query.filter_by(student_id=profile.id).order_by(Submission.submitted_at.desc()).all()

    st.subheader("📊 Results")
    if not submissions:
        st.info("No submitted assignments yet.")
        return
    for s in submissions:
        title = s.assignment.title if s.assignment else f"Submission #{s.id}"
        st.write(f"**{title}** — {s.score:g}/{s.max_score:g}" if s.max_score is not None else f"**{title}**")
        if s.feedback:
            try:
                details = json.loads(s.feedback)
                for d in details:
                    icon = "✅" if d.get("is_correct") else "❌"
                    st.write(f"{icon} {d.get('question','')}")
            except Exception:
                st.write(s.feedback)


def student_live(user):
    with flask_app.app_context():
        profile = db.session.get(User, user["id"]).student_profile
        classes = LiveClass.query.filter(
            (LiveClass.category == profile.category) |
            (LiveClass.category.is_(None))
        ).order_by(LiveClass.scheduled_at.desc()).all()
    st.subheader("🎥 Live classes")
    for c in classes:
        st.write(f"**{c.title}** — {c.scheduled_at or 'Time not set'}")
        st.write(c.description or "")
        if c.meeting_link:
            st.link_button("Join class", c.meeting_link)


def main():
    init_app()

    if "user_id" not in st.session_state:
        render_login()
        return

    user = current_user()
    if not user:
        logout()
        return

    with st.sidebar:
        brand_sidebar()
        st.markdown(f"**{user['full_name']}**")
        st.markdown(f'<span class="pill">{user["role"].title()}</span>', unsafe_allow_html=True)
        st.write("")
        if st.button("Log out", use_container_width=True):
            logout()

        if user["role"] == "admin":
            page = st.radio("Navigate", ["Dashboard", "Manage users"])
        elif user["role"] == "teacher":
            page = st.radio(
                "Navigate",
                ["Dashboard", "AI Tutor", "AI Question Generator", "Create Assignment",
                 "Assignments", "Live Classes"],
            )
        else:
            page = st.radio(
                "Navigate",
                ["Dashboard", "AI Tutor", "Assignments", "Results", "Live Classes"],
            )

    header(user)

    if user["role"] == "admin":
        {"Dashboard": admin_dashboard, "Manage users": admin_manage_users}[page]()
    elif user["role"] == "teacher":
        actions = {
            "Dashboard": teacher_dashboard,
            "AI Tutor": lambda: tutor_chat(user),
            "AI Question Generator": lambda: teacher_generate(user),
            "Create Assignment": lambda: teacher_create_assignment(user),
            "Assignments": lambda: teacher_assignments(user),
            "Live Classes": lambda: teacher_live_classes(user),
        }
        actions[page](user) if page != "Dashboard" else actions[page](user)
    else:
        actions = {
            "Dashboard": student_dashboard,
            "AI Tutor": lambda: tutor_chat(user),
            "Assignments": lambda: student_assignments(user),
            "Results": lambda: student_results(user),
            "Live Classes": lambda: student_live(user),
        }
        actions[page](user) if page != "Dashboard" else actions[page](user)

    st.markdown(
        '<div style="text-align:center;padding:40px 0 12px;color:#91a0ad;font-size:12px;">'
        'TutorAI · Learn smarter. Teach better.</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
