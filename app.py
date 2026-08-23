import os
from datetime import datetime
from flask import Flask
from config import Config
from extensions import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

    from Blueprints.auth import auth_bp
    from Blueprints.admin import admin_bp
    from Blueprints.teacher import teacher_bp
    from Blueprints.student import student_bp
    from Blueprints.files import files_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(files_bp)

    @app.context_processor
    def inject_globals():
        return {"current_year": datetime.utcnow().year, "app_name": "TutorAI"}

    @app.errorhandler(403)
    def forbidden(e):
        return "403 - You don't have access to this page.", 403

    @app.errorhandler(404)
    def not_found(e):
        return "404 - Page not found.", 404

    with app.app_context():
        db.create_all()
        _seed_admin(app)

    return app


def _seed_admin(app):
    from models import User
    email = app.config["ADMIN_EMAIL"]
    if User.query.filter_by(email=email).first():
        return
    admin = User(role="admin", full_name="System Admin", email=email, phone="")
    admin.set_password(app.config["ADMIN_PASSWORD"])
    db.session.add(admin)
    db.session.commit()
    print(f"[TutorAI] Seeded admin account -> {email} / {app.config['ADMIN_PASSWORD']}")


app = Flask(__name__)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
