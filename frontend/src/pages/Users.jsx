import { useEffect, useState, useCallback } from "react";
import api, { formatApiError, API } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Plus, Download, Trash2 } from "lucide-react";

const ROLES = ["ADMIN", "OPERATORE", "APPROVATORE", "SOLA_LETTURA"];
const EMPTY = { first_name: "", last_name: "", email: "", role: "OPERATORE", password: "", active: true };

export default function Users() {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState(null);
  const [del, setDel] = useState(null);
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");

  const load = useCallback(() => { api.get("/users").then((r) => setRows(r.data)).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      if (form.id) await api.put(`/users/${form.id}`, { first_name: form.first_name, last_name: form.last_name, role: form.role, active: form.active });
      else await api.post("/users", form);
      toast.success("Utente salvato"); setForm(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const doDelete = async () => {
    try { await api.delete(`/users/${del.id}?confirm=true`); toast.success("Utente eliminato"); setDel(null); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <PageHeader title="Utenti e ruoli" subtitle="Ruoli: ADMIN, OPERATORE, APPROVATORE, SOLA_LETTURA. Esportazione e cancellazione con conferma e audit."
        actions={isAdmin && <button data-testid="add-user" onClick={() => setForm({ ...EMPTY })} className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200"><Plus className="w-4 h-4" /> Nuovo utente</button>} />

      {rows.length === 0 ? <Empty text="Nessun utente." /> : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm" data-testid="users-table">
            <thead className="border-b border-border/60 text-muted-foreground">
              <tr className="[&>th]:label-caps [&>th]:text-left [&>th]:px-4 [&>th]:py-2.5">
                <th>Nome</th><th>Email</th><th>Ruolo</th><th>Stato</th><th>Ultimo accesso</th><th className="text-right">Azioni</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id} className="border-b border-border/40 hover:bg-muted/50 transition-colors duration-200">
                  <td className="px-4 py-2.5">{u.first_name} {u.last_name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs">{u.email}</td>
                  <td className="px-4 py-2.5"><span className="text-[10px] font-mono border border-border rounded-sm px-1.5 py-0.5">{u.role}</span></td>
                  <td className="px-4 py-2.5">{u.active ? <span className="text-emerald-400">attivo</span> : <span className="text-muted-foreground">disattivo</span>}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">{u.last_login ? new Date(u.last_login).toLocaleString() : "mai"}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1.5">
                      {isAdmin && <button onClick={() => setForm({ ...u })} className="rounded-sm border border-border px-2 py-1 text-xs hover:bg-muted/50">Modifica</button>}
                      {isAdmin && <a data-testid={`export-${u.id}`} href={`${API}/users/${u.id}/export`} className="rounded-sm border border-border px-2 py-1 text-xs hover:bg-muted/50 inline-flex items-center gap-1"><Download className="w-3 h-3" /></a>}
                      {isAdmin && <button data-testid={`delete-${u.id}`} onClick={() => setDel(u)} className="rounded-sm border border-red-500/40 text-red-400 px-2 py-1 hover:bg-red-500/10"><Trash2 className="w-3.5 h-3.5" /></button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {form && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={() => setForm(null)}>
          <div className="bg-card border border-border rounded-sm p-6 w-full max-w-lg shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-display text-lg font-medium mb-4">{form.id ? "Modifica utente" : "Nuovo utente"}</h3>
            <div className="grid grid-cols-2 gap-3">
              <In l="Nome" v={form.first_name} on={(v) => setForm({ ...form, first_name: v })} testid="user-first" />
              <In l="Cognome" v={form.last_name} on={(v) => setForm({ ...form, last_name: v })} testid="user-last" />
              <In l="Email" v={form.email} on={(v) => setForm({ ...form, email: v })} disabled={!!form.id} full testid="user-email" />
              {!form.id && <In l="Password iniziale" v={form.password} on={(v) => setForm({ ...form, password: v })} type="password" full testid="user-pass" />}
              <div>
                <label className="label-caps block mb-1">Ruolo</label>
                <select data-testid="user-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm">
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div className="flex items-end gap-2">
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Attivo</label>
              </div>
            </div>
            <div className="flex gap-2 mt-4">
              <button data-testid="user-save" onClick={save} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Salva</button>
              <button onClick={() => setForm(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
            </div>
          </div>
        </div>
      )}

      {del && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={() => setDel(null)}>
          <div className="bg-card border border-red-500/40 rounded-sm p-6 w-full max-w-md shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-display text-lg font-medium mb-2">Conferma cancellazione</h3>
            <p className="text-sm text-muted-foreground mb-4">Eliminare definitivamente <b>{del.email}</b>? L'operazione viene registrata nell'audit.</p>
            <div className="flex gap-2">
              <button data-testid="confirm-delete" onClick={doDelete} className="bg-red-600 text-white rounded-sm px-4 py-2 text-sm">Elimina</button>
              <button onClick={() => setDel(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function In({ l, v, on, type = "text", full, disabled, testid }) {
  return (
    <div className={full ? "col-span-2" : ""}>
      <label className="label-caps block mb-1">{l}</label>
      <input data-testid={testid} type={type} value={v} disabled={disabled} onChange={(e) => on(e.target.value)}
        className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none disabled:opacity-60" />
    </div>
  );
}
