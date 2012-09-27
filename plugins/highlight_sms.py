from datetime import datetime, timedelta

from util import hook

from sqlalchemy import Column, Integer, String, Boolean, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


### Initialize DB

sms_db = create_engine("sqlite:///test.db", echo=True)
Base = declarative_base()
Session = sessionmaker(bind=sms_db)


### Create User model

class User(Base):
    __tablename__ = "sms_users"

    id = Column(Integer, primary_key=True)
    nick = Column(String, unique=True)
    number = Column(Integer)
    enabled = Column(Boolean, default=True)
    last_sms_time = Column(DateTime)

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


### Handle SMS highlights

def highlight_sms(nick, sender, message):
    # ghetto throttle: no more than 1 msg per 10 min

    session = Session()
    user = session.query(User).filter_by(nick=nick).first()
    session.close()

    # python owns
    now = datetime.now()
    if not user.last_sms_time or (now - user.last_sms_time) > timedelta(minutes=10):

        session = Session()
        user.last_sms_time = now
        session.add(user)
        session.commit()

        if user.enabled == True:
            print "Fake sending text message to user %s - '%s: %s'" % (nick, sender, message)
    else:
        print "Throttle hit for user %s (highlighted by %s)" % (nick, sender)


@hook.singlethread
@hook.event("PRIVMSG", ignorebots=True)
def highlight_hook(paraml, input=None, db=None, bot=None):
    sender = input.nick
    message = input.msg

    for nick in highlight_nick_cache:
        if nick in message:
            highlight_sms(nick, sender, message)


### Register for SMS

@hook.singlethread
@hook.event("NOTICE", ignorebots=False)
def listen_for_auth(paraml, input=None, db=None, bot=None, conn=None):
    if input.nick == "NickServ":
        # returns "STATUS <nick> <num>"
        nick = input.msg.split(" ")[1]
        status = input.msg.split(" ")[2]
        if int(status) == 3:
            #authed
            result = auth_queue[nick]["command"](nick, auth_queue[nick]["arg"])
            del auth_queue[nick]
            if result:
                conn.msg(nick, result)
        else:
            conn.msg(nick, "Could not confirm NickServ auth.")


@hook.command
def registersms(inp, nick='', chan='', db=None, input=None, conn=None):
    auth_queue[nick] = {"command": _registersms, "arg": inp}
    conn.msg("nickserv", "STATUS %s" % (nick))


def _registersms(nick, arg):
    try:
        number = int(arg)
    except ValueError:
        return "Please give a valid phone number."
    
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

    return "Disabled SMS messaging on highlights. To re-enable, use .enablesms."


@hook.command
def changenumber(inp, nick='', chan='', db=None, input=None):
    pass