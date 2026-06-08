from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

pymysql.install_as_MySQLdb()

# Création du moteur SQLAlchemy
engine = create_engine(DATABASE_URL)

# Session locale
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base pour les modèles
Base = declarative_base()

# 🔥 Fonction indispensable pour FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
