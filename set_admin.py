from app import create_app
from app.extensions import db
from app.models import User

app = create_app()

with app.app_context():
    user = User.query.filter_by(username='admin').first()

    if user:
        user.role = 'admin'
        db.session.commit()
        print("Role akun admin berhasil diubah menjadi admin.")
    else:
        print("User admin tidak ditemukan.")