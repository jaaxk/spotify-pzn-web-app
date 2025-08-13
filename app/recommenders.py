# app/recommenders.py
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import text
from .models import Track


def get_similar_tracks(db: Session, seed_track_id: int, limit: int = 10) -> List[Dict]:
    """
    Return top-N similar tracks across the entire tracks table using pgvector cosine distance.
    Requires that the seed track has a non-null embedding.
    """
    # Fetch seed embedding using ORM so we get a proper pgvector-backed value
    seed_track = db.query(Track).filter(Track.id == seed_track_id, Track.embedding != None).first()
    if seed_track is None:
        raise ValueError("No embedding found for the selected track")

    seed_vec = list(seed_track.embedding)
    # Build pgvector literal and cast explicitly to vector to avoid ARRAY[text] binding
    vec_str = "[" + ",".join(f"{float(x):.6f}" for x in seed_vec) + "]"

    # Order by cosine distance using pgvector operator <=>, filter encoded tracks only
    # Embed the vector literal directly to avoid driver/paramstyle casting issues
    sql = f"""
        SELECT t.id, t.spotify_track_id, t.name, t.artist,
               t.embedding <=> '{vec_str}'::vector AS distance
        FROM tracks t
        WHERE t.embedding IS NOT NULL AND t.encoded = TRUE AND t.id != :seed_id
        ORDER BY distance
        LIMIT :limit
    """
    rows = db.execute(
        text(sql),
        {"seed_id": seed_track_id, "limit": limit}
    ).fetchall()

    results: List[Dict] = []
    for row in rows:
        results.append({
            "id": row[0],
            "spotify_track_id": row[1],
            "name": row[2],
            "artist": row[3],
            "distance": float(row[4]),
        })
    return results


