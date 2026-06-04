"""
╔══════════════════════════════════════════════════════════════════╗
║   SDP SHORTS WEB  —  Backend API  v1.0                         ║
║   Squeeky Door Productions  |  squeekydoorproductions.com       ║
╚══════════════════════════════════════════════════════════════════╝

FastAPI backend:  auth · jobs · tokens · Stripe · PayPal

ENV VARS needed (.env):
    SECRET_KEY          = any random 32-char string
    CLAUDE_API_KEY      = sk-ant-...
    STRIPE_SECRET_KEY   = sk_live_...  (or sk_test_...)
    STRIPE_WEBHOOK_SECRET = whsec_...
    STRIPE_PRICE_STARTER  = price_...
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

import os, uuid, json, shutil, asyncio, tempfile, math, subprocess, threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

from fastapi import (FastAPI, Depends, HTTPException, BackgroundTasks,
                     Request, Header, status)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlalchemy import (create_engine, Column, String, Integer, Float,
                        Boolean, DateTime, Text, ForeignKey)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from jose import JWTError, jwt
from passlib.context import CryptContext
import stripe
import requests as http_req
from dotenv import load_dotenv
import smtplib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

# ══════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════

SECRET_KEY      = os.getenv("SECRET_KEY", "change-me-in-production-32chars!!")
ALGORITHM       = "HS256"
TOKEN_EXP_HOURS = 24 * 7   # 1 week JWT

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

TOKENS_PER_CLIP = 0.5   # Each clip costs half a token

# ── Admin / owner accounts — bypass all token checks ──────────────
ADMIN_EMAILS = {
    "thelabsdp206@gmail.com",
    "squeekydoorphotos@gmail.com",
    "layzphotos@gmail.com",
    "ar.photo.sdp@gmail.com",
    "wimplobeats@gmail.com",
}

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


Base.metadata.create_all(bind=engine)


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


def hash_pw(pw: str) -> str:        return pwd_ctx.hash(pw)
def verify_pw(pw: str, h: str) -> bool: return pwd_ctx.verify(pw, h)


def create_jwt(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(hours=TOKEN_EXP_HOURS)
    return jwt.encode({"sub": user_id, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(authorization: str = Header(None),
                     db: Session = Depends(get_db)) -> User:
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
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
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
      <p style="color:#888;line-height:1.6">Thanks for signing up! Click below to verify your email and get your 5 free tokens.</p>
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


# ══════════════════════════════════════════════════════════════════
#  APP
# ══════════════════════════════════════════════════════════════════

app = FastAPI(title="SDP Shorts Web API", version="1.0.0")

app.add_middleware(CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "https://spd-shorts-factory.netlify.app",
        "https://shorts.squeekydoorproductions.com",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email already registered")
    if len(data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    verify_tok = secrets.token_urlsafe(32)
    user = User(email=data.email, hashed_pw=hash_pw(data.password),
                verify_token=verify_tok, email_verified=False)
    db.add(user); db.commit(); db.refresh(user)
    # Send verification email (non-blocking)
    try: send_verification_email(data.email, verify_tok)
    except: pass
    return {"token": create_jwt(user.id), "tokens": user.tokens, "plan": user.plan,
            "email": user.email, "is_admin": user.email in ADMIN_EMAILS,
            "email_verified": user.email_verified}


@app.post("/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_pw(data.password, user.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    return {"token": create_jwt(user.id), "tokens": user.tokens, "plan": user.plan,
            "email": user.email, "is_admin": user.email in ADMIN_EMAILS,
            "email_verified": user.email_verified}


@app.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    from datetime import timezone
    next_free = None
    if user.plan == "free" and user.last_free_job_at:
        since = (datetime.utcnow() - user.last_free_job_at).total_seconds()
        if since < 7 * 24 * 3600:
            nf = user.last_free_job_at + timedelta(days=7)
            next_free = nf.isoformat()
    return {"id": user.id, "email": user.email, "tokens": user.tokens,
            "plan": user.plan, "created_at": user.created_at,
            "next_free_job_at": next_free,
            "tokens_per_clip": TOKENS_PER_CLIP,
            "is_admin": user.email in ADMIN_EMAILS,
            "email_verified": user.email_verified}

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
def forgot_password(data: ForgotIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
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
    if len(data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
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
    cost = round(data.clip_count * TOKENS_PER_CLIP, 1)
    admin = user.email in ADMIN_EMAILS

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
            log("🎙️  Attempting transcription…")
            try:
                import whisper, threading as _th
                log("   Loading Whisper tiny model…")
                model = whisper.load_model("tiny")
                # For long videos only transcribe first 10 min — enough for clip picking
                transcribe_path = video_path
                if dur > 600:
                    import subprocess as _sp, tempfile as _tf
                    trimmed = str(Path(tmp_dir) / "trim_tx.mp4")
                    _sp.run([FFMPEG_BIN, "-y", "-ss", "0", "-i", video_path,
                             "-t", "600", "-c", "copy", trimmed],
                            capture_output=True, timeout=60)
                    if Path(trimmed).exists():
                        transcribe_path = trimmed
                        log("   Transcribing first 10 min of video…")
                # Run with 5-min timeout so it never hangs forever
                result_box = [None]
                def _run(): result_box[0] = model.transcribe(transcribe_path, verbose=False, word_timestamps=True)
                t = _th.Thread(target=_run, daemon=True); t.start(); t.join(timeout=300)
                if result_box[0] is None:
                    raise RuntimeError("Transcription timed out after 5 min")
                segments = result_box[0].get("segments", [])
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
                            log(f"   🎯 Smart reframe…")
                            try:
                                smart_reframe(p, p + "_rf.mp4", smoothness=0.3, log_fn=log)
                                os.replace(p + "_rf.mp4", p)
                            except Exception as ex:
                                log(f"   ⚠️  Reframe failed: {ex}")

                # Face blur pass
                if settings.get("face_blur"):
                    for p in paths:
                        log(f"   👁️  Face blur…")
                        try:
                            blur_faces_opencv(p, p + "_bl.mp4", strength=5, log_fn=log)
                            os.replace(p + "_bl.mp4", p)
                        except Exception as ex:
                            log(f"   ⚠️  Blur failed: {ex}")

                made += 1
                log(f"   ✅ Done")
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
