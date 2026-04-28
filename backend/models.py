"""Pydantic models for Field Intelligence Platform."""
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime, timezone
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- USERS / TEAMS ----------
Role = Literal["TM", "Manager", "Admin"]


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: Role = "TM"
    team_id: Optional[str] = None
    region: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[Role] = None
    team_id: Optional[str] = None
    region: Optional[str] = None
    active_status: Optional[bool] = None
    password: Optional[str] = None


class UserPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    full_name: str
    email: EmailStr
    role: Role
    team_id: Optional[str] = None
    region: Optional[str] = None
    active_status: bool = True
    created_at: str
    updated_at: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    token: str
    user: UserPublic


class TeamCreate(BaseModel):
    team_name: str
    manager_user_id: Optional[str] = None
    region: Optional[str] = None


class Team(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    team_name: str
    manager_user_id: Optional[str] = None
    region: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------- DOCTORS ----------
Segment = Literal["Occasional", "Active", "Engaged", "Expert"]
DoctorStatus = Literal["Active", "Inactive", "Watchlist"]
DoctorType = Literal["GP", "Ortho", "Other"]


class DoctorCreate(BaseModel):
    doctor_name: str
    clinic_name: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    doctor_type: DoctorType = "GP"
    segment: Segment = "Occasional"
    assigned_tm_id: Optional[str] = None
    team_id: Optional[str] = None
    status: DoctorStatus = "Active"
    general_notes: Optional[str] = None


class DoctorUpdate(BaseModel):
    doctor_name: Optional[str] = None
    clinic_name: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    doctor_type: Optional[DoctorType] = None
    segment: Optional[Segment] = None
    assigned_tm_id: Optional[str] = None
    team_id: Optional[str] = None
    status: Optional[DoctorStatus] = None
    general_notes: Optional[str] = None


class Doctor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    doctor_name: str
    clinic_name: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    doctor_type: DoctorType = "GP"
    segment: Segment = "Occasional"
    assigned_tm_id: Optional[str] = None
    team_id: Optional[str] = None
    status: DoctorStatus = "Active"
    general_notes: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------- VISITS ----------
VisitType = Literal[
    "In-person visit",
    "Phone call",
    "Online meeting",
    "Event conversation",
    "Training/session",
    "Other",
]
Sentiment = Literal["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]
OpportunityState = Literal["Blocked", "Stuck", "Advancing", "Unknown"]


class PromiseDraft(BaseModel):
    task_title: str
    task_description: Optional[str] = ""
    suggested_due_date: Optional[str] = None  # ISO date
    priority: Literal["Low", "Medium", "High"] = "Medium"


class AIExtraction(BaseModel):
    summary: str = ""
    topics: List[str] = []
    barriers: List[str] = []
    sentiment: Sentiment = "Neutral"
    opportunity_state: OpportunityState = "Unknown"
    promises_detected: List[PromiseDraft] = []
    suggested_next_action: str = ""
    market_signals: List[str] = []
    privacy_warnings: List[str] = []  # e.g., "Possible patient name detected"


class AnalyzeNoteRequest(BaseModel):
    note: str
    doctor_id: Optional[str] = None


class VisitCreate(BaseModel):
    doctor_id: str
    visit_date: Optional[str] = None  # ISO datetime
    visit_type: VisitType = "In-person visit"
    free_text_note: str = ""
    confirmed_topics: List[str] = []
    confirmed_barriers: List[str] = []
    sentiment: Sentiment = "Neutral"
    opportunity_state: OpportunityState = "Unknown"
    next_step: Optional[str] = None
    promises: List[PromiseDraft] = []  # tasks user confirmed
    ai_extraction: Optional[AIExtraction] = None  # raw AI result preserved separately


class Visit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    doctor_id: str
    tm_user_id: str
    team_id: Optional[str] = None
    visit_date: str = Field(default_factory=_now_iso)
    visit_type: VisitType = "In-person visit"
    free_text_note: str = ""
    confirmed_topics: List[str] = []
    confirmed_barriers: List[str] = []
    sentiment: Sentiment = "Neutral"
    opportunity_state: OpportunityState = "Unknown"
    next_step: Optional[str] = None
    ai_extraction: Optional[AIExtraction] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------- TASKS / PROMISES ----------
TaskStatus = Literal["Open", "Completed", "Overdue", "Cancelled"]
TaskPriority = Literal["Low", "Medium", "High"]


class TaskCreate(BaseModel):
    doctor_id: str
    visit_id: Optional[str] = None
    task_title: str
    task_description: Optional[str] = ""
    due_date: Optional[str] = None  # ISO date
    priority: TaskPriority = "Medium"
    created_from_ai: bool = False


class TaskUpdate(BaseModel):
    task_title: Optional[str] = None
    task_description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None


class Task(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    doctor_id: str
    tm_user_id: str
    team_id: Optional[str] = None
    visit_id: Optional[str] = None
    task_title: str
    task_description: Optional[str] = ""
    due_date: Optional[str] = None
    priority: TaskPriority = "Medium"
    status: TaskStatus = "Open"
    created_from_ai: bool = False
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    completed_at: Optional[str] = None


# ---------- AUDIT ----------
class AuditLog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    user_id: str
    user_email: str
    action_type: str  # create/update/delete/view_sensitive/export/login/logout
    entity_type: str  # user/team/doctor/visit/task
    entity_id: Optional[str] = None
    timestamp: str = Field(default_factory=_now_iso)
    previous_value: Optional[dict] = None
    new_value: Optional[dict] = None
    ip: Optional[str] = None
