import sys
import os
import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(PROJECT_ROOT)

from services.shared.models import Base, Pipeline, PipelineRun, Error, User

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://debugger:debugger@localhost:5433/pipeline_debugger"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── Password helpers (stdlib only) ────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split(":", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(check.hex(), digest_hex)
    except Exception:
        return False

# ── Pydantic schemas ───────────────────────────────────────────────────────────

class PipelineStatus(BaseModel):
    name: str
    status: str
    lastRun: str

class ErrorItem(BaseModel):
    pipeline: str
    error: str
    rootCause: str
    fix: str
    detectedAt: str | None = None

class RunItem(BaseModel):
    runId: str
    status: str
    createdAt: str

class DashboardData(BaseModel):
    pipelines: List[PipelineStatus]
    errors: List[ErrorItem]

class RegisterRequest(BaseModel):
    email: str
    name: str | None = None
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class PaymentRequest(BaseModel):
    plan: str   # 'starter' | 'pro' | 'enterprise'

class UserOut(BaseModel):
    email: str
    name: str | None
    paid: bool
    plan: str | None

class AuthResponse(BaseModel):
    token: str
    user: UserOut

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        # ── Column additions (safe: IF NOT EXISTS) ────────────────────────────
        conn.execute(text("ALTER TABLE errors ADD COLUMN IF NOT EXISTS detected_at VARCHAR"))

        # ── NOT NULL enforcement (fill nulls first, then set constraint) ──────
        conn.execute(text("UPDATE pipelines      SET status   = 'Failed'   WHERE status   IS NULL"))
        conn.execute(text("UPDATE pipelines      SET last_run = 'Unknown'  WHERE last_run IS NULL"))
        conn.execute(text("UPDATE pipeline_runs  SET status   = 'Failed'   WHERE status   IS NULL"))
        conn.execute(text("UPDATE pipeline_runs  SET created_at = now()::text WHERE created_at IS NULL"))
        conn.execute(text("ALTER TABLE pipelines     ALTER COLUMN name     SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipelines     ALTER COLUMN status   SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipelines     ALTER COLUMN last_run SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipeline_runs ALTER COLUMN pipeline_name SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipeline_runs ALTER COLUMN run_id     SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipeline_runs ALTER COLUMN status     SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipeline_runs ALTER COLUMN created_at SET NOT NULL"))
        conn.execute(text("ALTER TABLE errors        ALTER COLUMN pipeline_name SET NOT NULL"))
        conn.execute(text("ALTER TABLE errors        ALTER COLUMN error_type    SET NOT NULL"))

        # ── CHECK constraints (IF NOT EXISTS via DO block) ────────────────────
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_pipelines_status'
                ) THEN
                    ALTER TABLE pipelines ADD CONSTRAINT ck_pipelines_status
                        CHECK (status IN ('Failed', 'Success'));
                END IF;
            END $$;
        """))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_pipeline_runs_status'
                ) THEN
                    ALTER TABLE pipeline_runs ADD CONSTRAINT ck_pipeline_runs_status
                        CHECK (status IN ('Failed', 'Success'));
                END IF;
            END $$;
        """))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_plan'
                ) THEN
                    ALTER TABLE users ADD CONSTRAINT ck_users_plan
                        CHECK (plan IN ('starter', 'pro', 'enterprise'));
                END IF;
            END $$;
        """))

        # ── Unique composite key on errors (pipeline_name, error_type) ────────
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_errors_pipeline_error'
                ) THEN
                    ALTER TABLE errors ADD CONSTRAINT uq_errors_pipeline_error
                        UNIQUE (pipeline_name, error_type);
                END IF;
            END $$;
        """))

        # ── server_default for users.paid ─────────────────────────────────────
        conn.execute(text(
            "ALTER TABLE users ALTER COLUMN paid SET DEFAULT false"
        ))

        conn.commit()
    yield

app = FastAPI(title="AI Pipeline Debugger API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── DB dependency ──────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Auth dependency ────────────────────────────────────────────────────────────

def get_current_user(
    x_session_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Missing session token")
    user = db.query(User).filter(User.session_token == x_session_token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return user

def _user_out(user: User) -> dict:
    return {"email": user.email, "name": user.name, "paid": user.paid, "plan": user.plan}

# ── Auth endpoints ─────────────────────────────────────────────────────────────

@app.post("/auth/register", response_model=AuthResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    token = secrets.token_urlsafe(32)
    user  = User(
        email         = req.email,
        name          = req.name,
        password_hash = hash_password(req.password),
        paid          = False,
        session_token = token,
        created_at    = datetime.now(timezone.utc).isoformat(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": token, "user": _user_out(user)}

@app.post("/auth/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    # Rotate session token on every login
    user.session_token = secrets.token_urlsafe(32)
    db.commit()
    return {"token": user.session_token, "user": _user_out(user)}

@app.get("/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)

@app.post("/auth/payment", response_model=UserOut)
def complete_payment(
    req: PaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.paid = True
    current_user.plan = req.plan
    db.commit()
    db.refresh(current_user)
    return _user_out(current_user)

@app.delete("/auth/session", status_code=204)
def sign_out(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.session_token = None
    db.commit()

# ── Dashboard endpoints ────────────────────────────────────────────────────────

@app.get("/dashboard", response_model=DashboardData)
def get_dashboard_data(db: Session = Depends(get_db)):
    pipelines = db.query(Pipeline).all()
    errors    = db.query(Error).order_by(Error.detected_at.desc()).all()
    return {
        "pipelines": [{"name": p.name, "status": p.status, "lastRun": p.last_run} for p in pipelines],
        "errors":    [{"pipeline": e.pipeline_name, "error": e.error_type, "rootCause": e.root_cause, "fix": e.fix, "detectedAt": e.detected_at} for e in errors],
    }

@app.get("/pipelines/{pipeline_name}/errors", response_model=List[ErrorItem])
def get_pipeline_errors(pipeline_name: str, db: Session = Depends(get_db)):
    if not db.query(Pipeline).filter(Pipeline.name == pipeline_name).first():
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_name}' not found")
    errors = db.query(Error).filter(Error.pipeline_name == pipeline_name).order_by(Error.detected_at.desc()).all()
    return [{"pipeline": e.pipeline_name, "error": e.error_type, "rootCause": e.root_cause, "fix": e.fix, "detectedAt": e.detected_at} for e in errors]

@app.get("/pipelines/{pipeline_name}/runs", response_model=List[RunItem])
def get_pipeline_runs(pipeline_name: str, db: Session = Depends(get_db)):
    if not db.query(Pipeline).filter(Pipeline.name == pipeline_name).first():
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_name}' not found")
    runs = (
        db.query(PipelineRun)
        .filter(PipelineRun.pipeline_name == pipeline_name)
        .order_by(PipelineRun.created_at.desc())
        .all()
    )
    return [{"runId": r.run_id, "status": r.status, "createdAt": r.created_at} for r in runs]

@app.get("/health")
def health():
    return {"status": "ok"}
