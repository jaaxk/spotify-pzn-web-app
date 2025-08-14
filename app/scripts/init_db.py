# app/scripts/init_db.py
from sqlalchemy import text
from app.db import init_db, engine

if __name__ == "__main__":
    # Ensure pgvector extension exists before creating tables
    try:
        with engine.connect() as conn:
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "vector";'))
            conn.commit()
            print("Ensured pgvector extension exists.")
    except Exception as e:
        print(f"Warning: could not create pgvector extension automatically: {e}")

    init_db()
    print("DB initialized.")
