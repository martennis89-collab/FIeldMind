import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { Plus, Shield, Users as UsersIcon, Briefcase, Activity } from "lucide-react";

const ALL = "__ALL__";

export default function Admin() {
  return (
    <div data-testid="admin-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Administration</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          Manage <span className="font-medium">the platform.</span>
        </h1>
      </div>
      <Tabs defaultValue="users">
        <TabsList className="bg-[var(--bg-paper)]">
          <TabsTrigger value="users" data-testid="admin-tab-users"><UsersIcon className="w-4 h-4 mr-1" />Users</TabsTrigger>
          <TabsTrigger value="teams" data-testid="admin-tab-teams"><Briefcase className="w-4 h-4 mr-1" />Teams</TabsTrigger>
          <TabsTrigger value="audit" data-testid="admin-tab-audit"><Shield className="w-4 h-4 mr-1" />Audit log</TabsTrigger>
        </TabsList>
        <TabsContent value="users"><Users /></TabsContent>
        <TabsContent value="teams"><Teams /></TabsContent>
        <TabsContent value="audit"><Audit /></TabsContent>
      </Tabs>
    </div>
  );
}

function Users() {
  const [users, setUsers] = useState([]);
  const [teams, setTeams] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ full_name: "", email: "", password: "", role: "TM", team_id: "", region: "" });

  const load = async () => {
    const [u, t] = await Promise.all([api.get("/users"), api.get("/teams")]);
    setUsers(u.data); setTeams(t.data);
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    try {
      await api.post("/users", { ...form, team_id: form.team_id || null, region: form.region || null });
      toast.success("User created");
      setOpen(false); setForm({ full_name: "", email: "", password: "", role: "TM", team_id: "", region: "" });
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  const toggleActive = async (u) => {
    await api.put(`/users/${u.id}`, { active_status: !u.active_status });
    toast.success(`User ${u.active_status ? "deactivated" : "activated"}`);
    load();
  };

  return (
    <div className="mt-4">
      <div className="flex justify-end mb-3">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button data-testid="add-user-btn" style={{ background: "var(--brand-primary)", color: "white" }}><Plus className="w-4 h-4 mr-1" /> New user</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>Create user</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Full name</Label><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} data-testid="new-user-name" /></div>
              <div><Label>Email</Label><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="new-user-email" /></div>
              <div><Label>Password</Label><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="new-user-password" /></div>
              <div><Label>Role</Label>
                <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                  <SelectTrigger data-testid="new-user-role"><SelectValue /></SelectTrigger>
                  <SelectContent>{["TM", "Manager", "Admin"].map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div><Label>Team</Label>
                <Select value={form.team_id || ALL} onValueChange={(v) => setForm({ ...form, team_id: v === ALL ? "" : v })}>
                  <SelectTrigger><SelectValue placeholder="None" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>None</SelectItem>
                    {teams.map((t) => <SelectItem key={t.id} value={t.id}>{t.team_name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div><Label>Region</Label><Input value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} /></div>
            </div>
            <DialogFooter>
              <Button onClick={create} disabled={!form.email || !form.password || !form.full_name} data-testid="submit-new-user">Create</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)" }}>
        <table className="w-full text-sm">
          <thead style={{ background: "var(--bg-paper)" }}>
            <tr>{["Name", "Email", "Role", "Team", "Active", ""].map((h) => <th key={h} className="text-left px-4 py-2 text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const team = teams.find((t) => t.id === u.team_id);
              return (
                <tr key={u.id} className="border-t" style={{ borderColor: "var(--border-default)" }} data-testid={`user-row-${u.id}`}>
                  <td className="px-4 py-2 font-medium">{u.full_name}</td>
                  <td className="px-4 py-2">{u.email}</td>
                  <td className="px-4 py-2"><span className="pill pill-info">{u.role}</span></td>
                  <td className="px-4 py-2">{team?.team_name || "—"}</td>
                  <td className="px-4 py-2">{u.active_status ? <span className="pill pill-success">Active</span> : <span className="pill pill-danger">Disabled</span>}</td>
                  <td className="px-4 py-2 text-right">
                    <Button size="sm" variant="outline" onClick={() => toggleActive(u)} data-testid={`toggle-user-${u.id}`}>
                      {u.active_status ? "Deactivate" : "Activate"}
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Teams() {
  const [teams, setTeams] = useState([]);
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ team_name: "", manager_user_id: "", region: "" });
  const load = async () => {
    const [t, u] = await Promise.all([api.get("/teams"), api.get("/users")]);
    setTeams(t.data); setUsers(u.data);
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    try {
      await api.post("/teams", { ...form, manager_user_id: form.manager_user_id || null, region: form.region || null });
      toast.success("Team created"); setOpen(false); setForm({ team_name: "", manager_user_id: "", region: "" }); load();
    } catch (e) { toast.error("Failed"); }
  };

  return (
    <div className="mt-4">
      <div className="flex justify-end mb-3">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild><Button data-testid="add-team-btn" style={{ background: "var(--brand-primary)", color: "white" }}><Plus className="w-4 h-4 mr-1" />New team</Button></DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle>Create team</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <div><Label>Team name</Label><Input value={form.team_name} onChange={(e) => setForm({ ...form, team_name: e.target.value })} data-testid="new-team-name" /></div>
              <div><Label>Region</Label><Input value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} /></div>
              <div><Label>Manager</Label>
                <Select value={form.manager_user_id || ALL} onValueChange={(v) => setForm({ ...form, manager_user_id: v === ALL ? "" : v })}>
                  <SelectTrigger><SelectValue placeholder="None" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>None</SelectItem>
                    {users.filter((u) => u.role === "Manager").map((u) => <SelectItem key={u.id} value={u.id}>{u.full_name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter><Button onClick={create} disabled={!form.team_name} data-testid="submit-new-team">Create</Button></DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {teams.map((t) => (
          <div key={t.id} className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
            <div className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>{t.team_name}</div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>{t.region || "—"}</div>
            <div className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>Manager: {users.find((u) => u.id === t.manager_user_id)?.full_name || "—"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Audit() {
  const [logs, setLogs] = useState([]);
  useEffect(() => { api.get("/audit", { params: { limit: 200 } }).then((r) => setLogs(r.data)); }, []);
  return (
    <div className="mt-4 rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)" }}>
      <table className="w-full text-sm">
        <thead style={{ background: "var(--bg-paper)" }}>
          <tr>{["Time", "Actor", "Action", "Entity", "ID"].map((h) => <th key={h} className="text-left px-4 py-2 text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {logs.map((l) => (
            <tr key={l.id} className="border-t" style={{ borderColor: "var(--border-default)" }}>
              <td className="px-4 py-2 text-xs" style={{ color: "var(--text-muted)" }}>{new Date(l.timestamp).toLocaleString()}</td>
              <td className="px-4 py-2">{l.user_email || "—"}</td>
              <td className="px-4 py-2"><span className="pill pill-info">{l.action_type}</span></td>
              <td className="px-4 py-2">{l.entity_type}</td>
              <td className="px-4 py-2 font-mono text-xs">{l.entity_id?.slice(0, 8)}…</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
