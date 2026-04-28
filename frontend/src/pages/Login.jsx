import React, { useState } from "react";
import { useAuth } from "../lib/auth";
import { useNavigate, Link } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import api from "../lib/api";
import { Brain, Lock, ShieldCheck } from "lucide-react";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email.trim().toLowerCase(), password);
      toast.success("Welcome back");
      navigate("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  const seed = async () => {
    try {
      const { data } = await api.post("/seed/init");
      if (data.skipped) toast.info("Demo data already present.");
      else toast.success(`Seeded: ${data.created.users} users, ${data.created.doctors} doctors, ${data.created.visits} visits`);
    } catch (err) {
      toast.error("Seed failed");
    }
  };

  const quickFill = (e, p) => {
    setEmail(e); setPassword(p);
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2" style={{ background: "var(--bg-default)" }}>
      {/* Left form */}
      <div className="flex flex-col justify-center px-6 sm:px-12 lg:px-20 py-10">
        <div className="max-w-md w-full mx-auto">
          <div className="flex items-center gap-2 mb-10">
            <div className="w-10 h-10 rounded-md flex items-center justify-center" style={{ background: "var(--brand-primary)" }}>
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="font-display text-xl font-semibold" style={{ color: "var(--brand-primary)" }}>FieldMind</div>
              <div className="text-[11px] uppercase tracking-[0.2em]" style={{ color: "var(--text-muted)" }}>Field Intelligence</div>
            </div>
          </div>

          <h1 className="font-display text-4xl sm:text-5xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Your secure<br />second brain<br /><span className="font-medium">in the field.</span>
          </h1>
          <p className="mt-4 text-base leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            Remember every conversation. Track every promise. Surface the doctors who need attention next.
          </p>

          <form onSubmit={submit} className="mt-10 space-y-5" data-testid="login-form">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@field.io"
                required
                data-testid="login-email-input"
                className="h-11"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                data-testid="login-password-input"
                className="h-11"
              />
            </div>
            <Button
              type="submit"
              disabled={busy}
              data-testid="login-submit-btn"
              className="w-full h-11 font-medium"
              style={{ background: "var(--brand-primary)", color: "white" }}
            >
              <Lock className="w-4 h-4 mr-2" />
              {busy ? "Signing in..." : "Sign in securely"}
            </Button>
          </form>

          <div className="mt-8 p-4 rounded-md border" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
            <div className="flex items-center gap-2 mb-3">
              <ShieldCheck className="w-4 h-4" style={{ color: "var(--brand-primary)" }} />
              <div className="text-sm font-medium" style={{ color: "var(--brand-primary)" }}>Demo accounts</div>
            </div>
            <div className="space-y-1.5 text-sm">
              {[
                ["admin@field.io", "admin123", "Admin"],
                ["manager@field.io", "manager123", "Manager"],
                ["tm1@field.io", "tm123", "Territory Manager"],
                ["tm2@field.io", "tm123", "Territory Manager"],
              ].map(([e, p, r]) => (
                <button
                  key={e}
                  type="button"
                  onClick={() => quickFill(e, p)}
                  data-testid={`demo-fill-${r.toLowerCase().replace(/\s/g, "-")}`}
                  className="w-full flex items-center justify-between px-2 py-1.5 rounded hover:bg-[var(--bg-muted)] transition-colors"
                >
                  <span className="font-mono text-xs">{e}</span>
                  <span className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{r}</span>
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={seed}
              data-testid="seed-btn"
              className="mt-3 w-full text-xs underline"
              style={{ color: "var(--text-secondary)" }}
            >
              Initialize demo data
            </button>
          </div>
        </div>
      </div>

      {/* Right hero */}
      <div className="hidden lg:block relative overflow-hidden" style={{ background: "var(--bg-paper)" }}>
        <img
          src="https://images.pexels.com/photos/29390707/pexels-photo-29390707.jpeg"
          alt=""
          className="absolute inset-0 w-full h-full object-cover"
        />
        <div className="absolute inset-0" style={{ background: "linear-gradient(135deg, rgba(39,64,53,0.35), rgba(39,64,53,0.6))" }} />
        <div className="relative h-full flex items-end p-12">
          <div className="text-white max-w-md">
            <p className="text-xs uppercase tracking-[0.3em] opacity-80 mb-4">Not a CRM</p>
            <p className="font-display text-3xl font-light leading-tight">
              "Salesforce records that an activity happened. <span className="font-medium">FieldMind remembers what was discussed, what was promised, and what the market is saying.</span>"
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
