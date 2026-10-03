from app.__init__ import create_app
from app.extensions import db
from app import models

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # bikin tabel di database
    app.run(debug=True)
