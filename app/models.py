# app/models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base
from pgvector.sqlalchemy import Vector

Base = declarative_base()

# Junction table for many-to-many relationship between users and tracks
user_tracks = Table(
    'user_tracks',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('track_id', Integer, ForeignKey('tracks.id'), primary_key=True),
    Column('created_at', DateTime(timezone=True), server_default=func.now())
)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    spotify_user_id = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String)
    email = Column(String)
    refresh_token = Column(String)  # store for now
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Many-to-many relationship with tracks
    tracks = relationship("Track", secondary=user_tracks, back_populates="users")

class Track(Base):
    __tablename__ = "tracks"
    id = Column(Integer, primary_key=True, index=True)
    spotify_track_id = Column(String, unique=True, index=True, nullable=False)  # Made unique since tracks are shared
    name = Column(String)
    artist = Column(String)
    preview_url = Column(String, nullable=True)
    encoded = Column(Boolean, default=False)  # Track encoding status (global, not per user)
    # store 1024-d embeddings
    embedding = Column(Vector(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Many-to-many relationship with users
    users = relationship("User", secondary=user_tracks, back_populates="tracks")
