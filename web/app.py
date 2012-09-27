from flask import Flask, request, redirect
from flask.ext.sqlalchemy import SQLAlchemy
import twilio.twiml

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///../test.db')

db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = "sms_users"

    id = db.Column(db.Integer, primary_key=True)
    nick = db.Column(db.String, unique=True)
    number = db.Column(db.Integer)
    enabled = db.Column(db.Boolean, default=True)
    last_sms_time = db.Column(db.DateTime)


@app.route("/reply", methods=["POST"])
def receive_sms():
    text = request.values.get('Body', None)
    user_number = request.values.get('From', None)

    user = User.query.filter_by(user_number=user_number).first()

    if user:
        user.enabled = False
        db.session.add(user)
        db.session.commit()

        return "Notifications have been disabled. Use .enablesms next time you're on IRC to re-enable them."