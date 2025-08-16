# Spotify Music Personalization

A full-stack application for personalized music analysis using Spotify's API and various customized audio encoder models (MERT, CLMR).

## Features

- Spotify OAuth integration
- Music library analysis with MERT embeddings
- Real-time processing with Celery workers
- PostgreSQL with pgvector for similarity search
- S3 storage for audio previews

## Setup

1. Fill in .env with your credentials (and path to AWS DB URL)
2. Run with Docker: `docker-compose up --build'

## Architecture

- **FastAPI**: REST API and WebSocket server
- **Celery**: Async task processing
- **PostgreSQL + pgvector**: Database with vector similarity (hosted in AWS)
- **Redis**: Celery broker and result backend
- **Node.js**: Preview URL extraction service
