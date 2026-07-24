import React, { useState } from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import { Brain, Mail, ArrowLeft, CheckCircle2 } from "lucide-react";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/auth/forgot-password", { email: email.trim().toLowerCase() });
      setSent(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Something went wrong — try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg-default)" }}>
      <div className="max-w-md w-full">
        <div className="flex items-center gap-2 mb-8 justify-center">
          <div className="w-10 h-10 rounded-md flex items-center justify-center" style={{ background: "var(--brand-primary)" }}>
            <Brain className="w-5 h-5 text-white" />
          </div>
          <div className="font-display text-xl font-semibold" style={{ color: "var(--brand-primary)" }}>FieldMind</div>
        </div>

        <div className="rounded-lg border p-6" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }} data-testid="forgot-password-card">
          {sent ? (
            <div className="text-center py-2" data-testid="forgot-password-sent">
              <CheckCircle2 className="w-10 h-10 mx-auto mb-3" style={{ color: "var(--status-success)" }} />
              <h1 className="font-display text-xl font-medium mb-2" style={{ color: "var(--brand-primary)" }}>Check your email</h1>
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                If <strong>{email.trim()}</strong> is registered, we've sent a link to reset your password. It expires in 1 hour.
              </p>
              <Link to="/login" className="inline-flex items-center gap-1 text-sm mt-5 hover:underline" style={{ color: "var(--brand-primary)" }}>
                <ArrowLeft className="w-3.5 h-3.5" /> Back to sign in
              </Link>
            </div>
          ) : (
            <>
              <h1 className="font-display text-xl font-medium mb-1" style={{ color: "var(--brand-primary)" }}>Forgot your password?</h1>
              <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
                Enter your email and we'll send you a link to reset it.
              </p>
              <form onSubmit={submit} className="space-y-4" data-testid="forgot-password-form">
                <div className="space-y-2">
                  <Label htmlFor="fp-email">Email</Label>
                  <Input
                    id="fp-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@field.io"
                    required
                    autoFocus
                    data-testid="forgot-password-email-input"
                    className="h-11"
                  />
                </div>
                <Button type="submit" disabled={busy} data-testid="forgot-password-submit-btn" className="w-full h-11 font-medium" style={{ background: "var(--brand-primary)", color: "white" }}>
                  <Mail className="w-4 h-4 mr-2" />
                  {busy ? "Sending…" : "Send reset link"}
                </Button>
              </form>
              <Link to="/login" className="inline-flex items-center gap-1 text-sm mt-5 hover:underline" style={{ color: "var(--text-secondary)" }}>
                <ArrowLeft className="w-3.5 h-3.5" /> Back to sign in
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
