import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { Plus, Shield, Users as UsersIcon, Briefcase, Activity, BookOpen, Pencil, Trash2, FileSpreadsheet } from "lucide-react";

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
          <TabsTrigger value="taxonomy" data-testid="admin-tab-taxonomy"><BookOpen className="w-4 h-4 mr-1" />Taxonomy</TabsTrigger>
          <TabsTrigger value="imports" data-testid="admin-tab-imports"><FileSpreadsheet className="w-4 h-4 mr-1" />Doctor imports</TabsTrigger>
          <TabsTrigger value="audit" data-testid="admin-tab-audit"><Shield className="w-4 h-4 mr-1" />Audit log</TabsTrigger>
        </TabsList>
        <TabsContent value="users"><Users /></TabsContent>
        <TabsContent value="teams"><Teams /></TabsContent>
        <TabsContent value="taxonomy"><Taxonomy /></TabsContent>
        <TabsContent value="imports"><DoctorImports /></TabsContent>
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

function Taxonomy() {
  const [terms, setTerms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeKind, setActiveKind] = useState("topic");
  const [adding, setAdding] = useState(false);
  const [newCat, setNewCat] = useState("");
  const [newTerm, setNewTerm] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editCat, setEditCat] = useState("");
  const [editTerm, setEditTerm] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/taxonomy");
      setTerms(data.terms || []);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const grouped = terms
    .filter((t) => t.kind === activeKind)
    .reduce((acc, t) => {
      (acc[t.category] = acc[t.category] || []).push(t);
      return acc;
    }, {});
  const categories = Object.keys(grouped).sort();

  const create = async () => {
    const cat = newCat.trim();
    const term = newTerm.trim();
    if (!cat || !term) { toast.error("Category and term required"); return; }
    try {
      await api.post("/admin/taxonomy", { kind: activeKind, category: cat, term });
      toast.success(`Added "${term}"`);
      setNewCat(""); setNewTerm(""); setAdding(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not add term");
    }
  };

  const startEdit = (t) => {
    setEditingId(t.id);
    setEditCat(t.category);
    setEditTerm(t.term);
  };
  const saveEdit = async (id) => {
    try {
      await api.put(`/admin/taxonomy/${id}`, { category: editCat.trim(), term: editTerm.trim() });
      toast.success("Updated");
      setEditingId(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not update");
    }
  };
  const remove = async (t) => {
    if (!window.confirm(`Delete "${t.term}"? Existing visits referencing this term will keep their label.`)) return;
    try {
      await api.delete(`/admin/taxonomy/${t.id}`);
      toast.success("Deleted");
      load();
    } catch {
      toast.error("Could not delete");
    }
  };

  return (
    <div data-testid="taxonomy-tab" className="mt-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex gap-1 rounded-full p-1" style={{ background: "var(--bg-paper)" }}>
          {[{ v: "topic", label: "Topics" }, { v: "barrier", label: "Barriers" }].map((opt) => (
            <button
              key={opt.v}
              type="button"
              onClick={() => setActiveKind(opt.v)}
              data-testid={`taxonomy-kind-${opt.v}`}
              className="px-4 py-1.5 text-sm rounded-full transition-all"
              style={{
                background: activeKind === opt.v ? "var(--brand-primary)" : "transparent",
                color: activeKind === opt.v ? "white" : "var(--text-secondary)",
                fontWeight: activeKind === opt.v ? 500 : 400,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {!adding && (
          <Button size="sm" onClick={() => setAdding(true)} data-testid="taxonomy-add-btn"
                  style={{ background: "var(--brand-primary)", color: "white" }}>
            <Plus className="w-3 h-3 mr-1" /> Add {activeKind}
          </Button>
        )}
      </div>

      {adding && (
        <div className="rounded-md border p-4 grid sm:grid-cols-3 gap-2 items-end" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }} data-testid="taxonomy-add-form">
          <div>
            <Label className="mb-1 block text-xs">Category</Label>
            <Input value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder="e.g. Clinical" className="bg-white" data-testid="taxonomy-new-category" list="taxonomy-cat-suggest" />
            <datalist id="taxonomy-cat-suggest">{categories.map((c) => <option key={c} value={c} />)}</datalist>
          </div>
          <div>
            <Label className="mb-1 block text-xs">Term</Label>
            <Input value={newTerm} onChange={(e) => setNewTerm(e.target.value)} placeholder="e.g. Insurance navigation" className="bg-white" data-testid="taxonomy-new-term" />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={create} data-testid="taxonomy-save-new" style={{ background: "var(--brand-primary)", color: "white" }}>Save</Button>
            <Button size="sm" variant="ghost" onClick={() => { setAdding(false); setNewCat(""); setNewTerm(""); }}>Cancel</Button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : categories.length === 0 ? (
        <div className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }}>No {activeKind}s yet. Add the first one above.</div>
      ) : (
        <div className="space-y-3">
          {categories.map((cat) => (
            <div key={cat} className="rounded-md border" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }} data-testid={`taxonomy-cat-${cat}`}>
              <div className="px-4 py-2 border-b text-xs uppercase tracking-widest font-medium" style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}>
                {cat} <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· {grouped[cat].length}</span>
              </div>
              <ul>
                {grouped[cat].map((t) => (
                  <li key={t.id} className="px-4 py-2 flex items-center justify-between border-b last:border-b-0 gap-2" style={{ borderColor: "var(--border-default)" }} data-testid={`taxonomy-row-${t.id}`}>
                    {editingId === t.id ? (
                      <div className="flex flex-1 gap-2">
                        <Input value={editCat} onChange={(e) => setEditCat(e.target.value)} className="bg-white h-8 text-sm" data-testid={`taxonomy-edit-cat-${t.id}`} />
                        <Input value={editTerm} onChange={(e) => setEditTerm(e.target.value)} className="bg-white h-8 text-sm" data-testid={`taxonomy-edit-term-${t.id}`} />
                        <Button size="sm" onClick={() => saveEdit(t.id)} data-testid={`taxonomy-save-${t.id}`} style={{ background: "var(--brand-primary)", color: "white" }}>Save</Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>Cancel</Button>
                      </div>
                    ) : (
                      <>
                        <span className="text-sm" style={{ color: "var(--text-primary)" }}>{t.term}</span>
                        <div className="flex gap-1">
                          <button onClick={() => startEdit(t)} data-testid={`taxonomy-edit-${t.id}`} className="p-1.5 rounded hover:bg-[var(--bg-paper)]" title="Rename"><Pencil className="w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} /></button>
                          <button onClick={() => remove(t)} data-testid={`taxonomy-delete-${t.id}`} className="p-1.5 rounded hover:bg-[var(--bg-paper)]" title="Delete"><Trash2 className="w-3.5 h-3.5" style={{ color: "var(--status-danger)" }} /></button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


function DoctorImports() {
  const [imports, setImports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(null); // selected import for details

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/doctor-imports");
      setImports(data.imports || []);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  return (
    <div className="mt-4 space-y-4" data-testid="doctor-imports-tab">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Recent doctor imports across the platform.
        </div>
        <Link to="/doctors/import">
          <Button data-testid="admin-import-btn" style={{ background: "var(--brand-primary)", color: "white" }}>
            <Plus className="w-4 h-4 mr-1" /> New import
          </Button>
        </Link>
      </div>
      {loading ? (
        <div className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : imports.length === 0 ? (
        <div className="rounded-md border p-10 text-center" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
          <FileSpreadsheet className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>No imports yet. Run one from the Doctors page or click "New import" above.</div>
        </div>
      ) : (
        <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)" }}>
          <table className="w-full text-sm">
            <thead style={{ background: "var(--bg-paper)" }}>
              <tr>
                {["Date", "By", "Assigned TM", "File", "Rows", "Created", "Updated", "Skipped", "Failed", ""].map((h) => (
                  <th key={h} className="text-left px-4 py-2 text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {imports.map((imp) => (
                <tr key={imp.id} className="border-t" style={{ borderColor: "var(--border-default)" }} data-testid={`import-row-${imp.id}`}>
                  <td className="px-4 py-2">{new Date(imp.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
                  <td className="px-4 py-2">{imp.uploaded_by_email}</td>
                  <td className="px-4 py-2">{imp.assigned_tm_name || "—"}</td>
                  <td className="px-4 py-2 text-xs font-mono" style={{ color: "var(--text-muted)" }}>{imp.filename}</td>
                  <td className="px-4 py-2 text-right">{imp.row_count}</td>
                  <td className="px-4 py-2 text-right" style={{ color: "var(--status-success)" }}>{imp.created_count}</td>
                  <td className="px-4 py-2 text-right">{imp.updated_count}</td>
                  <td className="px-4 py-2 text-right" style={{ color: imp.skipped_count ? "var(--status-warning)" : "inherit" }}>{imp.skipped_count}</td>
                  <td className="px-4 py-2 text-right" style={{ color: imp.failed_count ? "var(--status-danger)" : "inherit" }}>{imp.failed_count}</td>
                  <td className="px-4 py-2 text-right">
                    <Button size="sm" variant="outline" onClick={() => setOpen(imp)} data-testid={`view-import-${imp.id}`}>Details</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Dialog open={!!open} onOpenChange={(v) => !v && setOpen(null)}>
        <DialogContent data-testid="import-details-dialog" className="max-w-2xl">
          <DialogHeader><DialogTitle>Import details</DialogTitle></DialogHeader>
          {open && (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div><span className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>File</span><div>{open.filename}</div></div>
                <div><span className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Strategy</span><div>{open.duplicate_strategy}</div></div>
                <div><span className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>By</span><div>{open.uploaded_by_email}</div></div>
                <div><span className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>For TM</span><div>{open.assigned_tm_name || "—"}</div></div>
              </div>
              {open.details?.failed?.length > 0 && (
                <div>
                  <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--status-danger)" }}>Failed rows</div>
                  <ul className="list-disc pl-5 text-xs space-y-0.5 max-h-40 overflow-y-auto">
                    {open.details.failed.slice(0, 50).map((f, i) => <li key={i}>Row {f.row_index + 2}: {f.errors.join(", ")}</li>)}
                  </ul>
                </div>
              )}
              {open.details?.skipped?.length > 0 && (
                <div>
                  <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--status-warning)" }}>Skipped duplicates</div>
                  <ul className="list-disc pl-5 text-xs space-y-0.5 max-h-40 overflow-y-auto">
                    {open.details.skipped.slice(0, 50).map((s, i) => <li key={i}>Row {s.row_index + 2}: {s.doctor_name}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
