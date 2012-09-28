from flask import Flask, request, redirect
from flask.ext.sqlalchemy import SQLAlchemy
import twilio.twiml
import redis

import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///../test.db')
db = SQLAlchemy(app)
r = redis.StrictRedis(host='localhost', port=6379, db=0)


class User(db.Model):
    __tablename__ = "sms_users"

    id = db.Column(db.Integer, primary_key=True)
    nick = db.Column(db.String, unique=True)
    number = db.Column(db.Integer)
    enabled = db.Column(db.Boolean, default=True)

    last_sms_time = db.Column(db.DateTime)
    last_sms_sender = db.Column(db.String)
    last_sms_replied = db.Column(db.Boolean, default=True)


@app.route("/reply", methods=["POST"])
def receive_sms():
    text = request.values.get('Body', None)
    user_number = request.values.get('From', None)

    user = User.query.filter_by(number=user_number).first()

    if user and text == "unsub":
        user.enabled = False
        db.session.add(user)
        db.session.commit()

        resp = "Notifications have been disabled, %s. Use .enablesms next time you're on IRC to re-enable them." % (user.nick)

    elif user:
        if user.last_sms_replied == False:
            r.publish("sms_replies", "%s %s %s" % (user.nick, user.last_sms_sender, text))
            resp = "Sent your reply to %s." % (user.last_sms_sender)

            user.last_sms_replied = True
            db.session.add(user)
            db.session.commit()
        else:
            resp = "You've already replied to your last message."

    else:
        resp = "[no action to take]"

    twiml_resp = twilio.twiml.Response()
    twiml_resp.sms(resp)

    return str(twiml_resp)
