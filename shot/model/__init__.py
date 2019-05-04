from loguru import logger
from sqla_wrapper import SQLAlchemy
from sqlalchemy import BigInteger, Column, Integer, String
from sqlalchemy.exc import SQLAlchemyError

from shot import conf
from .utils import db_session_scope

db = SQLAlchemy(conf.db_uri, scopefunc=db_session_scope)


class BaseModel(db.Model):
    __abstract__ = True

    @classmethod
    def get_by_id(cls, model_id):
        try:
            return db.query(cls).get(model_id)
        except SQLAlchemyError:
            logger.exception()
            raise


class Admin(BaseModel):
    admin_id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True)


class Channel(BaseModel):
    channel_id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True)
    cam = Column(String(length=64))


class PhotoChannel(BaseModel):
    channel_id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True)
    cam = Column(String(length=64))

# db.create_all()
# TODO automate db.create_all()
