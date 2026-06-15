"""
╔═════════════════════════════════════════════════════════════════╗
║   SDP SHORTS WEB  —  Backend API  v1.0                         ║
║   Squeeky Door Productions  |  squeekydoorproductions.com       ║
╚═════════════════════════════════════════════════════════════════╝

FastAPI backend:  auth · jobs · tokens · Stripe · PayPal

ENV VARS needed (.env):
    SECRET_KEY          = any random 32-char string
    CLAUDE_API_KEY      = sk-ant-...
    STRIPE_SECRET_KEY   = sk_live_...  (or sk_test_...)
    STRIPE_WEBHOOK_SECRET = whsec_...
    STRIPE_PRICE_STARTER  = price_...h
    STRIPE_PRICE_PRO      = price_...
    STRIPE_PRICE_STUDIO   = price_...
    PAYPAL_CLIENT_ID    = ...
    PAYPAL_CLIENT_SECRET= ...
    PAYPAL_MODE         = sandbox  (or live)
    FRONTEND_URL        = https://your-netlify-site.netlify.app
"""

# ── bcrypt / passlib compatibility patch ──────────────────────────
try:
    import bcrypt as _bcrypt
    if not hasattr(_bcrypt, "__about__"):
        _bcrypt.__about__ = type("_", (), {"__version__": getattr(_bcrypt, "__version__", "3.2.2")})()
except Exception:
    pass

import os, uuid, json, re, shutil, asyncio, tempfile, math, subprocess, threading
from urllib.parse import urlparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

from fastapi import (FastAPI, Depends, HTTPException, BackgroundTasks,
                     Request, Header, Response, status, Form, UploadFile, File)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlalchemy import (create_engine, Column, String, Integer, Float,
                        Boolean, DateTime, Text, ForeignKey, func)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from jose import JWTError, jwt
from passlib.context import CryptContext
import stripe
import requests as http_req
from dotenv import load_dotenv
import smtplib
import secrets
import re
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

# ══════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════

SECRET_KEY = os.getenv("SECRET_KEY")

# -- social-token encryption at rest --------------------------------
# OAuth tokens (YouTube etc.) are encrypted before hitting the DB.
# Key is derived from SECRET_KEY, so no extra env var is needed.
import base64 as _b64, hashlib as _hashlib
from cryptography.fernet import Fernet as _Fernet

def _build_token_fernet():
    if not SECRET_KEY:
        return None
    digest = _hashlib.sha256(("social-token-enc:" + SECRET_KEY).encode()).digest()
    return _Fernet(_b64.urlsafe_b64encode(digest))

_TOKEN_FERNET = _build_token_fernet()

def enc_token(val):
    """Encrypt an OAuth token for storage. None/empty passes through."""
    if not val or _TOKEN_FERNET is None:
        return val
    return _TOKEN_FERNET.encrypt(val.encode()).decode()

def dec_token(val):
    """Decrypt a stored OAuth token. Falls back to plaintext for
    tokens saved before encryption was added (legacy rows)."""
    if not val or _TOKEN_FERNET is None:
        return val
    try:
        return _TOKEN_FERNET.decrypt(val.encode()).decode()
    except Exception:
        return val
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set — refusing to start. "
        "Set it in Railway → Variables before deploying."
    )
ALGORITHM       = "HS256"
TOKEN_EXP_HOURS = 24 * 2   # 2 days JWT

CLAUDE_API_KEY  = os.getenv("CLAUDE_API_KEY", "")
FRONTEND_URL    = os.getenv("FRONTEND_URL", "http://localhost:5173")

# ── Email config ──────────────────────────────────────────────────
EMAIL_FROM    = os.getenv("EMAIL_FROM", "squeekydoorphotos@gmail.com")
EMAIL_PASS    = os.getenv("EMAIL_APP_PASS", "")
EMAIL_ENABLED = bool(EMAIL_PASS)

stripe.api_key  = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK  = os.getenv("STRIPE_WEBHOOK_SECRET", "")

PAYPAL_CLIENT_ID     = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_MODE          = os.getenv("PAYPAL_MODE", "sandbox")
PAYPAL_BASE = ("https://api-m.sandbox.paypal.com" if PAYPAL_MODE == "sandbox"
               else "https://api-m.paypal.com")

YOUTUBE_CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REDIRECT_URI  = "https://backend-production-33b3.up.railway.app/social/youtube/callback"
YOUTUBE_SCOPES        = ["https://www.googleapis.com/auth/youtube.upload",
                          "https://www.googleapis.com/auth/youtube.readonly"]

TIKTOK_CLIENT_KEY     = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
TIKTOK_CLIENT_SECRET  = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
TIKTOK_REDIRECT_URI   = "https://backend-production-33b3.up.railway.app/auth/tiktok/callback"
TIKTOK_SCOPES         = "user.info.basic,video.upload,video.publish"

TOKENS_PER_CLIP = 0.5   # Each clip costs half a token

# ── Admin / owner accounts — bypass all token checks ──────────────
ADMIN_EMAILS = {
    "thelabsdp206@gmail.com",
    "squeekydoorphotos@gmail.com",
    "layzphotos@gmail.com",
    "ar.photo.sdp@gmail.com",
    "wimplobeats@gmail.com",
}

# Main admin — only this account can grant/revoke social-connect access for others
MAIN_ADMIN_EMAIL = "layzphotos@gmail.com"


JOBS_DIR  = Path(tempfile.gettempdir()) / "sdp_jobs"
FONTS_DIR = Path(__file__).parent / "fonts"
JOBS_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)

# Find ffmpeg/ffprobe — Railway/Nix puts them in non-standard paths
def _find_bin(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for p in [f"/nix/var/nix/profiles/default/bin/{name}",
              f"/usr/local/bin/{name}", f"/usr/bin/{name}", f"/bin/{name}"]:
        if Path(p).exists():
            return p
    try:
        r = subprocess.run(["which", name], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except:
        pass
    return name

FFMPEG_BIN  = _find_bin("ffmpeg")
FFPROBE_BIN = _find_bin("ffprobe")

# Subscription plans
PLANS = {
    # Slightly cheaper than Opus Clip ($19/$49/$99)
    "starter": {"usd": 12.99, "tokens": 100, "clips": 200,  "price_env": "STRIPE_PRICE_STARTER"},
    "pro":     {"usd": 29.99, "tokens": 360, "clips": 720,  "price_env": "STRIPE_PRICE_PRO"},
    "studio":  {"usd": 69.99, "tokens": 1000,"clips": 2000, "price_env": "STRIPE_PRICE_STUDIO"},
}

# Token top-up packs
TOPUPS = {
    "small":  {"usd": 4.99,  "tokens": 20,  "clips": 40},
    "medium": {"usd": 9.99,  "tokens": 50,  "clips": 100},
    "large":  {"usd": 24.99, "tokens": 140, "clips": 280},
}

# Fonts available for subtitle burning
FONTS_CONFIG = {
    "Arial":        {"family": "Arial",             "file": None},
    "Impact":       {"family": "Impact",             "file": None},
    "Montserrat":   {"family": "Montserrat-Bold",    "file": "Montserrat-Bold.ttf",
                     "url": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf"},
    "Bebas Neue":   {"family": "BebasNeue-Regular",  "file": "BebasNeue-Regular.ttf",
                     "url": "https://github.com/dharmatype/Bebas-Neue/raw/master/fonts/BebasNeue-Regular.ttf"},
    "Anton":        {"family": "Anton-Regular",      "file": "Anton-Regular.ttf",
                     "url": "https://fonts.gstatic.com/s/anton/v25/1Ptgg87LROyAm0K08i4gS7lu.ttf"},
    "Oswald":       {"family": "Oswald-Bold",        "file": "Oswald-Bold.ttf",
                     "url": "https://fonts.gstatic.com/s/oswald/v53/TK3_WkUHHAIjg75cFRf3bXL8LICs1_Fv.ttf"},
}

# ══════════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════════

DB_PATH = Path(os.getenv("DB_PATH", "/tmp/sdp_shorts.db"))
engine  = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email          = Column(String, unique=True, index=True, nullable=False)
    hashed_pw      = Column(String, nullable=False)
    tokens         = Column(Float,   default=5.0) # free signup bonus (0.5 per clip)
    plan           = Column(String, default="free")
    last_free_job_at = Column(DateTime, nullable=True)  # weekly free job tracking
    stripe_cust_id  = Column(String, nullable=True)
    stripe_sub_id   = Column(String, nullable=True)
    email_verified  = Column(Boolean, default=False)
    verify_token    = Column(String, nullable=True)
    reset_token     = Column(String, nullable=True)
    reset_token_exp = Column(DateTime, nullable=True)
    can_connect_socials = Column(Boolean, default=False)  # social-media account linking permission
    created_at      = Column(DateTime, default=datetime.utcnow)
    jobs            = relationship("Job", back_populates="user")


class Job(Base):
    __tablename__ = "jobs"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id     = Column(String, ForeignKey("users.id"), nullable=False)
    status      = Column(String, default="queued")   # queued/processing/done/failed
    source_url  = Column(String, nullable=True)
    settings    = Column(Text, default="{}")          # JSON blob
    clips_count    = Column(Integer, default=0)
    clips_metadata = Column(Text, default="[]")  # JSON array of clip info
    log            = Column(Text, default="")
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user        = relationship("User", back_populates="jobs")


class Transaction(Base):
    __tablename__ = "transactions"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String, ForeignKey("users.id"), nullable=False)
    kind       = Column(String)   # subscription/topup/refund
    provider   = Column(String)   # stripe/paypal
    amount_usd = Column(Float)
    tokens     = Column(Float)
    ref_id     = Column(String)   # Stripe/PayPal ID
    created_at = Column(DateTime, default=datetime.utcnow)


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id          = Column(String, ForeignKey("users.id"), nullable=False)
    platform         = Column(String, nullable=False)   # youtube / tiktok / instagram / facebook
    account_name     = Column(String, nullable=True)
    access_token     = Column(Text, nullable=True)
    refresh_token    = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    connected_at     = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)

# ── Lightweight auto-migration: add new columns to existing tables ─
# (Base.metadata.create_all only creates brand-new tables; it will NOT
#  add new columns to a table that already exists on disk. Without this,
#  the app crashes with "no such column: users.can_connect_socials".)
def _migrate_db():
    try:
        with engine.connect() as conn:
            cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()]
            if "can_connect_socials" not in cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN can_connect_socials BOOLEAN DEFAULT 0")
                conn.commit()
                print("[Migration] Added users.can_connect_socials column")
    except Exception as _mig_err:
        print(f"[Migration] Skipped/failed (non-fatal): {_mig_err}")

_migrate_db()



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ══════════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════════

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_password(pw: str):
    if len(pw) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not re.search(r"[A-Z]", pw):
        raise HTTPException(400, "Password needs at least one uppercase letter")
    if not re.search(r"[0-9]", pw):
        raise HTTPException(400, "Password needs at least one number")

def hash_pw(pw: str) -> str:        return pwd_ctx.hash(pw)
def verify_pw(pw: str, h: str) -> bool: return pwd_ctx.verify(pw, h)


def create_jwt(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(hours=TOKEN_EXP_HOURS)
    return jwt.encode({"sub": user_id, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request, authorization: str = Header(None),
                     db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("sdp_token")
    if not token:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Not authenticated")
        token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        uid = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ══════════════════════════════════════════════════════════════════
#  PAYPAL HELPERS
# ══════════════════════════════════════════════════════════════════

def _paypal_token() -> str:
    r = http_req.post(f"{PAYPAL_BASE}/v1/oauth2/token",
                      auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
                      data={"grant_type": "client_credentials"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def paypal_create_order(amount_usd: float, description: str) -> dict:
    token = _paypal_token()
    r = http_req.post(f"{PAYPAL_BASE}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"intent": "CAPTURE",
              "purchase_units": [{"amount": {"currency_code": "USD",
                                             "value": f"{amount_usd:.2f}"},
                                  "description": description}]},
        timeout=15)
    r.raise_for_status()
    return r.json()


def paypal_capture_order(order_id: str) -> dict:
    token = _paypal_token()
    r = http_req.post(f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15)
    r.raise_for_status()
    return r.json()

# ══════════════════════════════════════════════════════════════
#  URL VALIDATION  (SSRF protection)
# ══════════════════════════════════════════════════════════════

ALLOWED_VIDEO_DOMAINS = {
    "youtube.com", "youtu.be",
    "vimeo.com",
    "tiktok.com",
    "instagram.com",
    "twitter.com", "x.com",
    "twitch.tv",
    "facebook.com",
    "dailymotion.com",
    "reddit.com",
    "streamable.com",
}

def validate_video_url(url: str) -> str:
    """Block SSRF: only allow known public video platform domains."""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        raise HTTPException(400, "Invalid URL")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Only http/https URLs are allowed")
    host = parsed.netloc.lower().split(":")[0]  # strip port
    if not host:
        raise HTTPException(400, "Invalid URL \u2014 missing host")
    allowed = any(
        host == d or host.endswith("." + d)
        for d in ALLOWED_VIDEO_DOMAINS
    )
    if not allowed:
        raise HTTPException(
            400,
            "Unsupported video platform. Supported: YouTube, Vimeo, TikTok, "
            "Instagram, Twitter/X, Twitch, Facebook, Dailymotion, Reddit, Streamable."
        )
    return url.strip()


# ══════════════════════════════════════════════════════════════════
#  FONT DOWNLOADER
# ══════════════════════════════════════════════════════════════════

def ensure_font(font_name: str) -> Optional[str]:
    """Download font file if needed. Returns path or None for system fonts."""
    cfg = FONTS_CONFIG.get(font_name, FONTS_CONFIG["Arial"])
    if cfg["file"] is None:
        return None  # System font — ffmpeg will find it
    path = FONTS_DIR / cfg["file"]
    if not path.exists():
        try:
            r = http_req.get(cfg["url"], timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
        except Exception as e:
            print(f"Font download failed for {font_name}: {e}")
            return None
    return str(path)

# ══════════════════════════════════════════════════════════════════
#  EMAIL HELPERS
# ══════════════════════════════════════════════════════════════════

def send_email(to: str, subject: str, html: str):
    """Send email via Gmail SMTP."""
    if not EMAIL_ENABLED:
        print(f"[Email disabled] Would send to {to}: {subject}")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"SDP Shorts <{EMAIL_FROM}>"
        msg["To"]      = to
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as s:
            s.login(EMAIL_FROM, EMAIL_PASS)
            s.sendmail(EMAIL_FROM, to, msg.as_string())
        print(f"[Email] Sent to {to}: {subject}")
    except Exception as e:
        print(f"[Email] Failed: {e}")


def send_verification_email(email: str, token: str):
    url = f"{FRONTEND_URL}?verify={token}"
    send_email(email, "Verify your SDP Shorts account", f"""
    <div style="background:#000;color:#ccc;font-family:Georgia,serif;padding:40px;max-width:520px;margin:0 auto">
      <div style="color:#C9A443;font-size:22px;font-weight:700;margin-bottom:8px">SDP Shorts</div>
      <div style="color:#4a8c5c;font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:24px">Squeeky Door Productions</div>
      <h2 style="color:#C9A443;font-weight:400">Verify your account</h2>
      <p style="colo="color:#888;line-height:1.6">Thanks for signing up! Click below to verify your email and get your 5 free tokens.</p>
      <a href="{url}" style="display:inline-block;background:#4a8c5c;color:#000;text-decoration:none;padding:14px 32px;font-family:Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;border-radius:2px;margin:20px 0">
        Verify My Account
      </a>
      <p style="color:#555;font-size:12px;font-family:Arial,sans-serif">Link expires in 24 hours. If you didn't sign up, ignore this email.</p>
    </div>""")


def send_reset_email(email: str, token: str):
    url = f"{FRONTEND_URL}?reset={token}"
    send_email(email, "Reset your SDP Shorts password", f"""
    <div style="background:#000;color:#ccc;font-family:Georgia,serif;padding:40px;max-width:520px;margin:0 auto">
      <div style="color:#C9A443;font-size:22px;font-weight:700;margin-bottom:8px">SDP Shorts</div>
      <div style="color:#4a8c5c;font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:24px">Squeeky Door Productions</div>
      <h2 style="color:#C9A443;font-weight:400">Reset your password</h2>
      <p style="color:#888;line-height:1.6">We received a request to reset your password. Click below to choose a new one.</p>
      <a href="{url}" style="display:inline-block;background:#4a8c5c;color:#000;text-decoration:none;padding:14px 32px;font-family:Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;border-radius:2px;margin:20px 0">
        Reset My Password
      </a>
      <p style="color:#555;font-size:12px;font-family:Arial,sans-serif">Link expires in 1 hour. If you didn't request this, ignore this email.</p>
    </div>""")


def send_welcome_email(email: str):
    send_email(email, "Welcome to SDP Shorts!", f"""
    <div style="background:#000;color:#ccc;font-family:Georgia,serif;padding:40px;max-width:520px;margin:0 auto">
      <div style="color:#C9A443;font-size:22px;font-weight:700;margin-bottom:8px">SDP Shorts</div>
      <div style="color:#4a8c5c;font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:24px">Squeeky Door Productions</div>
      <h2 style="color:#C9A443;font-weight:400">You're in! 🎬</h2>
      <p style="color:#888;line-height:1.6">Your account is verified and your <strong style="color:#C9A443">5 free tokens</strong> are ready to use.</p>
      <p style="color:#888;line-height:1.6">Paste any video URL, let AI pick the viral moments, and download your clips — all within 48 hours before they auto-clear.</p>
      <a href="{FRONTEND_URL}" style="display:inline-block;background:#4a8c5c;color:#000;text-decoration:none;padding:14px 32px;font-family:Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;border-radius:2px;margin:20px 0">
        Start Making Shorts
      </a>
      <p style="color:#555;font-size:12px;font-family:Arial,sans-serif">0.5 tokens per clip · Clips available for 48 hours</p>
    </div>""")

def send_job_done_email(email: str, clips_count: int):
    send_email(email, "Your clips are ready!!🎬", f"""
    <div style="background:#000;color:#ccc;font-family:Georgia,serif;padding:40px;max-width:520px;margin:0 auto">
      <div style="color:#C9A443;font-size:22px;font-weight:700;margin-bottom:8px">SDP Shorts</div>
      <div style="color:#4a8c5c;font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:24px">Squeeky Door Productions</div>
      <h2 style="color:#C9A443;font-weight:400">All done! 🎉</h2>
      <p style="color:#888;line-height:1.6">We finished processing your video and made <strong style="color:#C9A443">{clips_count} clip(s)</strong> for you.</p>
      <p style="color:#888;line-height:1.6">Head back to your dashboard to preview and download them — clips are available for 48 hours.</p>
      <a href="{FRONTEND_URL}" style="display:inline-block;background:#4a8c5c;color:#000;text-decoration:none;padding:14px 32px;font-family:Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;border-radius:2px;margin:20px 0">
        View My Clips
      </a>
      <p style="color:#555;font-size:12px;font-family:Arial,sans-serif">Clips available for 48 hours before they auto-clear</p>
    </div>""")


def send_job_done_email(email: str, clips_count: int):
    send_email(email, "Your clips are ready! 🎬", f"""
    <div style="background:#000;color:#ccc;font-family:Georgia,serif;padding:40px;max-width:520px;margin:0 auto">
      <div style="color:#C9A443;font-size:22px;font-weight:700;margin-bottom:8px">SDP Shorts</div>
      <div style="color:#4a8c5c;font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:24px">Squeeky Door Productions</div>
      <h2 style="color:#C9A443;font-weight:400">All done! 🎉</h2>
      <p style="color:#888;line-height:1.6">We finished processing your video and made <strong style="color:#C9A443">{clips_count} clip(s)</strong> for you.</p>
      <p style="color:#888;line-height:1.6">Head back to your dashboard to preview and download them — clips are available for 48 hours.</p>
      <a href="{FRONTEND_URL}" style="display:inline-block;background:#4a8c5c;color:#000;text-decoration:none;padding:14px 32px;font-family:Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;border-radius:2px;margin:20px 0">
        View My Clips
      </a>
      <p style="color:#555;font-size:12px;font-family:Arial,sans-serif">Clips available for 48 hours before they auto-clear</p>
    </div>""")




# ══════════════════════════════════════════════════════════════════
#  APP
# ══════════════════════════════════════════════════════════════════

app = FastAPI(title="SDP Shorts Web API", version="1.0.0")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "https://spd-shorts-factory.netlify.app",
        "https://shorts.squeekydoorproductions.com",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options",  "nosniff")
        resp.headers.setdefault("X-Frame-Options",          "DENY")
        resp.headers.setdefault("Referrer-Policy",          "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy",       "camera=(), microphone=(), geolocation=()")
        return resp

app.add_middleware(_SecurityHeadersMiddleware)

# ══════════════════════════════════════════════════════════════════
#  PYDANTIC SCHEMAS
# ══════════════════════════════════════════════════════════════════

class RegisterIn(BaseModel):
    email: str
    password: str

class LoginIn(BaseModel):
    email: str
    password: str

class JobCreateIn(BaseModel):
    source_url: str
    clip_count: int = 10
    clip_length: int = 30       # seconds
    output_format: str = "both" # both / vertical / original
    ai_pick: bool = True
    subtitles: bool = True
    subtitle_font: str = "Arial"
    subtitle_size: int = 52
    subtitle_colour: str = "white"
    smart_reframe: bool = False
    face_blur: bool = False
    audio_norm: bool = True

    class Config:
        # Allow up to 500 clips for admin/paid users
        pass

class TopupIn(BaseModel):
    pack: str       # small / medium / large
    provider: str   # stripe / paypal

class PayPalCaptureIn(BaseModel):
    order_id: str
    pack: str

class SubscribeIn(BaseModel):
    plan: str   # starter / pro / studio

# ══════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════════

@app.post("/auth/register")
@limiter.limit("3/minute")
def register(request: Request, data: RegisterIn, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(func.lower(User.email) == data.email.lower().strip()).first():
        raise HTTPException(400, "Email already registered")
    validate_password(data.password)
    verify_tok = secrets.token_urlsafe(32)
    user = User(email=data.email.lower().strip(), hashed_pw=hash_pw(data.password),
                verify_token=verify_tok, email_verified=False)
    db.add(user); db.commit(); db.refresh(user)
    # Send verification email (non-blocking)
    try: send_verification_email(data.email, verify_tok)
    except: pass
    tok = create_jwt(user.id)
    response.set_cookie("sdp_token", tok, httponly=True, secure=True, samesite="lax", max_age=2*24*3600)
    return {"token": tok, "tokens": user.tokens, "plan": user.plan,
            "email": user.email, "is_admin": user.email in ADMIN_EMAILS,
            "email_verified": user.email_verified, "can_connect_socials": user.can_connect_socials}


@app.post("/auth/login")
@limiter.limit("5/minute")
def login(request: Request, data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == data.email.lower().strip()).first()
    if not user or not verify_pw(data.password, user.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    tok = create_jwt(user.id)
    response.set_cookie("sdp_token", tok, httponly=True, secure=True, samesite="lax", max_age=2*24*3600)
    return {"token": tok, "tokens": user.tokens, "plan": user.plan,
            "email": user.email, "is_admin": user.email in ADMIN_EMAILS,
            "email_verified": user.email_verified, "can_connect_socials": user.can_connect_socials}


@app.get("/auth/me")
def me(response: Response, user: User = Depends(get_current_user)):
    from datetime import timezone
    next_free = None
    if user.plan == "free" and user.last_free_job_at:
        since = (datetime.utcnow() - user.last_free_job_at).total_seconds()
        if since < 7 * 24 * 3600:
            nf = user.last_free_job_at + timedelta(days=7)
            next_free = nf.isoformat()
    tok = create_jwt(user.id)
    response.set_cookie("sdp_token", tok, httponly=True, secure=True, samesite="lax", max_age=2*24*3600)
    return {"id": user.id, "email": user.email, "tokens": user.tokens,
            "plan": user.plan, "created_at": user.created_at,
            "next_free_job_at": next_free,
            "tokens_per_clip": TOKENS_PER_CLIP,
            "is_admin": user.email in ADMIN_EMAILS,
            "token": tok,
            "email_verified": user.email_verified, "can_connect_socials": user.can_connect_socials}

@app.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("sdp_token")
    return {"ok": True}

# ── Admin: manage social-connect access (main admin only) ────────
def _require_main_admin(user: User = Depends(get_current_user)):
    if user.email != MAIN_ADMIN_EMAIL:
        raise HTTPException(403, "Only the main admin can manage access")
    return user


@app.get("/admin/users")
def admin_list_users(admin: User = Depends(_require_main_admin),
                      db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [{"id": u.id, "email": u.email, "plan": u.plan,
             "is_admin": u.email in ADMIN_EMAILS,
             "can_connect_socials": u.can_connect_socials,
             "created_at": u.created_at} for u in users]


class SocialAccessIn(BaseModel):
    enabled: bool


@app.post("/admin/users/{user_id}/social-access")
def admin_set_social_access(user_id: str, data: SocialAccessIn,
                            admin: User = Depends(_require_main_admin),
                            db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "User not found")
    target.can_connect_socials = data.enabled
    db.commit()
    return {"ok": True, "email": target.email, "can_connect_socials": target.can_connect_socials}


# ── Admin: refund support (main admin only) ──────────────────────
@app.get("/admin/refund-check/{email}")
def admin_refund_check(email: str,
                       admin: User = Depends(_require_main_admin),
                       db: Session = Depends(get_db)):
    """Everything needed to decide a refund request per the 14-day policy."""
    target = db.query(User).filter(func.lower(User.email) == email.lower().strip()).first()
    if not target:
        raise HTTPException(404, "No account with that email")
    txs = db.query(Transaction).filter(Transaction.user_id == target.id)\
            .order_by(Transaction.created_at.desc()).all()
    jobs = db.query(Job).filter(Job.user_id == target.id).all()
    now = datetime.utcnow()
    purchases = []
    for t in txs:
        days = (now - t.created_at).days if t.created_at else None
        used_since = sum((j.clips_count or 0) for j in jobs
                         if j.created_at and t.created_at and j.created_at >= t.created_at) * TOKENS_PER_CLIP
        if t.kind == "refund":
            hint = "ALREADY A REFUND RECORD"
        elif days is not None and days <= 14 and used_since == 0:
            hint = "FULL REFUND OK (within 14 days, no tokens used since)"
        elif days is not None and days <= 14:
            hint = f"PARTIAL AT DISCRETION ({used_since} tokens used since purchase)"
        else:
            hint = "OUTSIDE 14-DAY WINDOW (refund not required by policy)"
        purchases.append({"date": t.created_at, "days_ago": days, "kind": t.kind,
                          "provider": t.provider, "amount_usd": t.amount_usd,
                          "tokens": t.tokens, "ref_id": t.ref_id,
                          "tokens_used_since": used_since, "policy_hint": hint})
    return {"email": target.email, "plan": target.plan,
            "token_balance": target.tokens,
            "account_created": target.created_at,
            "total_jobs": len(jobs),
            "total_clips": sum((j.clips_count or 0) for j in jobs),
            "purchases": purchases}


class RefundLogIn(BaseModel):
    email: str
    amount_usd: float
    tokens_removed: float = 0
    provider: str = "stripe"
    ref_id: str = ""
    note: str = ""


@app.post("/admin/refunds")
def admin_log_refund(data: RefundLogIn,
                     admin: User = Depends(_require_main_admin),
                     db: Session = Depends(get_db)):
    """Log a refund AFTER processing it in the Stripe/PayPal dashboard.
    Removes the refunded tokens from the account and records the transaction."""
    target = db.query(User).filter(func.lower(User.email) == data.email.lower().strip()).first()
    if not target:
        raise HTTPException(404, "No account with that email")
    target.tokens = max(0.0, (target.tokens or 0.0) - abs(data.tokens_removed or 0.0))
    ref = (data.ref_id + (" | " + data.note if data.note else ""))[:250]
    tx = Transaction(user_id=target.id, kind="refund", provider=data.provider,
                     amount_usd=-abs(data.amount_usd), tokens=-abs(data.tokens_removed or 0.0),
                     ref_id=ref)
    db.add(tx)
    db.commit()
    return {"ok": True, "email": target.email, "new_token_balance": target.tokens,
            "refund_recorded_usd": -abs(data.amount_usd)}



# ── Email verify route ────────────────────────────────────────────
@app.get("/auth/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verify_token == token).first()
    if not user:
        raise HTTPException(400, "Invalid or expired verification link")
    user.email_verified = True
    user.verify_token = None
    db.commit()
    send_welcome_email(user.email)
    return {"ok": True, "email": user.email}


class ForgotIn(BaseModel):
    email: str

class ResetIn(BaseModel):
    token: str
    password: str

@app.post("/auth/forgot")
@limiter.limit("3/minute")
def forgot_password(request: Request, data: ForgotIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == data.email.lower().strip()).first()
    if user:
        tok = secrets.token_urlsafe(32)
        user.reset_token     = tok
        user.reset_token_exp = datetime.utcnow() + timedelta(hours=1)
        db.commit()
        try: send_reset_email(data.email, tok)
        except: pass
    # Always return ok so we don't reveal if email exists
    return {"ok": True}


@app.post("/auth/reset")
def reset_password(data: ResetIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == data.token).first()
    if not user or not user.reset_token_exp:
        raise HTTPException(400, "Invalid or expired reset link")
    if datetime.utcnow() > user.reset_token_exp:
        raise HTTPException(400, "Reset link has expired — request a new one")
    validate_password(data.password)
    user.hashed_pw      = hash_pw(data.password)
    user.reset_token    = None
    user.reset_token_exp = None
    db.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════
#  JOB ROUTES
# ══════════════════════════════════════════════════════════════════

@app.post("/jobs")
def create_job(data: JobCreateIn,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    # SSRF protection: validate URL is a known public video platform
    validate_video_url(data.source_url)

    cost = round(data.clip_count * TOKENS_PER_CLIP, 1)
    admin = user.email in ADMIN_EMAILS

    if not admin and not user.email_verified:
        raise HTTPException(403, "Please verify your email address before creating jobs. Check your inbox.")

    if not admin:
        # Free plan: max 3 clips, 1 job per week
        if user.plan == "free":
            if data.clip_count > 3:
                raise HTTPException(402, "Free plan: max 3 clips per job. Upgrade for more.")
            if user.last_free_job_at:
                from datetime import timezone
                since = (datetime.utcnow() - user.last_free_job_at).total_seconds()
                if since < 7 * 24 * 3600:
                    next_at = user.last_free_job_at + timedelta(days=7)
                    raise HTTPException(402,
                        f"Free plan: 1 video per week. Next available: {next_at.strftime('%b %d at %I:%M %p')} UTC")

        if user.tokens < cost:
            raise HTTPException(402,
                f"Not enough tokens. This job costs {cost} tokens, you have {user.tokens:.1f}.")

        # Deduct tokens immediately
        user.tokens -= cost
        if user.plan == "free":
            user.last_free_job_at = datetime.utcnow()
        db.commit()

    job = Job(user_id=user.id, source_url=data.source_url,
              settings=json.dumps(data.dict()), clips_count=0)
    db.add(job); db.commit(); db.refresh(job)

    # Use thread for reliable background processing
    t = threading.Thread(target=process_job, args=(job.id, data.dict()), daemon=True)
    t.start()
    return {"job_id": job.id, "tokens_remaining": user.tokens}


@app.get("/jobs")
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = (db.query(Job).filter(Job.user_id == user.id)
            .order_by(Job.created_at.desc()).limit(20).all())
    return [_job_dict(j) for j in jobs]


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job: raise HTTPException(404, "Job not found")
    return _job_dict(job)


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: str,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Re-queue a stuck or failed job without charging tokens again."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    # Set to processing immediately so UI updates right away
    job.status     = "processing"
    job.log        = (job.log or "") + "\n🔄 Retried — starting now\n"
    job.updated_at = datetime.utcnow()
    db.commit()
    settings = json.loads(job.settings or "{}")
    # Use a real thread — more reliable than BackgroundTasks for long-running work
    t = threading.Thread(target=process_job, args=(job.id, settings), daemon=True)
    t.start()
    return {"ok": True, "job_id": job.id}


@app.get("/jobs/{job_id}/clips")
def list_clips(job_id: str, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job: raise HTTPException(404, "Job not found")
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        return []
    files = sorted(p.name for p in job_dir.glob("*.mp4"))
    return [{"filename": f, "url": f"/jobs/{job_id}/download/{f}"} for f in files]


@app.get("/jobs/{job_id}/download/{filename}")
def download_clip(job_id: str, filename: str,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job: raise HTTPException(404)
    path = JOBS_DIR / job_id / filename
    # Prevent path traversal: ensure resolved path stays within job dir
    try:
        base = (JOBS_DIR / job_id).resolve()
        resolved = path.resolve()
        if not str(resolved).startswith(str(base) + os.sep) and resolved != base:
            raise HTTPException(403, "Invalid filename")
    except HTTPException: raise
    except Exception: raise HTTPException(400, "Invalid request")
    if not path.exists(): raise HTTPException(404, "File not found")
    return FileResponse(str(path), media_type="video/mp4",
                        filename=filename)


def _job_dict(j: Job) -> dict:
    job_dir = JOBS_DIR / j.id
    clips = []
    if job_dir.exists():
        clips = [{"filename": p.name, "url": f"/jobs/{j.id}/download/{p.name}"}
                 for p in sorted(job_dir.glob("*.mp4"))]
    # Parse clip metadata (virality scores, hooks, etc.)
    try:
        clips_meta = json.loads(j.clips_metadata or "[]")
    except:
        clips_meta = []
    # Merge metadata with file list
    for clip in clips:
        stem = clip["filename"].replace(".mp4", "")
        meta = next((m for m in clips_meta if m.get("filename","") == clip["filename"]), {})
        clip.update(meta)
    # Calculate expiry (48h from updated_at)
    expires_at = None
    if j.updated_at and j.status == "done":
        expires_at = (j.updated_at + timedelta(hours=48)).isoformat()
    return {"id": j.id, "status": j.status, "clips_count": j.clips_count,
            "clips_metadata": clips_meta, "settings": j.settings,
            "log": j.log, "clips": clips, "expires_at": expires_at,
            "created_at": j.created_at, "updated_at": j.updated_at}

# ══════════════════════════════════════════════════════════════════
#  PAYMENT ROUTES
# ══════════════════════════════════════════════════════════════════

@app.get("/plans")
def get_plans():
    return {"plans": PLANS, "topups": TOPUPS, "fonts": list(FONTS_CONFIG.keys()), "tokens_per_clip": TOKENS_PER_CLIP}


@app.post("/payments/stripe/subscribe")
def stripe_subscribe(data: SubscribeIn, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    if data.plan not in PLANS:
        raise HTTPException(400, "Unknown plan")
    plan_cfg  = PLANS[data.plan]
    price_id  = os.getenv(plan_cfg["price_env"], "")
    if not price_id:
        raise HTTPException(500, f"Stripe price ID not configured for {data.plan}")

    # Create or reuse Stripe customer
    if not user.stripe_cust_id:
        cust = stripe.Customer.create(email=user.email,
                                       metadata={"user_id": user.id})
        user.stripe_cust_id = cust.id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=user.stripe_cust_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{FRONTEND_URL}/dashboard?sub=success",
        cancel_url=f"{FRONTEND_URL}/pricing",
        metadata={"user_id": user.id, "plan": data.plan},
    )
    return {"checkout_url": session.url}


@app.post("/payments/stripe/topup")
def stripe_topup(data: TopupIn, user: User = Depends(get_current_user)):
    if data.pack not in TOPUPS:
        raise HTTPException(400, "Unknown pack")
    pack    = TOPUPS[data.pack]
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price_data": {
            "currency": "usd",
            "unit_amount": int(pack["usd"] * 100),
            "product_data": {"name": f"SDP Shorts — {pack['tokens']} tokens"},
        }, "quantity": 1}],
        success_url=f"{FRONTEND_URL}/dashboard?topup=success",
        cancel_url=f"{FRONTEND_URL}/dashboard",
        metadata={"user_id": user.id, "tokens": pack["tokens"], "kind": "topup"},
    )
    return {"checkout_url": session.url}


@app.post("/payments/paypal/create")
def paypal_create(data: TopupIn, user: User = Depends(get_current_user)):
    if data.pack not in TOPUPS:
        raise HTTPException(400, "Unknown pack")
    pack  = TOPUPS[data.pack]
    order = paypal_create_order(pack["usd"], f"SDP Shorts {pack['tokens']} tokens")
    return {"order_id": order["id"], "tokens": pack["tokens"]}


@app.post("/payments/paypal/capture")
def paypal_capture(data: PayPalCaptureIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    if data.pack not in TOPUPS:
        raise HTTPException(400, "Unknown pack")
    pack = TOPUPS[data.pack]
    try:
        result = paypal_capture_order(data.order_id)
    except Exception as e:
        raise HTTPException(400, f"PayPal capture failed: {e}")

    if result.get("status") != "COMPLETED":
        raise HTTPException(400, "Payment not completed")

    user.tokens += pack["tokens"]
    txn = Transaction(user_id=user.id, kind="topup", provider="paypal",
                      amount_usd=pack["usd"], tokens=pack["tokens"],
                      ref_id=data.order_id)
    db.add(txn); db.commit()
    return {"tokens": user.tokens, "added": pack["tokens"]}


# Stripe webhook — handles subscription renewals + one-time payments
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig     = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK)
    except Exception:
        raise HTTPException(400, "Invalid webhook")

    etype = event["type"]
    obj   = event["data"]["object"]

    if etype == "checkout.session.completed":
        meta    = obj.get("metadata", {})
        uid     = meta.get("user_id")
        kind    = meta.get("kind", "subscription")
        tokens  = int(meta.get("tokens", 0))
        plan    = meta.get("plan", "")
        user    = db.query(User).filter(User.id == uid).first() if uid else None
        if user:
            if kind == "topup" and tokens:
                user.tokens += tokens
                txn = Transaction(user_id=uid, kind="topup", provider="stripe",
                                  amount_usd=obj.get("amount_total", 0)/100,
                                  tokens=tokens, ref_id=obj["id"])
                db.add(txn)
            elif plan:
                plan_tokens = PLANS.get(plan, {}).get("tokens", 0)
                user.tokens += plan_tokens
                user.plan    = plan
                user.stripe_sub_id = obj.get("subscription")
                txn = Transaction(user_id=uid, kind="subscription", provider="stripe",
                                  amount_usd=PLANS.get(plan,{}).get("usd",0),
                                  tokens=plan_tokens, ref_id=obj["id"])
                db.add(txn)
            db.commit()

    elif etype == "invoice.payment_succeeded":
        sub_id = obj.get("subscription")
        if sub_id:
            user = db.query(User).filter(User.stripe_sub_id == sub_id).first()
            if user and user.plan in PLANS:
                # Monthly renewal — add tokens
                tokens = PLANS[user.plan]["tokens"]
                user.tokens += tokens
                txn = Transaction(user_id=user.id, kind="subscription",
                                  provider="stripe",
                                  amount_usd=PLANS[user.plan]["usd"],
                                  tokens=tokens, ref_id=obj["id"])
                db.add(txn); db.commit()

    elif etype in ("customer.subscription.deleted", "customer.subscription.paused"):
        sub_id = obj.get("id")
        user   = db.query(User).filter(User.stripe_sub_id == sub_id).first()
        if user:
            user.plan = "free"; db.commit()

    return {"ok": True}

# ══════════════════════════════════════════════════════════════════
#  JOB PROCESSOR  (runs in background)
# ══════════════════════════════════════════════════════════════════

def _db_session() -> Session:
    return SessionLocal()


def _log_job(job_id: str, msg: str):
    """Append a line to job log in DB."""
    db = _db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.log = (job.log or "") + msg + "\n"
            job.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _set_job_status(job_id: str, status: str, clips_count: int = None):
    db = _db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            if clips_count is not None:
                job.clips_count = clips_count
            job.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _save_clip_metadata(job_id: str, meta_list: list):
    """Save clip metadata (scores, hooks, tags) to the job record."""
    db = _db_session()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.clips_metadata = json.dumps(meta_list)
            db.commit()
    finally:
        db.close()


def process_job(job_id: str, settings: dict):
    """
    Full processing pipeline — runs in FastAPI BackgroundTasks thread.
    Downloads video → picks clips → cuts them → applies features → saves to JOBS_DIR/job_id/
    """
    log = lambda m: _log_job(job_id, m)
    out_dir = JOBS_DIR / job_id
    out_dir.mkdir(exist_ok=True)
    tmp_dir = out_dir / "_tmp"
    tmp_dir.mkdir(exist_ok=True)

    _set_job_status(job_id, "processing")
    log("🚀 Job started")

    try:
        # Import processor functions (inside try so failures are caught)
        from processor import (download_video, pick_clips_claude, pick_clips_evenly,
                                build_ass_content, extract_clip,
                                smart_reframe, blur_faces_opencv)
        # 1. Download video
        log(f"⬇️  Downloading: {settings['source_url']}")
        video_path = download_video(settings["source_url"], str(tmp_dir), log)
        log(f"✅ Downloaded: {Path(video_path).name}")

        # 2. Get duration
        dur = _ffprobe_duration(video_path)
        if dur <= 0:
            # Last resort: use file size to estimate (rough: ~1MB per 10s for 720p)
            fsize = Path(video_path).stat().st_size
            dur = max(30.0, fsize / 150000)
            log(f"📹 Duration estimated: {dur:.1f}s (ffprobe couldn't read metadata)")
        else:
            log(f"📹 Duration: {dur:.1f}s ({dur/60:.1f} min)")

        # 3. Transcribe if needed (whisper optional)
        segments = []
        if settings.get("ai_pick") or settings.get("subtitles"):
            log("😙️  Attempting transcription…")
            try:
                import whisper, threading as _th, subprocess as _sp
                log("   Loading Whisper tiny model…")
                model = whisper.load_model("tiny")

                tx_total = dur  # no cap — transcribe the full video

                # Break the audio into ~2-min chunks. This lets us:
                #   1) handle videos of any length (no more 10-min wall),
                #   2) keep each individual transcribe() call small & fast,
                #   3) log real progress after every chunk completes.
                CHUNK_LEN = 120
                chunk_starts = list(range(0, max(int(tx_total), 1), CHUNK_LEN)) or [0]
                total_chunks = len(chunk_starts)
                log(f"   Splitting into {total_chunks} chunk(s) for transcription…")

                all_segments = []
                for idx, start in enumerate(chunk_starts, start=1):
                    length = min(CHUNK_LEN, tx_total - start) or CHUNK_LEN
                    chunk_path = str(Path(tmp_dir) / f"tx_chunk_{idx}.mp4")
                    _sp.run([FFMPEG_BIN, "-y", "-ss", str(start), "-i", video_path,
                             "-t", str(length), "-c", "copy", chunk_path],
                            capture_output=True, timeout=60)
                    if not Path(chunk_path).exists():
                        log(f"   ⚠️  Couldn't extract chunk {idx}/{total_chunks} — skipping")
                        continue

                    # Run with a per-chunk timeout so one slow piece can't hang the whole job
                    result_box = [None]
                    def _run(p=chunk_path): result_box[0] = model.transcribe(p, verbose=False, word_timestamps=True)
                    t = _th.Thread(target=_run, daemon=True)
                    t.start(); t.join(timeout=180)
                    if result_box[0] is None:
                        log(f"  #⚠️  Chunk {idx}/{total_chunks} timed out — skipping")
                    else:
                        for seg in result_box[0].get("segments", []):
                            seg["start"] = seg.get("start", 0) + start
                            seg["end"] = seg.get("end", 0) + start
                            all_segments.append(seg)
                        pct = round(idx / total_chunks * 100)
                        log(f"   🎙️  Transcribed chunk {idx}/{total_chunks} ({pct}%)")

                    try: Path(chunk_path).unlink()
                    except Exception: pass

                segments = all_segments
                log(f"✅ {len(segments)} transcript segments")
            except ImportError:
                log("ℹ️  Whisper not available — AI will pick by timestamp instead")
            except Exception as e:
                log(f"⚠️  Transcription skipped: {e}")


        # 4. Pick clips
        count    = settings.get("clip_count", 10)
        clip_len = settings.get("clip_length", 30)
        clips    = []

        if settings.get("ai_pick") and CLAUDE_API_KEY and segments:
            log(f"🤖 Asking Claude to pick {count} clips…")
            try:
                clips = pick_clips_claude(segments, count, clip_len, CLAUDE_API_KEY, log)
            except Exception as e:
                log(f"⚠️  Claude failed: {e} — using evenly spaced")
        if not clips:
            clips = pick_clips_evenly(count, clip_len, dur)

        # Pad if short
        if len(clips) < count:
            clips += pick_clips_evenly(count - len(clips), clip_len, dur)

        # 5. Cut clips
        fmt      = settings.get("output_format", "both")
        vertical = fmt in ("vertical", "both")
        both     = fmt == "both"
        made     = 0
        total    = min(count, len(clips))
        font_name = settings.get("subtitle_font", "Arial")
        font_path = ensure_font(font_name)

        saved_meta = []
        for i, clip in enumerate(clips[:total], 1):
            s = float(clip.get("start", 0))
            e = float(clip.get("end", s + clip_len))

            # Enforce requested clip length — center the viral moment in the window
            actual_len = e - s
            if actual_len < clip_len:
                # Extend to fill the full requested duration
                # Try to extend equally on both sides of the viral moment
                mid    = (s + e) / 2
                s      = max(0, mid - clip_len / 2)
                e      = s + clip_len
                # If we hit the end of video, back up
                if e > dur:
                    e = dur
                    s = max(0, dur - clip_len)
            elif actual_len > clip_len * 1.15:
                # If Claude picked something too long, trim to target from the start
                e = s + clip_len

            # Final clamp to video bounds
            s = max(0, min(s, dur - 1))
            e = min(e, dur)

            if e - s < 1:
                log(f"⚠️  Clip {i} too short after adjustment, skip"); continue

            log(f"✂️  Clip {i}/{total}: {s:.1f}s → {e:.1f}s ({e-s:.0f}s) | targeting {clip_len}s")

            hook = clip.get("hook", f"Clip {i}")
            safe = "".join(c if c.isalnum() or c in " _-" else ""
                           for c in hook)[:60].strip().replace(" ", "_")
            stem = f"clip_{i:02d}_{safe}"

            # Build subtitles
            ass = None
            if settings.get("subtitles") and segments:
                ass = build_ass_content(
                    segments, s, e, vertical or both,
                    font_family=FONTS_CONFIG.get(font_name, {}).get("family", "Arial"),
                    font_file=font_path,
                    font_size=settings.get("subtitle_size", 52),
                    colour=settings.get("subtitle_colour", "white")
                )

            try:
                paths = extract_clip(
                    video_path, s, e,
                    str(out_dir / (stem + ".mp4")),
                    vertical=vertical, both=both,
                    ass_content=ass,
                    audio_norm=settings.get("audio_norm", True),
                    log_fn=log,
                    smart_reframe_mode=bool(settings.get("smart_reframe"))
                )

                # Smart reframe pass
                if settings.get("smart_reframe"):
                    for p in paths:
                        if "_9x16" in p or (not both and vertical):
                            log(f"  #🎯 Smart reframe…")
                            try:
                                smart_reframe(p, p + "_rf.mp4", smoothness=0.3, log_fn=log)
                                os.replace(p + "_rf.mp4", p)
                            except Exception as ex:
                                log(f"  #⚠️  Reframe failed: {ex}")

                # Face blur pass
                if settings.get("face_blur"):
                    for p in paths:
                        log(f"  #👁️  Face blur…")
                        try:
                            blur_faces_opencv(p, p + "_bl.mp4", strength=5, log_fn=log)
                            os.replace(p + "_bl.mp4", p)
                        except Exception as ex:
                            log(f"   ⚠️  Blur failed: {ex}")

                made += 1
                log(f"  #✅ Done")
                # Save clip metadata for the picker page
                for path in paths:
                    fname = Path(path).name
                    saved_meta.append({
                        "filename": fname,
                        "score": clip.get("score", 0),
                        "tag": clip.get("tag", ""),
                        "hook": hook,
                        "start": round(s, 1),
                        "end": round(e, 1),
                        "duration": round(e - s, 1),
                    })
                _save_clip_metadata(job_id, saved_meta)
            except Exception as ex:
                log(f"   ❌ Failed: {ex}")

        # Cleanup tmp
        shutil.rmtree(str(tmp_dir), ignore_errors=True)

        _set_job_status(job_id, "done", made)
        log(f"\n🎉 Done! {made}/{total} clips ready")

        log(f"\n🎉 Done! {made}/{total} clips ready")

        # Email the account holder that their clips are ready (non-blocking)
        try:
            _db = _db_session()
            try:
                _job = _db.query(Job).filter(Job.id == job_id).first()
                _user = _db.query(User).filter(User.id == _job.user_id).first() if _job else None
                if _user and _user.email:
                    send_job_done_email(_user.email, made)
            finally:
                _db.close()
        except Exception as _email_err:
            print(f"[Email] job-done notify failed (non-fatal): {_email_err}")


    except Exception as ex:
        _set_job_status(job_id, "failed")
        log(f"\n💥 Job failed: {ex}")


def _ffprobe_duration(path: str) -> float:
    """Try multiple methods to get video duration."""
    # Method 1: check yt-dlp duration file saved alongside video
    try:
        dur_file = str(Path(path).with_suffix(".duration"))
        if Path(dur_file).exists():
            val = float(Path(dur_file).read_text().strip())
            if val > 0:
                return val
    except:
        pass

    # Method 2: ffprobe format duration
    try:
        r = subprocess.run(
            [FFPROBE_BIN,"-v","quiet","-print_format","json",
             "-show_format","-show_streams", path],
            capture_output=True, text=True, timeout=30)
        import json as _json
        data = _json.loads(r.stdout)
        dur = float(data.get("format", {}).get("duration", 0) or 0)
        if dur > 0:
            return dur
        # Try streams
        for s in data.get("streams", []):
            dur = float(s.get("duration", 0) or 0)
            if dur > 0:
                return dur
    except:
        pass

    # Method 3: ffprobe simple
    try:
        r = subprocess.run(
            [FFPROBE_BIN,"-v","error","-select_streams","v:0",
             "-show_entries","stream=duration",
             "-of","default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        val = float(r.stdout.strip())
        if val > 0:
            return val
    except:
        pass

    return 0.0



# ══════════════════════════════════════════════════════════════════
#  YOUTUBE OAUTH + UPLOAD ROUTES
# ══════════════════════════════════════════════════════════════════

@app.get("/social/youtube/auth")
def youtube_auth(current_user: User = Depends(get_current_user)):
    try:
        import urllib.parse
        params = {
            "client_id": YOUTUBE_CLIENT_ID,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(YOUTUBE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": str(current_user.id),
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
        return {"auth_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/social/youtube/callback")
def youtube_callback(code: str, state: str, db: Session = Depends(get_db)):
    try:
        import requests as _req
        # Exchange code for tokens
        token_resp = _req.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }, timeout=20)
        tokens = token_resp.json()
        user_id = state  # UUID string
        # Get channel name
        ch_resp = _req.get("https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {tokens.get('access_token', '')}"}, timeout=15)
        ch = ch_resp.json().get("items", [{}])[0]
        ch_name = ch.get("snippet", {}).get("title", "My Channel")
        # Upsert SocialAccount
        sa = db.query(SocialAccount).filter(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == "youtube"
        ).first()
        if not sa:
            sa = SocialAccount(user_id=user_id, platform="youtube")
            db.add(sa)
        sa.access_token    = enc_token(tokens.get("access_token"))
        sa.refresh_token   = enc_token(tokens.get("refresh_token"))
        sa.account_name    = ch_name
        sa.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        db.commit()
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            "<script>window.close();</script>"
            "<p style=\'font-family:sans-serif;text-align:center;margin-top:80px\'>"
            "✅ YouTube connected! You can close this tab.</p>"
        )
    except Exception as e:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"<p style=\'color:red\'>Error: {e}</p>")


@app.get("/social/youtube/status")
def youtube_status(current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    try:
        sa = db.query(SocialAccount).filter(
            SocialAccount.user_id == current_user.id,
            SocialAccount.platform == "youtube"
        ).first()
        if not sa:
            return {"connected": False}
        return {"connected": True, "channel_name": sa.account_name or "YouTube"}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.delete("/social/youtube/disconnect")
def youtube_disconnect(current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    try:
        sa = db.query(SocialAccount).filter(
            SocialAccount.user_id == current_user.id,
            SocialAccount.platform == "youtube"
        ).first()
        if sa:
            db.delete(sa)
            db.commit()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/social/youtube/upload")
def youtube_upload(
    clip_job_id: str,
    clip_filename: str,
    title: str,
    description: str = "",
    publish_at: str = "",   # ISO8601 e.g. "2026-06-10T18:00:00Z", empty = public now
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a clip to YouTube. Optionally schedule via publish_at (ISO8601)."""
    try:
        import requests as _req, json as _json
        sa = db.query(SocialAccount).filter(
            SocialAccount.user_id == current_user.id,
            SocialAccount.platform == "youtube"
        ).first()
        if not sa:
            raise HTTPException(status_code=400, detail="YouTube not connected. Connect it in Settings first.")
        # Refresh token if expired
        token = dec_token(sa.access_token)
        if sa.token_expires_at and sa.token_expires_at < datetime.utcnow():
            r = _req.post("https://oauth2.googleapis.com/token", data={
                "client_id": YOUTUBE_CLIENT_ID,
                "client_secret": YOUTUBE_CLIENT_SECRET,
                "refresh_token": dec_token(sa.refresh_token),
                "grant_type": "refresh_token",
            }, timeout=20)
            td = r.json()
            token = td.get("access_token", token)
            sa.access_token = enc_token(token)
            sa.token_expires_at = datetime.utcnow() + timedelta(seconds=td.get("expires_in", 3600))
            db.commit()
        # Validate job ownership
        job = db.query(Job).filter(Job.id == clip_job_id,
                                    Job.user_id == current_user.id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        clip_path = JOBS_DIR / clip_job_id / clip_filename
        if not clip_path.exists():
            raise HTTPException(status_code=404, detail="Clip file not found")
        # Build metadata
        status_body: dict = {"privacyStatus": "public"}
        if publish_at:
            status_body = {"privacyStatus": "private", "publishAt": publish_at}
        meta = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "categoryId": "22"
            },
            "status": status_body
        }
        # Initiate resumable upload
        init_r = _req.post(
            "https://www.googleapis.com/upload/youtube/v3/videos"
            "?uploadType=resumable&part=snippet,status",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
            },
            data=_json.dumps(meta),
            timeout=30
        )
        upload_url = init_r.headers.get("Location")
        if not upload_url:
            raise HTTPException(status_code=500, detail=f"YouTube init failed: {init_r.text[:300]}")
        # Upload video bytes
        with open(str(clip_path), "rb") as f:
            video_data = f.read()
        up_r = _req.put(upload_url, data=video_data,
                         headers={"Content-Type": "video/mp4"},
                         timeout=300)
        if up_r.status_code not in (200, 201):
            raise HTTPException(status_code=500, detail=f"Upload failed: {up_r.text[:300]}")
        yt_video_id = up_r.json().get("id", "")
        return {
            "success": True,
            "youtube_video_id": yt_video_id,
            "youtube_url": f"https://youtu.be/{yt_video_id}",
            "scheduled": bool(publish_at),
            "publish_at": publish_at or None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════
#  TIKTOK OAUTH + UPLOAD ROUTES
# ══════════════════════════════════════════════════════════════════

@app.get("/social/tiktok/auth")
def tiktok_auth(current_user: User = Depends(get_current_user)):
    """Step 1 — return the TikTok OAuth URL for the frontend to open."""
    import urllib.parse
    if not TIKTOK_CLIENT_KEY:
        raise HTTPException(500, "TikTok not configured — add TIKTOK_CLIENT_KEY to Railway vars")
    params = {
        "client_key":     TIKTOK_CLIENT_KEY,
        "response_type":  "code",
        "scope":          TIKTOK_SCOPES,
        "redirect_uri":   TIKTOK_REDIRECT_URI,
        "state":          str(current_user.id),
    }
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params)
    return {"auth_url": url}


@app.get("/auth/tiktok/callback")
def tiktok_callback(code: str = None, state: str = None,
                    error: str = None, db: Session = Depends(get_db)):
    """Step 2 — TikTok redirects here with ?code=... Exchange it for tokens."""
    from fastapi.responses import HTMLResponse
    if error or not code:
        return HTMLResponse(
            f"<p style='color:red;font-family:sans-serif;text-align:center;margin-top:80px'>"
            f"TikTok auth failed: {error or 'no code returned'}</p>"
        )
    try:
        import requests as _req
        # Exchange code for access + refresh tokens
        token_resp = _req.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key":     TIKTOK_CLIENT_KEY,
                "client_secret":  TIKTOK_CLIENT_SECRET,
                "code":           code,
                "grant_type":     "authorization_code",
                "redirect_uri":   TIKTOK_REDIRECT_URI,
            },
            timeout=20,
        )
        td = token_resp.json()
        access_token  = td.get("access_token", "")
        refresh_token = td.get("refresh_token", "")
        expires_in    = td.get("expires_in", 86400)
        if not access_token:
            return HTMLResponse(
                f"<p style='color:red;font-family:sans-serif;text-align:center;margin-top:80px'>"
                f"Token exchange failed: {td}</p>"
            )

        # Fetch TikTok display name
        user_resp = _req.get(
            "https://open.tiktokapis.com/v2/user/info/",
            params={"fields": "display_name,username"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        udata = user_resp.json().get("data", {}).get("user", {})
        display_name = udata.get("display_name") or udata.get("username") or "TikTok User"

        # Upsert SocialAccount row
        user_id = state  # UUID passed through state param
        sa = db.query(SocialAccount).filter(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == "tiktok"
        ).first()
        if not sa:
            sa = SocialAccount(user_id=user_id, platform="tiktok")
            db.add(sa)
        sa.access_token     = enc_token(access_token)
        sa.refresh_token    = enc_token(refresh_token)
        sa.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        sa.account_name     = display_name
        db.commit()

        return HTMLResponse("""
<html>
<body style="background:#000;font-family:sans-serif;text-align:center;padding-top:80px">
  <p style="color:#fff;font-size:18px">&#x2705; TikTok connected!</p>
  <p style="color:#888;font-size:14px">You can close this window.</p>
  <script>
    if (window.opener) { window.opener.postMessage('tiktok_connected', '*'); window.close(); }
  </script>
</body>
</html>""")
    except Exception as e:
        return HTMLResponse(
            f"<p style='color:red;font-family:sans-serif;text-align:center;margin-top:80px'>"
            f"Internal error: {e}</p>"
        )


# ── TikTok token refresh helper ───────────────────────────────────────────────────────────────────────────
def _tiktok_refresh(sa, db):
    """Refresh an expired TikTok access_token using refresh_token."""
    import requests as _req
    resp = _req.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key":    TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "grant_type":    "refresh_token",
            "refresh_token": dec_token(sa.refresh_token),
        },
        timeout=20,
    )
    td = resp.json()
    new_access  = td.get("access_token")
    new_refresh = td.get("refresh_token")
    new_expires = td.get("expires_in", 86400)
    if not new_access:
        raise HTTPException(502, f"TikTok refresh failed: {td}")
    sa.access_token     = enc_token(new_access)
    if new_refresh:
        sa.refresh_token = enc_token(new_refresh)
    sa.token_expires_at = datetime.utcnow() + timedelta(seconds=new_expires)
    db.commit()
    return new_access


@app.get("/social/tiktok/status")
def tiktok_status(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    sa = db.query(SocialAccount).filter(
        SocialAccount.user_id == str(current_user.id),
        SocialAccount.platform == "tiktok"
    ).first()
    if sa:
        return {"connected": True, "account_name": sa.account_name or "TikTok"}
    return {"connected": False, "account_name": ""}


@app.delete("/social/tiktok/disconnect")
def tiktok_disconnect(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    sa = db.query(SocialAccount).filter(
        SocialAccount.user_id == str(current_user.id),
        SocialAccount.platform == "tiktok"
    ).first()
    if sa:
        db.delete(sa)
        db.commit()
    return {"disconnected": True}


@app.post("/social/tiktok/upload")
async def tiktok_upload(
    clip_id: str = Form(...),
    title: str = Form(""),
    privacy_level: str = Form("PUBLIC_TO_EVERYONE"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sa = db.query(SocialAccount).filter(
        SocialAccount.user_id == str(current_user.id),
        SocialAccount.platform == "tiktok"
    ).first()
    if not sa:
        raise HTTPException(400, "TikTok account not connected")

    # Refresh token if expired
    if sa.token_expires_at and datetime.utcnow() >= sa.token_expires_at:
        access_token = _tiktok_refresh(sa, db)
    else:
        access_token = dec_token(sa.access_token)

    # Find clip file
    clip = db.query(Clip).filter(
        Clip.id == clip_id,
        Clip.user_id == str(current_user.id)
    ).first()
    if not clip:
        raise HTTPException(404, "Clip not found")

    clip_path = clip.file_path
    if not os.path.exists(clip_path):
        raise HTTPException(404, "Clip file not found on disk")

    file_size  = os.path.getsize(clip_path)
    chunk_size = 10 * 1024 * 1024
    total_chunks = (file_size + chunk_size - 1) // chunk_size
    import requests as _req

    # Step 1: Initialize upload
    init_resp = _req.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "post_info": {
                "title": title[:150] or "SDP Short",
                "privacy_level": privacy_level,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            },
        },
        timeout=30,
    )
    init_data = init_resp.json()
    if init_data.get("error", {}).get("code", "ok") != "ok":
        raise HTTPException(502, f"TikTok init failed: {init_data}")

    publish_id = init_data["data"]["publish_id"]
    upload_url = init_data["data"]["upload_url"]

    # Step 2: Upload chunks
    chunk_num = 0
    with open(clip_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            start = chunk_num * chunk_size
            end   = start + len(chunk) - 1
            _req.put(
                upload_url,
                headers={
                    "Content-Type":   "video/mp4",
                    "Content-Range":  f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(len(chunk)),
                },
                data=chunk,
                timeout=120,
            )
            chunk_num += 1

    return {"publish_id": publish_id, "status": "processing"}


#  ADMIN — YOUTUBE COOKIES UPLOAD
# ══════════════════════════════════════════════════════════════════

class CookiesIn(BaseModel):
    content: str  # Full Netscape cookie file text

def _cookies_path() -> Path:
    """Path to cookies file on the persistent volume."""
    db_path = Path(os.getenv("DB_PATH", "/tmp/sdp_shorts.db"))
    return db_path.parent / "yt_cookies.txt"

@app.post("/admin/cookies")
def upload_cookies(data: CookiesIn, user: User = Depends(get_current_user)):
    """Upload YouTube cookies to the persistent volume. Admin only."""
    if user.email not in ADMIN_EMAILS:
        raise HTTPException(403, "Admin only")
    path = _cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.content)
    lines = len(data.content.splitlines())
    size_kb = round(len(data.content) / 1024, 1)
    return {"ok": True, "path": str(path), "lines": lines, "size_kb": size_kb}

@app.get("/admin/cookies/status")
def cookies_status(user: User = Depends(get_current_user)):
    """Check if YouTube cookies are loaded on the volume. Admin only."""
    if user.email not in ADMIN_EMAILS:
        raise HTTPException(403, "Admin only")
    path = _cookies_path()
    if path.exists():
        content = path.read_text()
        return {"exists": True, "path": str(path),
                "lines": len(content.splitlines()),
                "size_kb": round(len(content) / 1024, 1)}
    return {"exists": False, "path": str(path)}

@app.delete("/admin/cookies")
def delete_cookies(user: User = Depends(get_current_user)):
    """Delete the YouTube cookies file. Admin only."""
    if user.email not in ADMIN_EMAILS:
        raise HTTPException(403, "Admin only")
    path = _cookies_path()
    if path.exists():
        path.unlink()
        return {"ok": True, "deleted": str(path)}
    return {"ok": True, "deleted": None}

# ══════════════════════════════════════════════════════════════════
#  CLEANUP  (delete job files > 24 hours)
# ══════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    asyncio.create_task(_cleanup_loop())
    # Mark any stuck "processing" jobs as failed on restart
    db = _db_session()
    try:
        stuck = db.query(Job).filter(Job.status == "processing").all()
        for j in stuck:
            j.status = "failed"
            j.log = (j.log or "") + "\n⚠️ Marked failed on restart\n"
        if stuck:
            db.commit()
            print(f"[Startup] Marked {len(stuck)} stuck jobs as failed")
    finally:
        db.close()
    print(f"[Startup] ffmpeg: {FFMPEG_BIN}")
    print(f"[Startup] ffprobe: {FFPROBE_BIN}")


async def _cleanup_loop():
    import asyncio
    while True:
        await asyncio.sleep(3600)   # run hourly
        cutoff = datetime.utcnow() - timedelta(hours=48)
        db = _db_session()
        try:
            old_jobs = db.query(Job).filter(Job.updated_at < cutoff,
                                             Job.status == "done").all()
            for job in old_jobs:
                shutil.rmtree(str(JOBS_DIR / job.id), ignore_errors=True)
        finally:
            db.close()
