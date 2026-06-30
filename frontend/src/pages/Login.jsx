import React, { useState } from "react";
import { useAuth } from "../lib/auth";
import { useNavigate, Link } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import { Brain, Lock } from "lucide-react";

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

  return (
    <div
      className="grid lg:grid-cols-2 min-h-screen lg:h-screen lg:overflow-hidden"
      style={{ background: "var(--bg-default)" }}
    >
      {/* Left form */}
      <div className="flex flex-col justify-center px-6 sm:px-12 lg:px-16 py-8 lg:py-6 lg:overflow-y-auto">
        <div className="max-w-md w-full mx-auto">
          <div className="flex items-center gap-2 mb-6 lg:mb-8">
            <div
              className="w-10 h-10 rounded-md flex items-center justify-center"
              style={{ background: "var(--brand-primary)" }}
            >
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div>
              <div
                className="font-display text-xl font-semibold"
                style={{ color: "var(--brand-primary)" }}
              >
                FieldMind
              </div>
              <div
                className="text-[11px] uppercase tracking-[0.2em]"
                style={{ color: "var(--text-muted)" }}
              >
                Field Intelligence
              </div>
            </div>
          </div>

          <h1
            className="font-display text-3xl sm:text-4xl lg:text-[2.5rem] font-light tracking-tight leading-[1.1]"
            style={{ color: "var(--brand-primary)" }}
          >
            Your secure
            <br />
            second brain
            <br />
            <span className="font-medium">in the field.</span>
          </h1>
          <p
            className="mt-3 text-sm sm:text-base leading-relaxed"
            style={{ color: "var(--text-secondary)" }}
          >
            Remember every conversation. Track every promise. Surface the
            doctors who need attention next.
          </p>

          <form
            onSubmit={submit}
            className="mt-6 lg:mt-8 space-y-4"
            data-testid="login-form"
          >
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

          {/* Mobile quote — shown below the form so it's visible with at most a small scroll */}
          <div
            className="lg:hidden mt-8 rounded-lg border p-5"
            style={{
              background: "var(--brand-primary)",
              borderColor: "var(--brand-primary)",
            }}
            data-testid="mobile-quote-block"
          >
            <p className="text-[10px] uppercase tracking-[0.3em] text-white/70 mb-2">
              Not a CRM
            </p>
            <p className="font-display text-base leading-snug text-white">
              &quot;Salesforce records that an activity happened.{" "}
              <span className="font-medium">
                FieldMind remembers what was discussed, what was promised, and
                what the market is saying.
              </span>
              &quot;
            </p>
          </div>
        </div>
      </div>

      {/* Right hero (desktop only) */}
      <div
        className="hidden lg:block relative overflow-hidden"
        style={{ background: "var(--bg-paper)" }}
      >
        <img
          src="https://images.pexels.com/photos/29390707/pexels-photo-29390707.jpeg"
          alt=""
          className="absolute inset-0 w-full h-full object-cover"
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(135deg, rgba(39,64,53,0.35), rgba(39,64,53,0.6))",
          }}
        />
        <div className="relative h-full flex items-end p-10 xl:p-12">
          <div className="text-white max-w-md">
            <p className="text-xs uppercase tracking-[0.3em] opacity-80 mb-3">
              Not a CRM
            </p>
            <p className="font-display text-2xl xl:text-3xl font-light leading-snug">
              &quot;Salesforce records that an activity happened.{" "}
              <span className="font-medium">
                FieldMind remembers what was discussed, what was promised, and
                what the market is saying.
              </span>
              &quot;
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
