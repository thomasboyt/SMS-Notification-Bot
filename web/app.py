from flask import Flask, request, redirect
from flask.ext.sqlalchemy import SQLAlchemy
import twilio.twiml

import os

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

    user = User.query.filter_by(number=user_number).first()

    print user_number

    if user:
        user.enabled = False
        db.session.add(user)
        db.session.commit()

        return "Notifications have been disabled, %s. Use .enablesms next time you're on IRC to re-enable them." % (user.nick)
    else:
        return "No user registered with your number."

#app.run(debug=True)