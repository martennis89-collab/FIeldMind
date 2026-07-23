import React, { useMemo, useState } from "react";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { toast } from "sonner";
import { KeyRound, ShieldCheck, UserRound, Globe } from "lucide-react";

// Full IANA zone list where the browser supports it (virtually every modern
// browser does); falls back to a small curated set otherwise so the picker
// never breaks. Works for any user in any country — nothing hardcoded.
function allTimezones() {
  try {
    if (typeof Intl.supportedValuesOf === "function") {
      return Intl.supportedValuesOf("timeZone");
    }
  } catch {
    /* fall through */
  }
  return [
    "UTC", "Europe/Sofia", "Europe/London", "Europe/Berlin", "Europe/Madrid", "Europe/Paris",
    "Europe/Athens", "Europe/Istanbul", "Europe/Moscow", "America/New_York", "America/Chicago",
    "America/Denver", "America/Los_Angeles", "America/Sao_Paulo", "Asia/Dubai", "Asia/Kolkata",
    "Asia/Shanghai", "Asia/Tokyo", "Australia/Sydney",
  ];
}

export default function Account() {
  const { user, refresh } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [tzBusy, setTzBusy] = useState(false);
  const timezones = useMemo(allTimezones, []);

  const updateTimezone = async (tz) => {
    setTzBusy(true);
    try {
      await api.put("/auth/timezone", { timezone: tz });
      await refresh();
      toast.success("Timezone updated");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not update timezone");
    } finally {
      setTzBusy(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (next.length < 4) {
      toast.error("New password must be at least 4 characters");
      return;
    }
    if (next !== confirm) {
      toast.error("New password and confirmation do not match");
      return;
    }
    if (next === current) {
      toast.error("New password must be different from the current one");
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      toast.success("Password updated");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not update password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto" data-testid="account-page">
      <div className="mb-6">
        <div className="text-[11px] uppercase tracking-[0.2em]" style={{ color: "var(--text-muted)" }}>
          Settings
        </div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          My account
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          Review your profile details and reset your password whenever you need.
        </p>
      </div>

      {/* Profile card */}
      <section
        className="rounded-lg border p-5 mb-6"
        style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}
        data-testid="account-profile-card"
      >
        <div className="flex items-center gap-2 mb-4">
          <UserRound className="w-4 h-4" style={{ color: "var(--brand-primary)" }} />
          <div className="text-sm font-medium" style={{ color: "var(--brand-primary)" }}>Profile</div>
        </div>
        <div className="grid sm:grid-cols-2 gap-4 text-sm">
          <Field label="Name" value={user?.full_name} testid="account-name" />
          <Field label="Email" value={user?.email} testid="account-email" />
          <Field label="Role" value={user?.role} testid="account-role" />
          {user?.region && <Field label="Region" value={user.region} testid="account-region" />}
        </div>
        <p className="mt-4 text-xs" style={{ color: "var(--text-muted)" }}>
          Name, email, or role wrong? Ping an admin — they can update your profile from the Admin panel.
        </p>
      </section>

      {/* Timezone card */}
      <section
        className="rounded-lg border p-5 mb-6"
        style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}
        data-testid="account-timezone-card"
      >
        <div className="flex items-center gap-2 mb-4">
          <Globe className="w-4 h-4" style={{ color: "var(--brand-primary)" }} />
          <div className="text-sm font-medium" style={{ color: "var(--brand-primary)" }}>Timezone</div>
        </div>
        <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
          Used so voice notes and Telegram messages like "book a meeting tomorrow at 2pm" resolve against
          your own calendar day, wherever you are.
        </p>
        <div className="max-w-sm">
          <Select value={user?.timezone || ""} onValueChange={updateTimezone} disabled={tzBusy}>
            <SelectTrigger className="bg-white" data-testid="account-timezone-select">
              <SelectValue placeholder="Select your timezone" />
            </SelectTrigger>
            <SelectContent className="max-h-72">
              {timezones.map((tz) => (
                <SelectItem key={tz} value={tz}>{tz.replace(/_/g, " ")}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </section>

      {/* Password change card */}
      <section
        className="rounded-lg border p-5"
        style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}
        data-testid="account-password-card"
      >
        <div className="flex items-center gap-2 mb-4">
          <KeyRound className="w-4 h-4" style={{ color: "var(--brand-primary)" }} />
          <div className="text-sm font-medium" style={{ color: "var(--brand-primary)" }}>Change password</div>
        </div>
        <form onSubmit={submit} className="space-y-4" data-testid="change-password-form">
          <div className="space-y-2">
            <Label htmlFor="cur-pw">Current password</Label>
            <Input
              id="cur-pw"
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
              data-testid="current-password-input"
              autoComplete="current-password"
              className="h-11"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-pw">New password</Label>
            <Input
              id="new-pw"
              type="password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
              minLength={4}
              data-testid="new-password-input"
              autoComplete="new-password"
              className="h-11"
            />
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              At least 4 characters. Pick something only you know.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm-pw">Confirm new password</Label>
            <Input
              id="confirm-pw"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              minLength={4}
              data-testid="confirm-password-input"
              autoComplete="new-password"
              className="h-11"
            />
          </div>
          <Button
            type="submit"
            disabled={busy}
            data-testid="change-password-submit"
            className="h-11 font-medium"
            style={{ background: "var(--brand-primary)", color: "white" }}
          >
            <ShieldCheck className="w-4 h-4 mr-2" />
            {busy ? "Updating…" : "Update password"}
          </Button>
        </form>
      </section>
    </div>
  );
}

function Field({ label, value, testid }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="mt-0.5 text-sm font-medium" style={{ color: "var(--text-primary)" }} data-testid={testid}>
        {value || "—"}
      </div>
    </div>
  );
}
