import React from "react";
import { Link, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  LayoutDashboard,
  Users,
  ClipboardList,
  CheckSquare,
  Search,
  Settings,
  LogOut,
  Plus,
  Brain,
  FileText,
} from "lucide-react";
import { Button } from "./ui/button";

const TABS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/doctors", label: "Doctors", icon: Users, testId: "nav-doctors" },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, testId: "nav-tasks" },
  { to: "/reports", label: "Reports", icon: FileText, testId: "nav-reports" },
  { to: "/search", label: "Search", icon: Search, testId: "nav-search" },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const showFab = !location.pathname.startsWith("/log-visit");

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
            {TABS.map((t) => (
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

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 bottom-nav border-t" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <div className="grid grid-cols-6 h-16">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
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
          ))}
          <button
            onClick={() => navigate("/log-visit")}
            data-testid="mobile-log-visit-btn"
            className="flex flex-col items-center justify-center gap-1 text-[10px] text-[var(--brand-secondary)] font-semibold"
          >
            <Plus className="w-5 h-5" />
            Log
          </button>
        </div>
      </nav>

      {/* Floating Log Visit FAB (desktop only) */}
      {showFab && (
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
