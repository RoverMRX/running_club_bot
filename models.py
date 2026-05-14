from datetime import datetime
from sqlalchemy import BigInteger, Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    xp = Column(Integer, default=0)
    is_admin = Column(Boolean, default=False)

class Challenge(Base):
    __tablename__ = 'challenges'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.tg_id'))
    type = Column(String) 
    goal_value = Column(Float)
    current_value = Column(Float, default=0.0)
    penalty = Column(String)
    is_active = Column(Boolean, default=True)
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)

class Vote(Base):
    __tablename__ = 'votes'
    id = Column(Integer, primary_key=True)
    report_message_id = Column(BigInteger) 
    voter_id = Column(BigInteger)
    
class Challenge(Base):
    __tablename__ = 'challenges'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.tg_id'))
    
    # Тип теперь может быть 'combined' (как у тебя сейчас)
    type = Column(String) 
    
    # Цели
    goal_value = Column(Float)   # Общий километраж (например, 9 км в неделю)
    min_per_run = Column(Float)  # Минимум за один раз (3 км)
    runs_per_week = Column(Integer) # Сколько раз нужно выйти (3 раза)
    
    # Текущий прогресс
    current_value = Column(Float, default=0.0)
    current_runs = Column(Integer, default=0) # Сколько раз уже сбегал
    
    penalty = Column(String)
    is_active = Column(Boolean, default=True)
    end_date = Column(DateTime)