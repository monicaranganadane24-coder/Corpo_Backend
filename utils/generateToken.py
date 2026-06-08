import jwt
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")

def create_token(email: str):
    payload = {
        "email": email,
        "exp": datetime.utcnow() + timedelta(minutes=15)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["email"]
    except:
        return None
