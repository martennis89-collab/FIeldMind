import {
  CalendarPlus,
  Calendar,
  LayoutDashboard,
  Users,
  ClipboardList,
  CheckSquare,
  FileText,
  AlertOctagon,
  TrendingUp,
  ScanLine,
  Smile,
  Receipt,
  Layers,
  UserRound,
} from "lucide-react";

// ---------- Desktop top nav (header) ----------
export const TM_TOP = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "nav-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "nav-invisalign" },
  { to: "/doctors", label: "Doctors", icon: Users, testId: "nav-doctors" },
  { to: "/meetings", label: "Meetings", icon: Calendar, testId: "nav-meetings" },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, testId: "nav-tasks" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "nav-expenses" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "nav-reports" },
];

export const MANAGER_TOP = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/intervention", label: "Intervention", icon: AlertOctagon, testId: "nav-intervention" },
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "nav-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "nav-invisalign" },
  { to: "/team-performance", label: "Team", icon: TrendingUp, testId: "nav-team-performance" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "nav-expenses" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "nav-reports" },
];

// Phase L — Senior TM is a TM + Manager hybrid. Desktop top nav is the
// FULL union: every TM item (Doctors / Meetings / Tasks) PLUS every Manager
// item (Intervention / Team). This is wider than either base nav by design
// — Senior TMs need to act AS a TM (logging) and AS a Manager (oversight)
// without switching accounts.
export const SENIORTM_TOP = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/intervention", label: "Intervention", icon: AlertOctagon, testId: "nav-intervention" },
  { to: "/doctors", label: "Doctors", icon: Users, testId: "nav-doctors" },
  { to: "/meetings", label: "Meetings", icon: Calendar, testId: "nav-meetings" },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, testId: "nav-tasks" },
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "nav-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "nav-invisalign" },
  { to: "/team-performance", label: "Team", icon: TrendingUp, testId: "nav-team-performance" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "nav-expenses" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "nav-reports" },
];

// Phase L.3 — Desktop top-nav split into primary slots (always visible) and
// overflow (collapsed under a "More ▾" dropdown). Keeps the header focused
// on high-traffic links and prevents wrap on 1024-1280px laptop screens.
//
// Values are { default, lg, xl } counts so the Senior TM nav can expand on
// wide desktops (1440px+) where there's room for the full union of TM +
// Manager links inline. `default` is the minimum used at md (≥768px).
//   - TM:        7 primary at every breakpoint
//   - Manager:   5 primary at every breakpoint
//   - SeniorTM:  6 at md, 8 at lg (≥1280px), 10 at xl (≥1440px) → ALL inline
//   - Owner+Admin: all visible at every breakpoint (no overflow)
export const TOP_PRIMARY_COUNT = {
  TM: { default: 7, lg: 7, xl: 8 },
  Manager: { default: 5, lg: 5, xl: 5 },
  SeniorTM: { default: 6, lg: 8, xl: 10 },
  Admin: { default: 99, lg: 99, xl: 99 },
  Owner: { default: 99, lg: 99, xl: 99 },
};

// ---------- Mobile bottom nav (max 5 slots) ----------
// TM: Home / Doctors / + / Tasks / More
export const TM_BOTTOM = [
  { to: "/", label: "Home", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/doctors", label: "Doctors", icon: Users, testId: "nav-doctors" },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, testId: "nav-tasks" },
];

export const TM_MORE = [
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "more-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "more-invisalign" },
  { to: "/meetings", label: "Meetings", icon: Calendar, testId: "more-meetings" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "more-reports" },
  { to: "/reimbursement", label: "Reimbursement", icon: FileText, testId: "more-reimbursement" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "more-expenses" },
  { to: "/account", label: "My account", icon: UserRound, testId: "more-account" },
];

// Manager: Dashboard / Intervention / iTero / Invisalign / More
export const MANAGER_BOTTOM = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/intervention", label: "Intervention", icon: AlertOctagon, testId: "nav-intervention" },
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "nav-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "nav-invisalign" },
];

export const MANAGER_MORE = [
  { to: "/team-performance", label: "Team performance", icon: TrendingUp, testId: "more-team" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "more-reports" },
  { to: "/reimbursement", label: "Reimbursement", icon: FileText, testId: "more-reimbursement" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "more-expenses" },
  { to: "/account", label: "My account", icon: UserRound, testId: "more-account" },
];

// Phase L — Senior TM is a TM + Manager hybrid. They log their own visits
// (TM functionality) AND oversee a sub-team (Manager functionality). Their
// bottom nav prioritises oversight + adding, with iTero/Invisalign/Team perf
// available via the More sheet.
//
// Slots: Dashboard / Intervention / + Add / Tasks / More
export const SENIORTM_BOTTOM = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/intervention", label: "Intervention", icon: AlertOctagon, testId: "nav-intervention" },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, testId: "nav-tasks" },
];

export const SENIORTM_MORE = [
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "more-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "more-invisalign" },
  { to: "/team-performance", label: "Team performance", icon: TrendingUp, testId: "more-team" },
  { to: "/doctors", label: "Doctors", icon: Users, testId: "more-doctors" },
  { to: "/meetings", label: "Meetings", icon: Calendar, testId: "more-meetings" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "more-reports" },
  { to: "/reimbursement", label: "Reimbursement", icon: FileText, testId: "more-reimbursement" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "more-expenses" },
  { to: "/account", label: "My account", icon: UserRound, testId: "more-account" },
];

// ---------- Shared "+ Add" sheet (TM + SeniorTM) ----------
// Each item: { icon, label, to, testId, subtitle? }
export const ADD_SHEET_ITEMS = [
  { icon: ClipboardList, label: "Log a visit", to: "/log-visit", testId: "add-log-visit" },
  { icon: CalendarPlus, label: "Book a meeting", to: "/meetings/book", testId: "add-book-meeting" },
  { icon: ScanLine, label: "Book an iTero demo", to: "/meetings/book?demo=1", testId: "add-book-demo", subtitle: "Auto-marks pipeline as Demo Booked" },
  { icon: Calendar, label: "Add an event", to: "/meetings?new_event=1", testId: "add-event", subtitle: "Generic agenda item, no doctor" },
  { icon: CheckSquare, label: "New task", to: "/tasks?new=1", testId: "add-new-task" },
  { icon: Receipt, label: "Add an expense", to: "/expenses/log", testId: "add-expense" },
  { icon: Users, label: "Add a doctor", to: "/doctors/add", testId: "add-doctor" },
  { icon: Layers, label: "Import doctors", to: "/doctors/import", testId: "add-doctor-import", subtitle: "From a spreadsheet" },
];
