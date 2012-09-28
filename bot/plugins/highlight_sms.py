from datetime import datetime, timedelta
import os
import phonenumbers
import redis
import threading

from util import hook

from sqlalchemy import Column, Integer, String, Boolean, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from twilio.rest import TwilioRestClient


### Initialize DB

try:
    database_uri = os.environ['DATABASE_URL']
except KeyError:
    database_uri = 'sqlite:///../test.db'

sms_db = create_engine(database_uri, echo=True)
Base = declarative_base()
Session = sessionmaker(bind=sms_db)


### Create User model

class User(Base):
    __tablename__ = "sms_users"

    id = Column(Integer, primary_key=True)
    nick = Column(String, unique=True)
    number = Column(String)
    enabled = Column(Boolean, default=True)

    last_sms_time = Column(DateTime)
    last_sms_sender = Column(String)
    last_sms_replied = Column(Boolean, default=True)

    def __init__(self, nick, number):
        self.nick = nick
        self.number = number

Base.metadata.create_all(sms_db)


### Load initial nicks (highlights)

session = Session()
highlight_nick_cache = []
for user in session.query(User).filter_by(enabled=True):
    highlight_nick_cache.append(user.nick)
session.close()

auth_queue = {}


### Redis pub/sub

def redis_cb(conn):
    r = redis.StrictRedis(host="localhost", port=6379, db=0)
    r = r.pubsub()
    r.subscribe("sms_replies")
    while True:
        for m in r.listen():
            print m
            if m['type'] == "message":
                from_nick, to_nick, reply_body = m['data'].split(" ", 2)

                conn.msg(to_nick, "SMS reply from %s: %s [Please do not attempt to reply to this message.]" % (from_nick, reply_body))

@hook.event('004')
def redis_onjoin(paraml, conn=None):
    t = threading.Thread(target=redis_cb, args=(conn,))
    t.setDaemon(True)
    t.start()


### Handle SMS highlights

def highlight_sms(nick, sender, message, channel, bot):
    # ghetto throttle: no more than 1 msg per 10 min

    account_sid = bot.config.get("twilio", {}).get("sid", None)
    account_auth_token = bot.config.get("twilio", {}).get("auth_token", None)
    twilio_number = bot.config.get("twilio", {}).get("twilio_number", None)
    throttle_time = int(bot.config.get("twilio", {}).get("throttle_time", "300"))

    if not account_sid or not account_auth_token or not twilio_number:
        print "** missing info in api keys"
        return

    session = Session()
    user = session.query(User).filter_by(nick=nick).first()
    session.close()

    # python owns
    now = datetime.now()
    #if True:
    if not user.last_sms_time or (now - user.last_sms_time) > timedelta(seconds=throttle_time):

        session = Session()
        user.last_sms_time = now
        user.last_sms_sender = sender
        user.last_sms_replied = False
        session.add(user)
        session.commit()

        if user.enabled == True:
            client = TwilioRestClient(account_sid, account_auth_token)
            to_num = "%s" % (user.number)
            from_num = "%s" % (twilio_number)
            body = "(%s) %s: %s" % (channel, sender, message)

            print "sending >>> %s" % (body)

            message = client.sms.messages.create(to=to_num, from_=from_num, body = body)
        else:
            # this occurs when the user has disabled via SMS - it doesn't remove it from the nick cache
            print "attempted to notify disabled user %s" % (nick)
            highlight_nick_cache.remove(nick)

    else:
        print "Throttle hit for user %s (highlighted by %s)" % (nick, sender)


@hook.singlethread
@hook.event("PRIVMSG", ignorebots=True)
def highlight_hook(paraml, input=None, db=None, bot=None):
    sender = input.nick
    message = input.msg
    channel = input.chan

    for nick in highlight_nick_cache:
        if nick.lower() in message.lower():
            highlight_sms(nick, sender, message, channel, bot)


### Register for SMS

@hook.singlethread
@hook.event("NOTICE", ignorebots=False)
def listen_for_auth(paraml, input=None, db=None, bot=None, conn=None):
    if input.nick == "NickServ":
        # returns "STATUS <nick> <num>" on SynIRC, "ACC <nick> <num>" elsewhere?
        nick = input.msg.split(" ")[1]
        status = input.msg.split(" ")[2]
        if int(status) == 3:
            #authed
            result = auth_queue[nick]["command"](nick, auth_queue[nick]["arg"])
            del auth_queue[nick]
            if result:
                conn.msg(nick, result)
        else:
            conn.msg(nick, "Register & login with this nick before using SMSBot.")


def convert_to_e164(raw_phone):
    if not raw_phone:
        return

    if raw_phone[0] == '+':
        # Phone number may already be in E.164 format.
        parse_type = None
    else:
        # If no country code information is present, assume it's a US number
        parse_type = "US"

    phone_representation = phonenumbers.parse(raw_phone, parse_type)
    return phonenumbers.format_number(phone_representation,
        phonenumbers.PhoneNumberFormat.E164)


@hook.command
def registersms(inp, nick='', chan='', db=None, input=None, conn=None):
    auth_queue[nick] = {"command": _registersms, "arg": inp}
    conn.msg("nickserv", "STATUS %s" % (nick))


def _registersms(nick, arg):
    number = convert_to_e164(arg)
    
    user = User(nick, number)

    try:
        session = Session()
        session.add(user)
        session.commit()
    except IntegrityError:
        return "You've already registered. To change your number, use 'changenumber'."

    highlight_nick_cache.append(nick)

    return "Added you to the SMS registry. Use 'disablesms' to disable."


@hook.command
def enablesms(inp, nick='', chan='', db=None, input=None, conn=None):
    auth_queue[nick] = {"command": _enablesms, "arg": inp}
    conn.msg("nickserv", "STATUS %s" % (nick))
    pass


def _enablesms(nick, arg):
    session = Session()
    user = session.query(User).filter_by(nick=nick).first()

    if not user:
        return "You are not registered."

    user.enabled = True
    session.add(user)
    session.commit()

    highlight_nick_cache.append(user.nick)

    return "Enabled SMS messaging on highlights. To disable, use .disablesms."


@hook.command
def disablesms(inp, nick='', chan='', db=None, input=None, conn=None):
    auth_queue[nick] = {"command": _disablesms, "arg": inp}
    conn.msg("nickserv", "STATUS %s" % (nick))
    pass


def _disablesms(nick, arg):
    session = Session()
    user = session.query(User).filter_by(nick=nick).first()

    if not user:
        return "You are not registered."

    user.enabled = False
    session.add(user)
    session.commit()

    highlight_nick_cache.remove(user.nick)

    return "Disabled SMS messaging on highlights. To re-enable, use .enablesms."


@hook.command
def changenumber(inp, nick='', chan='', db=None, input=None):
    pass