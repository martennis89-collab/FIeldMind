"""Pydantic models for Field Intelligence Platform."""
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime, timezone
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# PHASE C — COMPANY (multi-tenant root entity)
# ============================================================
TeamSizeCategory = Literal["1-5", "6-15", "16-50", "51-100", "101+"]
SalesMotion = Literal[
    "field sales",
    "medical device sales",
    "pharma field team",
    "dental/orthodontic field team",
    "B2B distribution",
    "equipment sales",
    "other",
]
CompanyStatus = Literal["Active", "Inactive"]


class CompanyCreate(BaseModel):
    company_name: str
    slug: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    market: Optional[str] = None
    region: Optional[str] = None
    team_size_category: Optional[TeamSizeCategory] = None
    sales_motion: Optional[SalesMotion] = None
    account_type: Optional[str] = None
    plan: Optional[str] = "internal"
    benchmark_opt_in: bool = False
    active_status: CompanyStatus = "Active"


class CompanyUpdate(BaseModel):
    company_name: Optional[str] = None
    slug: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    market: Optional[str] = None
    region: Optional[str] = None
    team_size_category: Optional[TeamSizeCategory] = None
    sales_motion: Optional[SalesMotion] = None
    account_type: Optional[str] = None
    plan: Optional[str] = None
    benchmark_opt_in: Optional[bool] = None
    active_status: Optional[CompanyStatus] = None


class Company(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_name: str
    slug: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    market: Optional[str] = None
    region: Optional[str] = None
    team_size_category: Optional[TeamSizeCategory] = None
    sales_motion: Optional[SalesMotion] = None
    account_type: Optional[str] = None
    plan: Optional[str] = "internal"
    benchmark_opt_in: bool = False
    active_status: CompanyStatus = "Active"
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


DEFAULT_COMPANY = {
    "company_name": "FieldMind Default Company",
    "slug": "default",
    "industry": "dental/orthodontic field team",
    "country": "Bulgaria",
    "market": "Bulgaria",
    "region": "Bulgaria",
    "team_size_category": "1-5",
    "sales_motion": "dental/orthodontic field team",
    "account_type": "doctors/clinics",
    "plan": "internal",
    "benchmark_opt_in": False,
    "active_status": "Active",
}


# ---------- USERS / TEAMS ----------
Role = Literal["TM", "Manager", "Admin", "Owner"]


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: Role = "TM"
    team_id: Optional[str] = None
    manager_user_id: Optional[str] = None
    region: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[Role] = None
    team_id: Optional[str] = None
    manager_user_id: Optional[str] = None
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
    manager_user_id: Optional[str] = None
    region: Optional[str] = None
    active_status: bool = True
    company_id: Optional[str] = None  # Phase C — multi-tenant root
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
    company_id: Optional[str] = None  # Phase C — multi-tenant root
    team_name: str
    manager_user_id: Optional[str] = None
    region: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------- DOCTORS ----------
Segment = Literal["New", "Lapsed", "Occasional", "Active", "Engaged", "Expert"]
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


IteroStage = Literal[
    "None",
    "Demo Discussed",
    "Demo Booked",
    "Demo Completed",
    "Proposal Sent",
    "Contract Sent",
    "Contract Signed",
    "Lost",
]


# Used to know which stage is "more advanced" (auto-advance only forward).
ITERO_STAGE_RANK = {
    "None": 0,
    "Demo Discussed": 1,
    "Demo Booked": 2,
    "Demo Completed": 3,
    "Proposal Sent": 4,
    "Contract Sent": 5,
    "Contract Signed": 6,
    "Lost": -1,  # terminal but explicit; never auto-advances over Lost
}


class Doctor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
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
    itero_stage: IteroStage = "None"
    itero_stage_updated_at: Optional[str] = None
    itero_stage_updated_by: Optional[str] = None
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


TrackType = Literal["ITERO", "INVISALIGN", "BOTH"]
ConfidenceLevel = Literal["Low", "Medium", "High", "Unknown"]
InterestLevel = Literal["Low", "Medium", "High", "None"]
AffordabilityPerception = Literal["Concerned", "Neutral", "Confident", "Unknown"]


class IteroActions(BaseModel):
    demo_discussed: bool = False
    demo_booked: bool = False
    demo_booked_date: Optional[str] = None
    demo_completed: bool = False
    demo_completed_date: Optional[str] = None
    contract_sent: bool = False
    contract_sent_date: Optional[str] = None
    contract_signed: bool = False
    contract_signed_date: Optional[str] = None
    lost: bool = False
    lost_reason: Optional[str] = None
    scanner_interest_level: InterestLevel = "None"
    scanner_concerns: List[str] = []


class InvisalignActions(BaseModel):
    growth_program_explained: bool = False
    certification_interest: bool = False
    tps_discussed: bool = False
    p2p_suggested: bool = False
    staff_training_needed: bool = False
    clinical_confidence: ConfidenceLevel = "Unknown"
    business_confidence: ConfidenceLevel = "Unknown"
    patient_affordability_perception: AffordabilityPerception = "Unknown"


class CommercialActions(BaseModel):
    """Track-agnostic commercial fields (pricing + proposal). iTero-specific demo
    fields and Invisalign-specific growth fields now live on IteroActions / InvisalignActions."""
    boost_discussed: bool = False
    trade_in_discussed: bool = False
    trade_in_interest: bool = False
    proposal_discussed: bool = False
    proposal_sent: bool = False
    proposal_sent_date: Optional[str] = None
    proposal_follow_up_done: bool = False
    # Deprecated — kept readable for backward compatibility (migration copies them out)
    demo_discussed: bool = False
    demo_booked: bool = False
    demo_booked_date: Optional[str] = None
    demo_completed: bool = False
    demo_completed_date: Optional[str] = None
    growth_program_explained: bool = False


class AIExtraction(BaseModel):
    summary: str = ""
    topics: List[str] = []
    barriers: List[str] = []
    sentiment: Sentiment = "Neutral"
    opportunity_state: OpportunityState = "Unknown"
    promises_detected: List[PromiseDraft] = []
    suggested_next_action: str = ""
    market_signals: List[str] = []
    privacy_warnings: List[str] = []
    track_types: List[TrackType] = []
    itero_actions: IteroActions = IteroActions()
    invisalign_actions: InvisalignActions = InvisalignActions()
    commercial_actions: CommercialActions = CommercialActions()


class AnalyzeNoteRequest(BaseModel):
    note: str
    doctor_id: Optional[str] = None


class VisitCreate(BaseModel):
    doctor_id: str
    visit_date: Optional[str] = None  # ISO datetime
    visit_type: VisitType = "In-person visit"
    track_type: TrackType = "BOTH"
    free_text_note: str = ""
    confirmed_topics: List[str] = []
    confirmed_barriers: List[str] = []
    sentiment: Sentiment = "Neutral"
    opportunity_state: OpportunityState = "Unknown"
    next_step: Optional[str] = None
    promises: List[PromiseDraft] = []
    ai_extraction: Optional[AIExtraction] = None
    itero_actions: IteroActions = IteroActions()
    invisalign_actions: InvisalignActions = InvisalignActions()
    commercial_actions: CommercialActions = CommercialActions()
    meeting_id: Optional[str] = None  # if logged from a booked meeting, marks it Completed


class Visit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
    doctor_id: str
    tm_user_id: str
    team_id: Optional[str] = None
    visit_date: str = Field(default_factory=_now_iso)
    visit_type: VisitType = "In-person visit"
    track_type: TrackType = "BOTH"
    free_text_note: str = ""
    confirmed_topics: List[str] = []
    confirmed_barriers: List[str] = []
    sentiment: Sentiment = "Neutral"
    opportunity_state: OpportunityState = "Unknown"
    next_step: Optional[str] = None
    ai_extraction: Optional[AIExtraction] = None
    itero_actions: IteroActions = IteroActions()
    invisalign_actions: InvisalignActions = InvisalignActions()
    commercial_actions: CommercialActions = CommercialActions()
    # Phase A additions — backward compatible
    is_draft: bool = False
    deleted_at: Optional[str] = None
    company_id: Optional[str] = None  # forward-compat for multi-tenant
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------- TASKS / PROMISES ----------
TaskStatus = Literal["Open", "Completed", "Overdue", "Cancelled"]
TaskPriority = Literal["Low", "Medium", "High"]
# Promise category — controlled vocabulary per spec §3.6.
# Backward-compat: old tasks without a category land in "other".
PromiseCategory = Literal[
    "send material",
    "follow-up call",
    "arrange demo",
    "send proposal",
    "explain program",
    "invite to event",
    "arrange training",
    "connect with expert/P2P",
    "admin/documentation",
    "expense/admin",
    "other",
]


class TaskCreate(BaseModel):
    doctor_id: str
    visit_id: Optional[str] = None
    task_title: str
    task_description: Optional[str] = ""
    due_date: Optional[str] = None  # ISO date
    priority: TaskPriority = "Medium"
    created_from_ai: bool = False
    ai_confirmed: bool = True  # manual creates are implicitly confirmed
    category: PromiseCategory = "other"


class TaskUpdate(BaseModel):
    task_title: Optional[str] = None
    task_description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    doctor_id: Optional[str] = None
    category: Optional[PromiseCategory] = None
    ai_confirmed: Optional[bool] = None


class Task(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
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
    ai_confirmed: bool = True
    category: PromiseCategory = "other"
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    completed_at: Optional[str] = None
    deleted_at: Optional[str] = None  # soft delete


# ---------- AUDIT / EVENT LEDGER ----------
# Phase A: the existing `audit_logs` collection becomes our Event Ledger.
# Named event types are layered on top of the generic CRUD action_types so
# analytics queries can target them precisely (per spec §3.12).
# We keep both `action_type` (legacy) and `event_type` (new, optional)
# to avoid breaking any existing reader code.
EventType = Literal[
    # generic CRUD (compatibility with action_type values)
    "create", "update", "delete", "view_sensitive", "export", "login", "logout",
    # named events (spec §3.12)
    "user_created", "user_deactivated", "user_reactivated",
    "doctor_imported", "doctor_created", "doctor_updated", "doctor_deleted",
    "meeting_logged", "meeting_updated", "meeting_deleted",
    "voice_note_uploaded", "ai_summary_generated", "ai_tags_confirmed",
    "promise_created", "promise_completed", "promise_overdue",
    "promise_updated", "promise_deleted",
    "report_generated", "report_submitted", "report_reviewed", "report_overdue",
    "report_revision_requested", "manager_comment_added",
    "intervention_created", "intervention_completed",
    "intervention_overdue", "intervention_dismissed",
    "expense_created", "expense_submitted", "expense_approved", "expense_rejected", "expense_deleted",
    "itero_demo_discussed", "itero_demo_booked", "itero_demo_completed",
    "itero_proposal_sent", "itero_proposal_followed_up",
    "itero_boost_discussed", "itero_trade_in_discussed",
    "invisalign_growth_program_explained", "invisalign_certification_interest_logged",
    "invisalign_tps_discussed", "invisalign_p2p_suggested",
    "invisalign_staff_training_needed", "invisalign_maob_discussed", "invisalign_ipe_discussed",
    "invisalign_clinical_confidence_barrier_logged",
    "invisalign_business_confidence_barrier_logged",
    "invisalign_patient_affordability_concern_logged",
    "invisalign_case_selection_concern_logged",
    "track_signal_created", "clinical_pattern_created",
]


class AuditLog(BaseModel):
    """Append-only Activity Event Ledger. Stored in `audit_logs` collection (kept
    for backward compatibility — the collection IS the event ledger)."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    user_id: str
    user_email: str
    action_type: str  # legacy generic verb
    event_type: Optional[str] = None  # spec §3.12 named event when applicable
    entity_type: str  # user/team/doctor/visit/task/meeting/track_signal/...
    entity_id: Optional[str] = None
    track_type: Optional[str] = None  # General / iTero / Invisalign / Both
    timestamp: str = Field(default_factory=_now_iso)
    previous_value: Optional[dict] = None
    new_value: Optional[dict] = None
    ip: Optional[str] = None
    # Idempotency guard — prevents duplicate event_ledger rows for the same logical action.
    idempotency_key: Optional[str] = None
    # Forward-compat: filled in Phase C
    company_id: Optional[str] = None
    team_id: Optional[str] = None



# ---------- WEEKLY REPORTS ----------
ReportStatus = Literal["Draft", "Submitted", "Reviewed"]


class ReportContent(BaseModel):
    visits_completed: int = 0
    doctors_visited: int = 0
    topics_discussed: List[str] = []
    barriers_heard: List[str] = []
    promises_created: int = 0
    promises_completed: int = 0
    overdue_promises: int = 0
    sentiment_summary: dict = {}
    key_insights: List[str] = []
    doctors_needing_attention: List[dict] = []
    doctor_breakdown: List[dict] = []  # per-doctor visit summary for the week
    notes_from_tm: str = ""
    demos_discussed: int = 0
    demos_booked: int = 0
    demos_completed: int = 0
    proposals_sent: int = 0
    proposals_followed_up: int = 0


class ReportComment(BaseModel):
    id: str = Field(default_factory=_uuid)
    user_id: str
    user_name: str
    text: str
    created_at: str = Field(default_factory=_now_iso)


class ReportCreate(BaseModel):
    week_start: str  # ISO date Monday
    week_end: str  # ISO date Sunday
    auto_summary: str = ""
    content: ReportContent
    notes_from_tm: str = ""


class ReportUpdate(BaseModel):
    auto_summary: Optional[str] = None
    content: Optional[ReportContent] = None
    notes_from_tm: Optional[str] = None


class WeeklyReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
    tm_user_id: str
    tm_name: str = ""
    team_id: Optional[str] = None
    week_start: str
    week_end: str
    status: ReportStatus = "Draft"
    auto_summary: str = ""
    content: ReportContent = ReportContent()
    notes_from_tm: str = ""
    submitted_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    comments: List[ReportComment] = []
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)



# ---------- EXPENSES ----------
ExpenseCategory = Literal["Petrol", "Food"]
ExpenseStatus = Literal["Draft", "Submitted"]


class ExpenseUpdate(BaseModel):
    expense_date: Optional[str] = None
    category: Optional[ExpenseCategory] = None
    amount: Optional[float] = None
    vendor: Optional[str] = None
    notes: Optional[str] = None


class Expense(BaseModel):
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
    tm_user_id: str
    tm_name: str = ""
    team_id: Optional[str] = None
    expense_date: str
    submission_month: Optional[str] = None  # YYYY-MM (set on Submit)
    category: ExpenseCategory
    amount: float
    currency: str = "EUR"
    vendor: Optional[str] = None
    notes: Optional[str] = None
    receipt_image_id: Optional[str] = None
    receipt_mime: Optional[str] = None
    receipt_hash: Optional[str] = None
    ocr: Optional[dict] = None
    status: ExpenseStatus = "Draft"
    submitted_at: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)



# ---------- MEETINGS ----------
MeetingStatus = Literal["Scheduled", "Completed", "Cancelled"]


class MeetingCreate(BaseModel):
    doctor_id: str
    scheduled_at: str  # ISO datetime
    duration_minutes: int = 30
    subject: Optional[str] = None
    is_demo: bool = False  # marks this meeting as an iTero demo


class MeetingUpdate(BaseModel):
    scheduled_at: Optional[str] = None
    duration_minutes: Optional[int] = None
    subject: Optional[str] = None
    status: Optional[MeetingStatus] = None
    is_demo: Optional[bool] = None


class Meeting(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
    doctor_id: str
    doctor_name: str = ""
    clinic_name: Optional[str] = None
    city: Optional[str] = None
    tm_user_id: str
    tm_name: str = ""
    team_id: Optional[str] = None
    scheduled_at: str
    duration_minutes: int = 30
    subject: Optional[str] = None
    is_demo: bool = False
    status: MeetingStatus = "Scheduled"
    visit_id: Optional[str] = None
    # Phase A additions — backward-compatible
    track_type: Literal["General", "iTero", "Invisalign", "Both"] = "General"
    is_draft: bool = False
    deleted_at: Optional[str] = None
    # Forward-compat for multi-tenant (filled in Phase C)
    company_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)



# ---------- EVENTS (generic calendar items, not tied to a doctor) ----------
EventStatus = Literal["Scheduled", "Done", "Cancelled"]


class EventCreate(BaseModel):
    title: str
    scheduled_at: str  # start ISO datetime
    ends_at: Optional[str] = None  # end ISO datetime; if absent, derived from duration_minutes
    duration_minutes: int = 60
    location: Optional[str] = None
    notes: Optional[str] = None


class EventUpdate(BaseModel):
    title: Optional[str] = None
    scheduled_at: Optional[str] = None
    ends_at: Optional[str] = None
    duration_minutes: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[EventStatus] = None


class Event(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
    title: str
    tm_user_id: str
    tm_name: str = ""
    team_id: Optional[str] = None
    scheduled_at: str
    ends_at: Optional[str] = None
    duration_minutes: int = 60
    location: Optional[str] = None
    notes: Optional[str] = None
    status: EventStatus = "Scheduled"
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------- ITERO PIPELINE ----------
class IteroStageUpdate(BaseModel):
    stage: IteroStage
    note: Optional[str] = None



# ============================================================
# PHASE B — TRACK SIGNAL (first-class structured iTero/Invisalign signal)
# ============================================================
TrackSignalTrack = Literal["iTero", "Invisalign"]
TrackSignalSource = Literal["Manual", "AI Suggested", "AI Confirmed"]

# Controlled vocabulary — extend cautiously, analytics depend on these strings.
# (iTero side)
ITERO_SIGNAL_TYPES = (
    "demo_discussed", "demo_booked", "demo_completed",
    "proposal_sent", "proposal_followed_up",
    "boost_discussed", "trade_in_discussed", "trade_in_interest",
    "scanner_concern", "scanner_interest_level",
    "itero_value_discussed", "face_scan_discussed",
)
# (Invisalign side)
INVISALIGN_SIGNAL_TYPES = (
    "growth_program_explained", "growth_program_not_understood",
    "certification_interest",
    "tps_discussed", "p2p_suggested",
    "staff_training_needed",
    "clinical_confidence_barrier", "business_confidence_barrier",
    "patient_affordability_concern", "case_selection_concern",
    "clincheck_understanding",
    "smileview_smilevideo_discussed", "teen_confidence_cover_discussed",
    "docloc_benefits_discussed",
    "invited_to_event",
    "marketing_support_discussed", "lead_generation_concern",
    "time_constraint",
    "competition_braces", "competition_other_aligners",
    "extraction_case_concern", "retained_teeth_concern",
    "maob_discussed", "maob_interest",
    "ipe_discussed", "ipe_interest",
)


class TrackSignalCreate(BaseModel):
    doctor_id: str
    meeting_id: Optional[str] = None  # links to a visit_id or meeting_id where applicable
    track_type: TrackSignalTrack
    signal_type: str  # validated against {iTero|Invisalign}_SIGNAL_TYPES in router
    signal_value: Optional[str] = None
    signal_status: Optional[str] = None
    signal_date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    source: TrackSignalSource = "Manual"


class TrackSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
    doctor_id: str
    tm_user_id: str
    team_id: Optional[str] = None
    meeting_id: Optional[str] = None  # may be visit_id or calendar meeting_id
    track_type: TrackSignalTrack
    signal_type: str
    signal_value: Optional[str] = None
    signal_status: Optional[str] = None
    signal_date: str
    source: TrackSignalSource = "Manual"
    # Forward-compat: filled in Phase C
    company_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    deleted_at: Optional[str] = None  # soft delete


# ============================================================
# PHASE B — CLINICAL PATTERN (doctor-level conversation intelligence)
# ============================================================
CaseType = Literal[
    "Class I", "Class II", "Class III",
    "Skeletal discrepancy", "Mixed complex", "Unknown",
]
TreatmentPreference = Literal[
    "Prefers aligners", "Prefers braces", "Hybrid approach",
    "Refers out", "Avoids complex cases", "Unknown",
]
TreatmentStrategy = Literal[
    "Extraction-based", "Non-extraction", "Expansion",
    "Functional-MAOB", "Surgical referral", "Unknown",
]
ConfidenceLevel = Literal["Low", "Medium", "High", "Unknown"]
BarrierType = Literal[
    "Does not trust aligners", "Lack of experience",
    "Does not know protocols", "Case selection confusion",
    "None", "Unknown",
]
ClinicalPatternSource = Literal["Manual", "AI Suggested", "AI Confirmed"]


class ClinicalPatternCreate(BaseModel):
    doctor_id: str
    meeting_id: Optional[str] = None
    case_type: CaseType = "Unknown"
    treatment_preference: TreatmentPreference = "Unknown"
    treatment_strategy: TreatmentStrategy = "Unknown"
    confidence_level: ConfidenceLevel = "Unknown"
    barrier_type: BarrierType = "Unknown"
    source: ClinicalPatternSource = "Manual"


class ClinicalPattern(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    company_id: Optional[str] = None  # Phase C — multi-tenant root
    doctor_id: str
    tm_user_id: str
    team_id: Optional[str] = None
    meeting_id: Optional[str] = None
    case_type: CaseType = "Unknown"
    treatment_preference: TreatmentPreference = "Unknown"
    treatment_strategy: TreatmentStrategy = "Unknown"
    confidence_level: ConfidenceLevel = "Unknown"
    barrier_type: BarrierType = "Unknown"
    source: ClinicalPatternSource = "Manual"
    # Forward-compat: filled in Phase C
    company_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    deleted_at: Optional[str] = None
