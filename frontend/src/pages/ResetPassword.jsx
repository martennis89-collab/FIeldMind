import React, { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import { Brain, Lock, ArrowLeft } from "lucide-react";

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";
  const navigate = useNavigate();
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (next.length < 4) {
      toast.error("New password must be at least 4 characters");
      return;
    }
    if (next !== confirm) {
      toast.error("Passwords do not match");
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: next });
      toast.success("Password reset — sign in with your new password");
      navigate("/login");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not reset password");
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
          <div className="font-display text-xl font-semibold" style={{ color: "var(--brand-primary)" }}>FieldTracker</div>
        </div>

        <div className="rounded-lg border p-6" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }} data-testid="reset-password-card">
          {!token ? (
            <div className="text-center py-2" data-testid="reset-password-no-token">
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                This reset link is missing its token. Request a new one from the sign-in page.
              </p>
              <Link to="/forgot-password" className="inline-flex items-center gap-1 text-sm mt-4 hover:underline" style={{ color: "var(--brand-primary)" }}>
                <ArrowLeft className="w-3.5 h-3.5" /> Request a new link
              </Link>
            </div>
          ) : (
            <>
              <h1 className="font-display text-xl font-medium mb-1" style={{ color: "var(--brand-primary)" }}>Set a new password</h1>
              <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
                Choose a new password for your account.
              </p>
              <form onSubmit={submit} className="space-y-4" data-testid="reset-password-form">
                <div className="space-y-2">
                  <Label htmlFor="rp-new">New password</Label>
                  <Input
                    id="rp-new"
                    type="password"
                    value={next}
                    onChange={(e) => setNext(e.target.value)}
                    required
                    minLength={4}
                    autoFocus
                    data-testid="reset-password-new-input"
                    autoComplete="new-password"
                    className="h-11"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="rp-confirm">Confirm new password</Label>
                  <Input
                    id="rp-confirm"
                    type="password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                    minLength={4}
                    data-testid="reset-password-confirm-input"
                    autoComplete="new-password"
                    className="h-11"
                  />
                </div>
                <Button type="submit" disabled={busy} data-testid="reset-password-submit-btn" className="w-full h-11 font-medium" style={{ background: "var(--brand-primary)", color: "white" }}>
                  <Lock className="w-4 h-4 mr-2" />
                  {busy ? "Resetting…" : "Reset password"}
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
