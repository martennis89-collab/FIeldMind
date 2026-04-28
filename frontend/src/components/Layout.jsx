import React, { useState } from "react";
import { Link, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  LayoutDashboard,
  Users,
  ClipboardList,
  CheckSquare,
  LogOut,
  Plus,
  Brain,
  FileText,
  AlertOctagon,
  TrendingUp,
  ScanLine,
  Smile,
  Receipt,
  Settings,
  MoreHorizontal,
  X,
  Layers,
} from "lucide-react";
import { Button } from "./ui/button";

// ---------- Top-level (header) ----------
const TM_TOP = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "nav-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "nav-invisalign" },
  { to: "/doctors", label: "Doctors", icon: Users, testId: "nav-doctors" },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, testId: "nav-tasks" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "nav-expenses" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "nav-reports" },
];
const MANAGER_TOP = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/intervention", label: "Intervention", icon: AlertOctagon, testId: "nav-intervention" },
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "nav-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "nav-invisalign" },
  { to: "/team-performance", label: "Team", icon: TrendingUp, testId: "nav-team-performance" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "nav-expenses" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "nav-reports" },
];

// ---------- Mobile bottom (max 5) ----------
// TM: Home / Doctors / + / Tasks / iTero (the last slot intentionally cycles iTero – Invisalign via long-press? keep simple: iTero)
const TM_BOTTOM = [
  { to: "/", label: "Home", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/doctors", label: "Doctors", icon: Users, testId: "nav-doctors" },
  // central "+ Add" injected at this slot
  { to: "/tasks", label: "Tasks", icon: CheckSquare, testId: "nav-tasks" },
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "nav-itero" },
];

// Manager: Dashboard / Intervention / iTero / Invisalign / More
const MANAGER_BOTTOM = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/intervention", label: "Intervention", icon: AlertOctagon, testId: "nav-intervention" },
  { to: "/itero", label: "iTero", icon: ScanLine, testId: "nav-itero" },
  { to: "/invisalign", label: "Invisalign", icon: Smile, testId: "nav-invisalign" },
  // central "More" sheet injected at this slot
];

const MANAGER_MORE = [
  { to: "/team-performance", label: "Team performance", icon: TrendingUp, testId: "more-team" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "more-reports" },
  { to: "/expenses", label: "Expenses", icon: Receipt, testId: "more-expenses" },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isManager = user?.role === "Manager";
  const isTM = user?.role === "TM";
  const TOP = isManager ? MANAGER_TOP : TM_TOP;
  const [tmAddOpen, setTmAddOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-default)" }}>
      {/* Top bar */}
      <header className="sticky top-0 z-30 border-b" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2" data-testid="brand-link">
            <div className="w-9 h-9 rounded-md flex items-center justify-center" style={{ background: "var(--brand-primary)" }}>
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div className="leading-tight">
              <div className="font-display text-lg font-semibold" style={{ color: "var(--brand-primary)" }}>FieldMind</div>
              <div className="text-[10px] uppercase tracking-[0.2em]" style={{ color: "var(--text-muted)" }}>Field Intelligence</div>
            </div>
          </Link>
          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-1">
            {TOP.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.to === "/"}
                data-testid={t.testId}
                className={({ isActive }) =>
                  `px-3 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-all duration-200 ${
                    isActive ? "bg-[var(--bg-muted)] text-[var(--brand-primary)]" : "text-[var(--text-secondary)] hover:bg-[var(--bg-paper)]"
                  }`
                }
              >
                <t.icon className="w-4 h-4" />
                {t.label}
              </NavLink>
            ))}
            {user?.role === "Admin" && (
              <NavLink
                to="/admin"
                data-testid="nav-admin"
                className={({ isActive }) =>
                  `px-3 py-2 rounded-md text-sm font-medium flex items-center gap-2 ${
                    isActive ? "bg-[var(--bg-muted)] text-[var(--brand-primary)]" : "text-[var(--text-secondary)] hover:bg-[var(--bg-paper)]"
                  }`
                }
              >
                <Settings className="w-4 h-4" />
                Admin
              </NavLink>
            )}
          </nav>
          <div className="flex items-center gap-3">
            <div className="hidden sm:block text-right leading-tight">
              <div className="text-sm font-medium" data-testid="current-user-name">{user?.full_name}</div>
              <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{user?.role}</div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => { await logout(); navigate("/login"); }}
              data-testid="logout-btn"
              className="text-[var(--text-secondary)]"
            >
              <LogOut className="w-4 h-4 mr-1" />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-6 pb-28 md:pb-10">{children}</main>

      {/* Mobile bottom nav (TM = 5 slots with central + Add; Manager = 5 slots with More sheet) */}
      {isTM && (
        <>
          <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 bottom-nav border-t" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="mobile-bottom-nav-tm">
            <div className="grid grid-cols-5 h-16">
              {/* slot 1, 2 */}
              {TM_BOTTOM.slice(0, 2).map((t) => <BottomTab key={t.to} t={t} />)}
              {/* slot 3 — central + Add */}
              <button
                onClick={() => setTmAddOpen(true)}
                data-testid="mobile-add-btn"
                className="flex flex-col items-center justify-center -mt-5"
                aria-label="Add"
              >
                <span className="w-12 h-12 rounded-full flex items-center justify-center text-white shadow-lg"
                      style={{ background: "var(--brand-secondary)" }}>
                  <Plus className="w-6 h-6" />
                </span>
                <span className="text-[10px] mt-1" style={{ color: "var(--brand-secondary)", fontWeight: 600 }}>Add</span>
              </button>
              {/* slot 4, 5 */}
              {TM_BOTTOM.slice(2, 4).map((t) => <BottomTab key={t.to} t={t} />)}
            </div>
          </nav>
          {/* + Add bottom sheet (TM) */}
          {tmAddOpen && (
            <BottomSheet onClose={() => setTmAddOpen(false)} testId="tm-add-sheet">
              <SheetTitle>Add</SheetTitle>
              <SheetItem icon={ClipboardList} label="Log a visit" onClick={() => { setTmAddOpen(false); navigate("/log-visit"); }} testId="add-log-visit" />
              <SheetItem icon={Receipt} label="Add an expense" onClick={() => { setTmAddOpen(false); navigate("/expenses/log"); }} testId="add-expense" />
              <SheetItem icon={Users} label="Add a doctor" onClick={() => { setTmAddOpen(false); navigate("/doctors/import"); }} testId="add-doctor" subtitle="Import from spreadsheet" />
            </BottomSheet>
          )}
        </>
      )}

      {isManager && (
        <>
          <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 bottom-nav border-t" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="mobile-bottom-nav-manager">
            <div className="grid grid-cols-5 h-16">
              {MANAGER_BOTTOM.map((t) => <BottomTab key={t.to} t={t} />)}
              <button
                onClick={() => setMoreOpen(true)}
                data-testid="mobile-more-btn"
                className="flex flex-col items-center justify-center gap-1 text-[10px]"
                style={{ color: moreOpen ? "var(--brand-primary)" : "var(--text-muted)" }}
              >
                <MoreHorizontal className="w-5 h-5" />
                More
              </button>
            </div>
          </nav>
          {moreOpen && (
            <BottomSheet onClose={() => setMoreOpen(false)} testId="manager-more-sheet">
              <SheetTitle>More</SheetTitle>
              {MANAGER_MORE.map((m) => (
                <SheetItem key={m.to} icon={m.icon} label={m.label} testId={m.testId} onClick={() => { setMoreOpen(false); navigate(m.to); }} />
              ))}
            </BottomSheet>
          )}
        </>
      )}

      {/* Admin: full top nav, no bottom nav (desktop-first) */}
      {!isTM && !isManager && (
        <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 bottom-nav border-t" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="grid grid-cols-3 h-16">
            <BottomTab t={{ to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" }} />
            <BottomTab t={{ to: "/admin", label: "Admin", icon: Settings, testId: "nav-admin" }} />
            <BottomTab t={{ to: "/reports", label: "Reports", icon: FileText, testId: "nav-reports" }} />
          </div>
        </nav>
      )}

      {/* Desktop FAB (TM only) */}
      {isTM && !location.pathname.startsWith("/log-visit") && (
        <button
          onClick={() => navigate("/log-visit")}
          data-testid="log-visit-fab"
          className="hidden md:flex fab-pulse fixed bottom-8 right-8 z-30 items-center gap-2 px-5 py-3 rounded-full text-white font-medium shadow-lg transition-all hover:opacity-95"
          style={{ background: "var(--brand-secondary)" }}
        >
          <ClipboardList className="w-4 h-4" />
          Log Visit
        </button>
      )}
    </div>
  );
}

function BottomTab({ t }) {
  return (
    <NavLink
      to={t.to}
      end={t.to === "/"}
      data-testid={`mobile-${t.testId}`}
      className={({ isActive }) =>
        `flex flex-col items-center justify-center gap-1 text-[10px] ${
          isActive ? "text-[var(--brand-primary)]" : "text-[var(--text-muted)]"
        }`
      }
    >
      <t.icon className="w-5 h-5" />
      {t.label}
    </NavLink>
  );
}

function BottomSheet({ children, onClose, testId }) {
  return (
    <div className="md:hidden fixed inset-0 z-50 flex items-end" data-testid={testId}>
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full bg-white rounded-t-2xl shadow-2xl pb-6 pt-3 px-1 animate-in slide-in-from-bottom" style={{ background: "var(--bg-default)" }}>
        <div className="flex justify-center mb-2"><span className="w-10 h-1.5 rounded-full" style={{ background: "var(--border-default)" }} /></div>
        <button onClick={onClose} className="absolute top-3 right-3 p-1.5 rounded-full hover:bg-[var(--bg-paper)]" data-testid="sheet-close"><X className="w-4 h-4" /></button>
        <div>{children}</div>
      </div>
    </div>
  );
}
function SheetTitle({ children }) {
  return <div className="px-4 pb-2 pt-1 text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{children}</div>;
}
function SheetItem({ icon: Icon, label, subtitle, onClick, testId }) {
  return (
    <button onClick={onClick} data-testid={testId} className="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-paper)] active:bg-[var(--bg-muted)] text-left">
      <span className="w-9 h-9 rounded-md flex items-center justify-center" style={{ background: "var(--bg-paper)" }}>
        <Icon className="w-4 h-4" style={{ color: "var(--brand-primary)" }} />
      </span>
      <div className="flex-1">
        <div className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{label}</div>
        {subtitle && <div className="text-xs" style={{ color: "var(--text-muted)" }}>{subtitle}</div>}
      </div>
    </button>
  );
}
