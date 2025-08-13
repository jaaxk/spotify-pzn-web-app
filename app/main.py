# app/main.py
import os
import json
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from spotipy import oauth2
from spotipy.oauth2 import SpotifyOAuth
import uuid
from .db import SessionLocal, init_db
from .models import User, Track
from .tasks import update_user_library_task
import redis
import threading

app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# init DB (create tables) on startup (for local dev)
@app.on_event("startup")
def startup():
    init_db()

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8000/auth/callback")
SPOTIFY_SCOPES = os.environ.get("SPOTIFY_SCOPES", "user-library-read user-read-recently-played user-read-email")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse("app/static/index.html")

@app.get("/auth/login")
def spotify_login():
    sp_oauth = SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=SPOTIFY_REDIRECT_URI, scope=SPOTIFY_SCOPES)
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
def spotify_callback(request: Request, db: SessionLocal = Depends(get_db)):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    sp_oauth = SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=SPOTIFY_REDIRECT_URI, scope=SPOTIFY_SCOPES)
    token_info = sp_oauth.get_access_token(code)
    access_token = token_info.get("access_token")
    refresh_token = token_info.get("refresh_token")

    import spotipy
    sp = spotipy.Spotify(auth=access_token)
    me = sp.current_user()
    spotify_user_id = me.get("id")
    display_name = me.get("display_name")
    email = me.get("email")

    # upsert user in DB
    user = db.query(User).filter(User.spotify_user_id == spotify_user_id).first()
    if not user:
        user = User(spotify_user_id=spotify_user_id, display_name=display_name, email=email, refresh_token=refresh_token)
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.refresh_token = refresh_token
        db.add(user); db.commit()

    # create a simple session cookie (in production use secure session storage)
    response = RedirectResponse(url=f"/static/dashboard.html?user_id={user.id}&spotify_user_id={spotify_user_id}")
    return response

@app.post("/api/update_library")
def start_update_library(user_id: int, db = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # start background task
    task = update_user_library_task.delay(user.refresh_token, user.id)
    return {"task_id": task.id}

@app.get("/api/task_status/{task_id}")
def get_task_status(task_id: str):
    """
    Polling endpoint to check task status.
    Returns the latest progress message from Redis or task state from Celery.
    """
    from celery.result import AsyncResult
    
    # Check Celery task state first
    task_result = AsyncResult(task_id)
    
    # Get the latest progress message from Redis
    latest_message = None
    try:
        # Get the most recent message from Redis pub/sub channel
        channel = f"task-progress-{task_id}"
        # We'll store the latest message in Redis with a key
        latest_key = f"latest-progress-{task_id}"
        latest_message = r.get(latest_key)
        
        if latest_message:
            latest_message = json.loads(latest_message)
    except Exception as e:
        print(f"Error getting Redis message: {e}")
    
    # Determine overall status
    if task_result.state == 'PENDING':
        status = 'pending'
    elif task_result.state == 'STARTED':
        status = 'started'
    elif task_result.state == 'SUCCESS':
        status = 'finished'
        # Get the result data
        try:
            result_data = task_result.result
            if isinstance(result_data, dict):
                latest_message = result_data
        except Exception as e:
            print(f"Error getting task result: {e}")
    elif task_result.state == 'FAILURE':
        status = 'failed'
        latest_message = {'error': str(task_result.info)}
    else:
        status = task_result.state.lower()
    
    return {
        'task_id': task_id,
        'status': status,
        'celery_state': task_result.state,
        'progress': latest_message
    }

@app.get("/api/encoded_tracks/{user_id}")
def get_encoded_tracks(user_id: int, db = Depends(get_db)):
    # Get tracks that are encoded and belong to this user
    from .models import user_tracks
    tracks = db.query(Track).join(user_tracks).filter(
        user_tracks.c.user_id == user_id,
        Track.encoded == True
    ).all()
    return [{"id": t.id, "spotify_track_id": t.spotify_track_id, "name": t.name, "artist": t.artist} for t in tracks]

@app.get("/api/similar/{user_id}/{track_id}")
def get_similar(user_id: int, track_id: int, db = Depends(get_db)):
    # fetch the track, ensure embedding exists and belongs to this user
    from .models import user_tracks
    target = db.query(Track).join(user_tracks).filter(
        Track.id == track_id,
        user_tracks.c.user_id == user_id,
        Track.embedding != None
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Track not found or not encoded")
    
    # Use pgvector cosine distance operator '<=>' to find similar tracks for this user
    from sqlalchemy import text
    q = text("""
       SELECT t.id, t.spotify_track_id, t.name, t.artist, t.embedding <=> :vec AS distance
       FROM tracks t
       JOIN user_tracks ut ON t.id = ut.track_id
       WHERE t.embedding IS NOT NULL AND ut.user_id = :user_id AND t.id != :track_id
       ORDER BY t.embedding <=> :vec
       LIMIT 3
    """)
    # convert embedding to Postgres array string format
    vec = list(target.embedding)
    result = db.execute(q, {"vec": vec, "user_id": user_id, "track_id": track_id}).fetchall()
    out = []
    for row in result:
        out.append({"id": row[0], "spotify_track_id": row[1], "name": row[2], "artist": row[3], "distance": float(row[4])})
    # lower distance == more similar; convert to similarity as 1 - distance (approx)
    for x in out:
        x["similarity"] = 1.0 - x["distance"]
    return out
