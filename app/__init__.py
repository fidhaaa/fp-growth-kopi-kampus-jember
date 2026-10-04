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
        _ensure_demo_data(app)

    return app


def _ensure_demo_data(app):
    # Create a read-only demo account and synthetic portfolio dataset.
    from app.models import User, AnalysisHistory
    import json
    import shutil

    demo = User.query.filter_by(username='demo').first()
    if not demo:
        demo = User(username='demo', role='demo')
        demo.set_password('demo123')
        db.session.add(demo)
        db.session.commit()

    demo_history = AnalysisHistory.query.filter_by(
        user_id=demo.id, filename='demo_transaksi.csv'
    ).first()

    upload_folder = Path(app.config['UPLOAD_FOLDER'])
    upload_folder.mkdir(parents=True, exist_ok=True)
    target = upload_folder / 'demo_transaksi.csv'
    source = BASE_DIR / 'app' / 'data' / 'demo_transaksi.csv'

    if not target.exists() and source.exists():
        shutil.copyfile(source, target)

    if not demo_history and target.exists():
        rules = [
            {"antecedents": ["Es Teh (Normal)"], "consequents": ["Mie Instan Goreng + Telur"], "confidence": 0.8571428571, "lift": 1.3186813187},
            {"antecedents": ["Mie Instan Goreng + Telur"], "consequents": ["Es Teh (Normal)"], "confidence": 0.9230769231, "lift": 1.3186813187},
            {"antecedents": ["Es Teh (Normal)"], "consequents": ["Joshua (Normal)"], "confidence": 0.7142857143, "lift": 1.2987012987},
            {"antecedents": ["Joshua (Normal)"], "consequents": ["Es Teh (Normal)"], "confidence": 0.9090909091, "lift": 1.2987012987},
            {"antecedents": ["Mie Instan Goreng + Telur"], "consequents": ["Joshua (Normal)"], "confidence": 0.6923076923, "lift": 1.2587412587},
            {"antecedents": ["Joshua (Normal)"], "consequents": ["Mie Instan Goreng + Telur"], "confidence": 0.8181818182, "lift": 1.2587412587},
            {"antecedents": ["Es Teh (Normal)", "Mie Instan Goreng + Telur"], "consequents": ["Joshua (Normal)"], "confidence": 0.6666666667, "lift": 1.2121212121},
            {"antecedents": ["Es Teh (Normal)", "Joshua (Normal)"], "consequents": ["Mie Instan Goreng + Telur"], "confidence": 0.8, "lift": 1.2307692308},
            {"antecedents": ["Mie Instan Goreng + Telur", "Joshua (Normal)"], "consequents": ["Es Teh (Normal)"], "confidence": 0.8888888889, "lift": 1.2698412698}
        ]
        least_sold = [["Joshua (Normal)", 55], ["Mie Instan Goreng + Telur", 65], ["Es Teh (Normal)", 70]]
        demo_history = AnalysisHistory(
            user_id=demo.id,
            filename='demo_transaksi.csv',
            result=json.dumps(rules),
            least_sold=json.dumps(least_sold)
        )
        db.session.add(demo_history)
        db.session.commit()
