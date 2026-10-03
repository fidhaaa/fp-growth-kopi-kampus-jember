import os
from pathlib import Path
from flask import Flask
from flask_migrate import Migrate
from app.extensions import db

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app():
    app = Flask(__name__)

    # Keep secrets and deployment settings outside the source code.
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-only-change-me')
    app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024

    # Use DATABASE_URL in production (e.g. PostgreSQL). For local testing,
    # fall back to SQLite stored in the project's instance directory.
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        # Some providers still expose the legacy postgres:// scheme.
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
    else:
        instance_dir = BASE_DIR / 'instance'
        instance_dir.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{instance_dir / 'fp_growth_demo.db'}"

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Store uploaded files in a project-relative folder. This keeps the app
    # working locally and makes the location explicit for deployment.
    upload_folder = BASE_DIR / 'uploads'
    upload_folder.mkdir(parents=True, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = str(upload_folder)

    db.init_app(app)
    Migrate(app, db)

    from .routes import main
    app.register_blueprint(main)

    with app.app_context():
        db.create_all()

    return app
