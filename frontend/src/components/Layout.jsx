import React, { useState } from "react";
import { Link, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  LogOut,
  Plus,
  Brain,
  FileText,
  LayoutDashboard,
  Settings,
  MoreHorizontal,
  X,
  UserRound,
  Wand2,
  ClipboardList,
} from "lucide-react";
import { Button } from "./ui/button";
import QuickCaptureDialog from "./QuickCaptureDialog";
import ErrorBoundary from "./ErrorBoundary";
import {
  TM_TOP,
  MANAGER_TOP,
  SENIORTM_TOP,
  TOP_PRIMARY_COUNT,
  TM_BOTTOM,
  TM_MORE,
  MANAGER_BOTTOM,
  MANAGER_MORE,
  SENIORTM_BOTTOM,
  SENIORTM_MORE,
  ADD_SHEET_ITEMS,
} from "./navConfig";

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  // Top-nav routing splits roles into three lanes:
  //   - Plain TM           -> TM_TOP
  //   - SeniorTM (hybrid)  -> SENIORTM_TOP (full union of TM + Manager items)
  //   - Manager / Admin / Owner -> MANAGER_TOP
  // We keep `isManager` separate from `isSeniorTM` because SeniorTM also needs
  // TM-only behaviour (the central "+ Add" button on mobile).
  const isManager = user?.role === "Manager" || user?.role === "Admin" || user?.role === "Owner";
  const isSeniorTM = user?.role === "SeniorTM";
  const isTM = user?.role === "TM";
  const TOP = isSeniorTM ? SENIORTM_TOP : (isManager ? MANAGER_TOP : TM_TOP);
  // The floating Log Visit button (below) only renders for TM/SeniorTM off the
  // log-visit page — give main content enough bottom clearance to not sit
  // under it at md+ widths (mobile already gets pb-28 from the bottom nav).
  const hasFab = (isTM || isSeniorTM) && !location.pathname.startsWith("/log-visit");
  const [addOpen, setAddOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [quickCaptureOpen, setQuickCaptureOpen] = useState(false);

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
          {/* Desktop nav — primary slots inline, overflow under "More ▾". */}
          <DesktopTopNav top={TOP} role={user?.role} />
          {(user?.role === "Admin" || user?.role === "Owner") && (
            <NavLink
              to="/admin"
              data-testid="nav-admin"
              className={({ isActive }) =>
                `hidden md:inline-flex px-3 py-2 rounded-md text-sm font-medium items-center gap-2 ${
                  isActive ? "bg-[var(--bg-muted)] text-[var(--brand-primary)]" : "text-[var(--text-secondary)] hover:bg-[var(--bg-paper)]"
                }`
              }
            >
              <Settings className="w-4 h-4" />
              Admin
            </NavLink>
          )}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setQuickCaptureOpen(true)}
              data-testid="header-quick-capture"
              className="p-2 rounded-md hover:bg-[var(--bg-paper)] transition-colors flex items-center justify-center"
              title="Quick capture (voice note → AI task)"
              aria-label="Quick capture"
              style={{ color: "var(--brand-primary)" }}
            >
              <Wand2 className="w-[18px] h-[18px]" />
            </button>
            <Link
              to="/account"
              data-testid="nav-account"
              className="hidden lg:block text-right leading-tight px-2 py-1 rounded hover:bg-[var(--bg-paper)] transition-colors whitespace-nowrap"
              title="My account"
            >
              <div className="text-sm font-medium" data-testid="current-user-name">{user?.full_name}</div>
              <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{user?.role} · My account</div>
            </Link>
            <Link
              to="/account"
              data-testid="nav-account-mobile"
              className="lg:hidden p-2 rounded hover:bg-[var(--bg-paper)] transition-colors"
              title="My account"
              aria-label="My account"
            >
              <UserRound className="w-5 h-5" style={{ color: "var(--text-secondary)" }} />
            </Link>
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

      <main className={`flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-6 pb-28 ${hasFab ? "md:pb-28" : "md:pb-10"}`}>
        <ErrorBoundary
          key={location.pathname}
          label="This page hit an unexpected rendering error."
        >
          {children}
        </ErrorBoundary>
      </main>

      {/* Mobile bottom nav — TM + SeniorTM share the "central + Add" pattern,
          Manager has 4 slots + More (no Add). Admin/Owner get a tiny 3-slot nav. */}
      {isTM && (
        <MobileNavWithAdd
          variant="tm"
          slots={TM_BOTTOM}
          moreItems={TM_MORE}
          addOpen={addOpen}
          setAddOpen={setAddOpen}
          moreOpen={moreOpen}
          setMoreOpen={setMoreOpen}
          setQuickCaptureOpen={setQuickCaptureOpen}
          navigate={navigate}
        />
      )}
      {isSeniorTM && (
        <MobileNavWithAdd
          variant="seniortm"
          slots={SENIORTM_BOTTOM}
          moreItems={SENIORTM_MORE}
          addOpen={addOpen}
          setAddOpen={setAddOpen}
          moreOpen={moreOpen}
          setMoreOpen={setMoreOpen}
          setQuickCaptureOpen={setQuickCaptureOpen}
          navigate={navigate}
        />
      )}
      {isManager && (
        <ManagerMobileNav
          moreOpen={moreOpen}
          setMoreOpen={setMoreOpen}
          setQuickCaptureOpen={setQuickCaptureOpen}
          navigate={navigate}
        />
      )}

      {/* Admin/Owner without manager flag (defensive — covers any future role): tiny 3-slot bottom nav. */}
      {!isTM && !isManager && !isSeniorTM && (
        <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 bottom-nav border-t" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="grid grid-cols-3 h-16">
            <BottomTab t={{ to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" }} />
            <BottomTab t={{ to: "/admin", label: "Admin", icon: Settings, testId: "nav-admin" }} />
            <BottomTab t={{ to: "/reports", label: "Reports", icon: FileText, testId: "nav-reports" }} />
          </div>
        </nav>
      )}

      {/* Desktop FAB (TM + Senior TM) */}
      {hasFab && (
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

      <QuickCaptureDialog
        open={quickCaptureOpen}
        onClose={() => setQuickCaptureOpen(false)}
        onCreated={() => setQuickCaptureOpen(false)}
      />
    </div>
  );
}

// ---------- Mobile nav variants ----------

// Used by TM and SeniorTM — 5 slots: 2 nav + central "+ Add" + 1 nav + More.
function MobileNavWithAdd({ variant, slots, moreItems, addOpen, setAddOpen, moreOpen, setMoreOpen, setQuickCaptureOpen, navigate }) {
  return (
    <>
      <nav
        className="md:hidden fixed bottom-0 inset-x-0 z-40 bottom-nav border-t"
        style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
        data-testid={`mobile-bottom-nav-${variant}`}
      >
        <div className="grid grid-cols-5 h-16">
          {/* slots 1, 2 */}
          {slots.slice(0, 2).map((t) => <BottomTab key={t.to} t={t} />)}
          {/* slot 3 — central + Add */}
          <button
            onClick={() => setAddOpen(true)}
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
          {/* slot 4 */}
          {slots.slice(2, 3).map((t) => <BottomTab key={t.to} t={t} />)}
          {/* slot 5 — More */}
          <button
            onClick={() => setMoreOpen(true)}
            data-testid={`mobile-more-btn-${variant}`}
            className="flex flex-col items-center justify-center gap-1 text-[10px]"
            style={{ color: moreOpen ? "var(--brand-primary)" : "var(--text-muted)" }}
          >
            <MoreHorizontal className="w-5 h-5" />
            More
          </button>
        </div>
      </nav>

      {addOpen && (
        <BottomSheet onClose={() => setAddOpen(false)} testId={`${variant}-add-sheet`}>
          <SheetTitle>Add</SheetTitle>
          {ADD_SHEET_ITEMS.map((item) => (
            <SheetItem
              key={item.testId}
              icon={item.icon}
              label={item.label}
              subtitle={item.subtitle}
              testId={item.testId}
              onClick={() => { setAddOpen(false); navigate(item.to); }}
            />
          ))}
        </BottomSheet>
      )}

      {moreOpen && (
        <BottomSheet onClose={() => setMoreOpen(false)} testId={`${variant}-more-sheet`}>
          <SheetTitle>More</SheetTitle>
          <SheetItem
            icon={Wand2}
            label="Quick capture"
            testId="more-quick-capture"
            onClick={() => { setMoreOpen(false); setQuickCaptureOpen(true); }}
          />
          {moreItems.map((m) => (
            <SheetItem key={m.to} icon={m.icon} label={m.label} testId={m.testId} onClick={() => { setMoreOpen(false); navigate(m.to); }} />
          ))}
        </BottomSheet>
      )}
    </>
  );
}

// Used by Manager/Admin/Owner — 4 nav slots + More (no central + Add).
function ManagerMobileNav({ moreOpen, setMoreOpen, setQuickCaptureOpen, navigate }) {
  return (
    <>
      <nav
        className="md:hidden fixed bottom-0 inset-x-0 z-40 bottom-nav border-t"
        style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
        data-testid="mobile-bottom-nav-manager"
      >
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
          <SheetItem
            icon={Wand2}
            label="Quick capture"
            testId="more-quick-capture"
            onClick={() => { setMoreOpen(false); setQuickCaptureOpen(true); }}
          />
          {MANAGER_MORE.map((m) => (
            <SheetItem key={m.to} icon={m.icon} label={m.label} testId={m.testId} onClick={() => { setMoreOpen(false); navigate(m.to); }} />
          ))}
        </BottomSheet>
      )}
    </>
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

// Phase L.3 — Desktop top nav with viewport-aware primary count + "More ▾"
// dropdown for overflow. Buckets: sm=768-1023 (tablet, where the mobile
// bottom nav has already handed off to this desktop nav at Tailwind's
// md=768px), default=1024-1279 (small laptop), lg=1280-1439, xl=1440+.
// This keeps the SeniorTM full union of links inline on 1440px+ screens
// while keeping the header from overflowing on a tablet.
function useTopPrimaryCount(role) {
  const counts = TOP_PRIMARY_COUNT[role] || TOP_PRIMARY_COUNT.TM;
  const computeBreakpoint = () => {
    if (typeof window === "undefined") return "default";
    const w = window.innerWidth;
    if (w >= 1440) return "xl";
    if (w >= 1280) return "lg";
    if (w >= 1024) return "default";
    return "sm";
  };
  const [bp, setBp] = React.useState(computeBreakpoint);
  React.useEffect(() => {
    if (typeof window === "undefined") return undefined;
    let frame;
    const onResize = () => {
      // rAF coalescing — resize fires many times mid-drag.
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setBp(computeBreakpoint()));
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return counts[bp] ?? counts.default ?? 99;
}

function DesktopTopNav({ top, role }) {
  const [open, setOpen] = useState(false);
  const ref = React.useRef(null);
  const primaryCount = useTopPrimaryCount(role);
  const primary = top.slice(0, primaryCount);
  const overflow = top.slice(primaryCount);

  // Click-outside to close. Listen on both mousedown (real user clicks) and
  // click (programmatic clicks from tests) so the menu reliably dismisses.
  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("click", onDoc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("click", onDoc);
    };
  }, [open]);

  return (
    <nav className="hidden md:flex items-center gap-1" data-testid="desktop-top-nav">
      {primary.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.to === "/"}
          data-testid={t.testId}
          className={({ isActive }) =>
            `px-3 py-2 rounded-md text-sm font-medium flex items-center gap-2 transition-all duration-200 ${
              isActive
                ? "bg-[var(--bg-muted)] text-[var(--brand-primary)]"
                : "text-[var(--text-secondary)] hover:bg-[var(--bg-paper)]"
            }`
          }
        >
          <t.icon className="w-4 h-4" />
          {t.label}
        </NavLink>
      ))}
      {overflow.length > 0 && (
        <div className="relative" ref={ref}>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            data-testid="desktop-nav-more-btn"
            aria-expanded={open}
            aria-haspopup="menu"
            className="px-3 py-2 rounded-md text-sm font-medium flex items-center gap-2 text-[var(--text-secondary)] hover:bg-[var(--bg-paper)] transition-all duration-200"
          >
            <MoreHorizontal className="w-4 h-4" />
            More
          </button>
          {open && (
            <div
              role="menu"
              data-testid="desktop-nav-more-menu"
              className="absolute right-0 mt-2 w-56 rounded-md border shadow-lg py-1 z-50"
              style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
            >
              {overflow.map((t) => (
                <NavLink
                  key={t.to}
                  to={t.to}
                  end={t.to === "/"}
                  data-testid={`${t.testId}-overflow`}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-4 py-2 text-sm ${
                      isActive
                        ? "bg-[var(--bg-muted)] text-[var(--brand-primary)] font-medium"
                        : "text-[var(--text-secondary)] hover:bg-[var(--bg-paper)]"
                    }`
                  }
                >
                  <t.icon className="w-4 h-4" />
                  {t.label}
                </NavLink>
              ))}
            </div>
          )}
        </div>
      )}
    </nav>
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
