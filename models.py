import json
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


def now():
    return datetime.utcnow()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # admin | teacher | student
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=now)

    teacher_profile = db.relationship("TeacherProfile", backref="user", uselist=False,
                                       cascade="all, delete-orphan")
    student_profile = db.relationship("StudentProfile", backref="user", uselist=False,
                                       cascade="all, delete-orphan")

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def initials(self):
        parts = self.full_name.strip().split()
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][0].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class TeacherProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    tier = db.Column(db.String(20), default="standard")  # standard | national | international
    subjects = db.Column(db.String(255))
    bio = db.Column(db.Text)
    categories = db.Column(db.String(255))  # comma list of category keys they can teach

    # Licensing
    license_status = db.Column(db.String(20), default="pending")  # pending | free_pending_admin | active | expired
    license_paid_at = db.Column(db.DateTime)
    license_expires_at = db.Column(db.DateTime)
    approved_by_admin = db.Column(db.Boolean, default=False)

    students = db.relationship("StudentProfile", backref="teacher", lazy="dynamic")

    @property
    def license_active(self):
        if self.license_status == "active" and self.license_expires_at:
            return self.license_expires_at > now()
        return False

    def student_count(self):
        return self.students.filter_by(status="active").count()


class StudentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    category = db.Column(db.String(30))  # pre_primary | primary | junior_school | senior_school
    tier = db.Column(db.String(20))  # standard | national | international
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher_profile.id"), nullable=True)
    status = db.Column(db.String(20), default="pending_payment")  # pending_payment | pending_teacher_assignment | active | inactive
    guardian_name = db.Column(db.String(120))
    guardian_phone = db.Column(db.String(30))

    def display_category(self):
        from flask import current_app
        return current_app.config["CATEGORIES"].get(self.category, self.category)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    purpose = db.Column(db.String(30))  # tuition | license
    amount = db.Column(db.Integer)
    method = db.Column(db.String(20), default="mpesa")
    phone = db.Column(db.String(30))
    reference = db.Column(db.String(60))
    status = db.Column(db.String(20), default="completed")  # completed | pending | failed
    created_at = db.Column(db.DateTime, default=now)

    user = db.relationship("User")


class LiveClass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher_profile.id"), nullable=False)
    title = db.Column(db.String(150))
    category = db.Column(db.String(30))
    description = db.Column(db.Text)
    meeting_link = db.Column(db.String(500))
    scheduled_at = db.Column(db.DateTime)
    duration_minutes = db.Column(db.Integer, default=60)
    created_at = db.Column(db.DateTime, default=now)

    teacher = db.relationship("TeacherProfile")


class Recording(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher_profile.id"), nullable=False)
    title = db.Column(db.String(150))
    category = db.Column(db.String(30))
    description = db.Column(db.Text)
    filename = db.Column(db.String(300))
    uploaded_at = db.Column(db.DateTime, default=now)

    teacher = db.relationship("TeacherProfile")


class LibraryBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher_profile.id"), nullable=True)
    title = db.Column(db.String(200))
    author = db.Column(db.String(150))
    category = db.Column(db.String(30))
    filename = db.Column(db.String(300))
    uploaded_at = db.Column(db.DateTime, default=now)

    teacher = db.relationship("TeacherProfile")


class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher_profile.id"), nullable=False)
    title = db.Column(db.String(200))
    category = db.Column(db.String(30))
    instructions = db.Column(db.Text)
    source_filename = db.Column(db.String(300))  # original uploaded pdf/image
    questions_json = db.Column(db.Text)  # AI-parsed interactive questions
    parse_status = db.Column(db.String(20), default="none")  # none | processing | done | failed
    due_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=now)

    teacher = db.relationship("TeacherProfile")
    submissions = db.relationship("Submission", backref="assignment", cascade="all, delete-orphan")

    def questions(self):
        if not self.questions_json:
            return []
        try:
            return json.loads(self.questions_json)
        except Exception:
            return []


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignment.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("student_profile.id"), nullable=False)
    answers_json = db.Column(db.Text)  # student's ticked/typed answers, keyed by question id
    upload_filename = db.Column(db.String(300))  # alternative: photo/pdf of handwritten answers
    status = db.Column(db.String(20), default="not_started")  # not_started | submitted | marked
    score = db.Column(db.Float, nullable=True)
    max_score = db.Column(db.Float, nullable=True)
    feedback = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, nullable=True)
    marked_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship("StudentProfile")

    def answers(self):
        if not self.answers_json:
            return {}
        try:
            return json.loads(self.answers_json)
        except Exception:
            return {}


class TutorMessage(db.Model):
    """AI Tutor chat history - used by both students and teachers."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    sender = db.Column(db.String(10))  # user | ai
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now)
