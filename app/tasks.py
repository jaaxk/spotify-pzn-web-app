# app/tasks.py
import os
import json
import subprocess
import uuid
from celery import shared_task, current_task
from sqlalchemy.orm import Session
from .db import SessionLocal
from .models import User, Track, user_tracks
from .utils import download_preview_to_temp, resample_to_24k
from .mert import MERTEmbedder
from .celery_app import celery_app
import redis
import time

REDIS_URL = os.environ.get("REDIS_URL")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# instantiate model once per worker process
EMBEDDER = None
def get_embedder():
    global EMBEDDER
    if EMBEDDER is None:
        EMBEDDER = MERTEmbedder()
    return EMBEDDER

def update_progress(task_id, message):
    """Helper function to publish progress and store latest message"""
    # Publish to Redis pub/sub for real-time updates (if WebSockets are still used)
    r.publish(f"task-progress-{task_id}", json.dumps(message))
    # Store latest message for polling endpoint
    r.set(f"latest-progress-{task_id}", json.dumps(message), ex=3600)  # Expire in 1 hour

@shared_task(bind=True)
def update_user_library_task(self, spotify_refresh_token, user_id):
    """
    1) Fetch user saved tracks via Spotipy (we'll use spotipy inside this task)
    2) Filter out tracks that are already encoded for this user (early exit if no new tracks)
    3) Write data/tracks.json for remaining tracks
    4) Call node/preview_finder.js as a subprocess (it reads data/tracks.json, writes data/preview_urls.json)
    5) For each track with a preview_url, download, resample, get embedding, save embedding in Postgres
    """
    from spotipy.oauth2 import SpotifyOAuth
    import spotipy

    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise RuntimeError("User not found")

        # 1. Fetch saved tracks (we'll page through them)
        sp_oauth = SpotifyOAuth(client_id=os.environ["SPOTIFY_CLIENT_ID"],
                                 client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
                                 redirect_uri=os.environ["SPOTIFY_REDIRECT_URI"])
        sp = spotipy.Spotify(auth_manager=sp_oauth)
        saved_tracks = []
        limit = 50
        offset = 0
        while True:
            res = sp.current_user_saved_tracks(limit=limit, offset=offset)
            items = res.get("items", [])
            if not items:
                break
            for it in items:
                track = it.get("track")
                if track is None:
                    continue
                spotify_track_id = track.get("id")
                name = track.get("name")
                artists = ", ".join([a.get("name") for a in track.get("artists", [])])
                saved_tracks.append({
                    "spotify_track_id": spotify_track_id,
                    "name": name,
                    "artist": artists
                })
            offset += len(items)
            if len(items) < limit:
                break

        # 2. Filter out tracks that are already encoded for this user
        # Get existing track IDs that are already linked to this user
        existing_user_tracks = db.query(Track.spotify_track_id).join(user_tracks).filter(
            user_tracks.c.user_id == user.id,
            Track.encoded == True
        ).all()
        existing_user_track_ids = {t[0] for t in existing_user_tracks}

        # Get all tracks that are already encoded globally
        existing_encoded_tracks = db.query(Track.spotify_track_id).filter(
            Track.encoded == True
        ).all()
        existing_encoded_ids = {t[0] for t in existing_encoded_tracks}

        # Find new tracks for this user (not already linked to user)
        new_tracks_for_user = [t for t in saved_tracks if t["spotify_track_id"] not in existing_user_track_ids]
        
        # Early exit if no new tracks for this user
        if not new_tracks_for_user:
            msg = {"status": "finished", "processed": 0, "total": 0, "message": "No new tracks for this user"}
            update_progress(self.request.id, msg)
            return {"status": "finished", "processed": 0, "total": 0, "message": "No new tracks for this user"}

        # Separate new tracks into: already encoded globally vs need processing
        tracks_to_link_only = []  # Already encoded, just need to link to user
        tracks_to_process = []    # Need full processing pipeline
        
        for track in new_tracks_for_user:
            if track["spotify_track_id"] in existing_encoded_ids:
                tracks_to_link_only.append(track)
            else:
                tracks_to_process.append(track)

        # Link pre-encoded tracks to user immediately
        for track_data in tracks_to_link_only:
            track = db.query(Track).filter(Track.spotify_track_id == track_data["spotify_track_id"]).first()
            if track and track not in user.tracks:
                user.tracks.append(track)
                db.commit()

        # Early exit if no tracks need processing
        if not tracks_to_process:
            msg = {"status": "finished", "processed": len(tracks_to_link_only), "total": len(new_tracks_for_user), "message": f"Linked {len(tracks_to_link_only)} pre-encoded tracks"}
            update_progress(self.request.id, msg)
            return {"status": "finished", "processed": len(tracks_to_link_only), "total": len(new_tracks_for_user), "message": f"Linked {len(tracks_to_link_only)} pre-encoded tracks"}

        # 3. save tracks.json for node script (only tracks that need processing)
        os.makedirs("data", exist_ok=True)
        tracks_json = []
        for t in tracks_to_process:
            tracks_json.append({"name": t["name"], "artist": t["artist"], "spotify_track_id": t["spotify_track_id"]})
        with open("data/tracks.json", "w", encoding="utf-8") as f:
            json.dump(tracks_json, f, indent=2)

        # 4. Run node preview finder script (subprocess)
        # It will read data/tracks.json and output data/preview_urls.json mapping "name - artist" -> preview_url
        node_cmd = ["node", "preview_finder.js"]
        env = os.environ.copy()
        proc = subprocess.run(node_cmd, capture_output=True, text=True, env=env, cwd="node")
        print(proc.stdout)
        if proc.returncode != 0:
            # log but proceed; preview script may fail on some tracks
            print("Node preview_finder error:", proc.stderr)

        preview_map = {}
        preview_file = "data/preview_urls.json"
        if os.path.exists(preview_file):
            with open(preview_file, "r", encoding="utf-8") as f:
                preview_map = json.load(f)

        # 5. For each track that needs processing, handle it
        total = len(tracks_to_process)
        processed = 0
        for idx, t in enumerate(tracks_to_process):
            key = f'{t["name"]} - {t["artist"]}'.strip()
            preview_url = preview_map.get(key)
            # publish progress
            msg = {"status": "processing", "index": idx+1, "total": total, "track": t, "preview_url_present": bool(preview_url)}
            update_progress(self.request.id, msg)

            # Check if track exists in database (shared across users)
            track = db.query(Track).filter(Track.spotify_track_id == t["spotify_track_id"]).first()
            
            if not preview_url:
                # Create track record if it doesn't exist, and link to user
                if not track:
                    track = Track(spotify_track_id=t["spotify_track_id"], name=t["name"], artist=t["artist"], preview_url=None)
                    db.add(track)
                    db.commit()
                    db.refresh(track)
                
                # Link track to user (if not already linked)
                if track not in user.tracks:
                    user.tracks.append(track)
                    db.commit()
                continue

            # Create track if it doesn't exist
            if not track:
                track = Track(spotify_track_id=t["spotify_track_id"], name=t["name"], artist=t["artist"], preview_url=preview_url)
                db.add(track)
                db.commit()
                db.refresh(track)

            # Link track to user (if not already linked)
            if track not in user.tracks:
                user.tracks.append(track)
                db.commit()

            # download, resample
            local_mp3 = None
            try:
                local_mp3 = download_preview_to_temp(preview_url)
                waveform, sr = resample_to_24k(local_mp3)
            except Exception as e:
                print("Failed to download or resample:", e)
                continue
            finally:
                # Clean up temporary file
                if local_mp3 and os.path.exists(local_mp3):
                    try:
                        os.unlink(local_mp3)
                    except Exception as e:
                        print(f"Failed to clean up temporary file {local_mp3}: {e}")

            # embed
            try:
                embedder = get_embedder()
                vec = embedder.embed_audio(waveform, sr)  # 1D numpy vector (normalized)
            except Exception as e:
                print("Embedding error:", e)
                continue

            
            # Update track with embedding
            track.embedding = list(map(float, vec.tolist()))
            track.encoded = True  # Mark track as encoded globally
            db.add(track)
            db.commit()

            processed += 1
            # publish progress with track data for real-time updates
            msg2 = {
                "status": "encoded", 
                "index": processed, 
                "total": total, 
                "track": {
                    "id": track.id,
                    "spotify_track_id": track.spotify_track_id,
                    "name": track.name,
                    "artist": track.artist
                }
            }
            update_progress(self.request.id, msg2)

        # final message
        final_msg = {"status": "finished", "processed": processed, "total": total}
        update_progress(self.request.id, final_msg)
        return {"status": "finished", "processed": processed, "total": total}
    finally:
        db.close()
