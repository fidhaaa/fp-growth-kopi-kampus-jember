import os

from app import create_app
from app.extensions import db
from app import models

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    port = int(os.getenv('PORT', 5000))

    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )
