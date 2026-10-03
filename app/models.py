from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

class User(db.Model):
    __tablename__ = 'user' # __tablename__ menentukan nama tabel di database
    id = db.Column(db.Integer, primary_key=True) # id kolom untuk menyimpan id unik untuk setiap user
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='staff', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
class SimulationHistory(db.Model):
    __tablename__ = 'simulation_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id')) # kolom untuk menyimpan id user
    selected_products = db.Column(db.Text)  # Produk yang dipilih user
    recommended_products = db.Column(db.Text)  # Hasil rekomendasi
    date_simulated = db.Column(db.DateTime, default=datetime.utcnow)

class AnalysisHistory(db.Model):
    __tablename__ = 'analysis_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(225), nullable=False) # kolom untuk menyimpan nama file yg terkait dg analisis
    date_uploaded = db.Column(db.DateTime, default=datetime.utcnow) # kolom untuk menyimpan waktu pembuatan riwayat analisis
    result = db.Column(db.Text, nullable=False) # kolom untuk menyimpan hasil analisis dalam format teks
    least_sold = db.Column(db.Text, nullable=True) # kolom untuk menyimpan hasil produk kurang laris

    user = db.relationship('User', backref='analysis_histories', lazy=True) #user relasi untuk menghubungkan 'AnalysisHistory' dengan 'user'

class UserActivityLog(db.Model):
    __tablename__ = 'user_activity_log'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    action = db.Column(db.String(20))  # login / register
    status = db.Column(db.String(50))  # berhasil / gagal + alasan
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
