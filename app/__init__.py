import os
from pathlib import Path
from flask import Flask
from flask_migrate import Migrate
from app.extensions import db

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.getenv(
        'SECRET_KEY',
        'dev-only-change-me'
    )
    app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024

    # =========================================================
    # DATABASE
    # =========================================================
    database_url = os.getenv('DATABASE_URL')

    if database_url:
        # Support legacy postgres:// URLs
        if database_url.startswith('postgres://'):
            database_url = database_url.replace(
                'postgres://',
                'postgresql://',
                1
            )
    else:
        # Deplexo: persistent storage is /data
        # Local development: use the project's instance folder
        if os.path.exists('/data'):
            data_dir = Path('/data')
        else:
            data_dir = BASE_DIR / 'instance'

        data_dir.mkdir(parents=True, exist_ok=True)

        database_path = data_dir / 'fp_growth_demo.db'
        database_url = f"sqlite:///{database_path}"

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # =========================================================
    # UPLOAD FOLDER
    # =========================================================
    # Deplexo: /data is persistent.
    # Local development: use the project's uploads folder.
    if os.path.exists('/data'):
        upload_folder = Path('/data/uploads')
    else:
        upload_folder = BASE_DIR / 'uploads'

    upload_folder.mkdir(parents=True, exist_ok=True)

    app.config['UPLOAD_FOLDER'] = str(upload_folder)

    # =========================================================
    # INITIALIZE EXTENSIONS
    # =========================================================
    db.init_app(app)
    Migrate(app, db)

    from .routes import main
    app.register_blueprint(main)

    with app.app_context():
        db.create_all()

    return app
