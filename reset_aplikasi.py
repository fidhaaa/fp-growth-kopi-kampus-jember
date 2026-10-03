import os
import shutil
from app import app
from app.models import db, AnalysisHistory, SimulationHistory, User  

UPLOAD_FOLDER = 'uploads'  

with app.app_context():
    # Hapus semua data dari database
    deleted_histories = AnalysisHistory.query.delete()
    deleted_simulations = SimulationHistory.query.delete()
    deleted_users = User.query.delete()
    db.session.commit()
    print(f"✔ Berhasil menghapus {deleted_histories} riwayat analisis, "
          f"{deleted_simulations} riwayat simulasi, dan {deleted_users} user.")

    # Reset folder uploads
    if os.path.exists(UPLOAD_FOLDER):
        shutil.rmtree(UPLOAD_FOLDER)
        print("🗑 Folder uploads dihapus.")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    print("📁 Folder uploads dibuat ulang.")
