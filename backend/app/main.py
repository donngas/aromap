"""Application entry point; domain routes will be registered here."""

from fastapi import FastAPI

app = FastAPI(title="Aromap API", version="0.1.0")
