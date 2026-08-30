import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";
import { toast } from "sonner";

export default function Approvals() {
  const [rows, setRows] = useState([]);
  const [confirm, setConfirm] = useState(null); // {type: 'all-approve'|'all-reject'}
  const { hasRole } = useAuth();
  const { refresh } = useSystem();
  const canApprove = hasRole("ADMIN", "APPROVATORE");

  const load = useCallback(() => {
    api.get("/approvals?status=IN_ATTESA_APPROVAZIONE").then((r) => setRows(r.data)).catch(() => {});
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);

  const act = async (id, action) => {
    try { await api.post(`/approvals/${id}/${action}`); toast.success(action === "approve" ? "Approvata" : "Rifiutata"); load(); refresh(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const bulk = async (action) => {
    setConfirm(null);
    try { const { data } = await api.post(`/approvals/${action}-all`); toast.success(`Elaborate ${data.processed}`); load(); refresh(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <PageHeader title="Centro Approvazioni"
        subtitle="Preventivi, spese, invii, pubblicazioni e azioni esterne. Approvazione idempotente."
        actions={canApprove && rows.length > 0 && (
          <div className="flex gap-2">
            <button data-testid="approve-all" onClick={() => setConfirm("approve")}
              className="rounded-sm bg-emerald-600 text-white px-3 py-2 text-sm hover:bg-emerald-500 active:scale-[0.98] transition-colors duration-200">APPROVA TUTTE</button>
            <button data-testid="reject-all" onClick={() => setConfirm("reject")}
              className="rounded-sm border border-red-500/40 text-red-400 px-3 py-2 text-sm hover:bg-red-500/10 active:scale-[0.98] transition-colors duration-200">RIFIUTA TUTTE</button>
          </div>
        )}
      />

      {confirm && (
        <Card className="p-4 mb-4 border-amber-500/40 bg-amber-500/5">
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm">Confermi l'azione in blocco: <b>{confirm === "approve" ? "APPROVA TUTTE" : "RIFIUTA TUTTE"}</b>?</span>
            <div className="flex gap-2">
              <button data-testid="bulk-confirm" onClick={() => bulk(confirm)} className="rounded-sm bg-primary text-primary-foreground px-3 py-1.5 text-sm">Conferma</button>
              <button onClick={() => setConfirm(null)} className="rounded-sm border border-border px-3 py-1.5 text-sm">Annulla</button>
            </div>
          </div>
        </Card>
      )}

      {rows.length === 0 ? <Empty text="Nessuna richiesta in attesa." /> : (
        <div className="space-y-3" data-testid="approvals-list">
          {rows.map((a) => (
            <Card key={a.id} className="p-5">
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <StatusBadge status={a.type} />
                    <span className="font-display font-medium">{a.title}</span>
                    {a.blocked && <span className="text-[10px] font-mono border border-red-500/30 bg-red-500/10 text-red-400 rounded-sm px-1.5 py-0.5">BLOCCATA</span>}
                  </div>
                  <p className="text-sm text-muted-foreground mb-2 max-w-2xl">{a.what}</p>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <Field label="Agente" value={a.agent_responsible} />
                    <Field label="Costo min/prob/max" value={`$${a.cost_min.toFixed(4)} / $${a.cost_probable.toFixed(4)} / $${a.cost_max.toFixed(4)}`} mono />
                    <Field label="Tetto approvabile" value={`$${a.approved_cap.toFixed(4)}`} mono />
                    <Field label="Rischi" value={(a.risks || []).join(", ") || "—"} />
                  </div>
                  {a.prerequisites?.length > 0 && (
                    <div className="mt-2 text-xs text-red-400">Prerequisiti mancanti: {a.prerequisites.join(", ")}</div>
                  )}
                  {a.external_actions?.length > 0 && (
                    <div className="mt-1 text-xs text-amber-400">Azioni esterne: {a.external_actions.join(", ")}</div>
                  )}
                  <p className="text-[11px] text-muted-foreground mt-2">Conseguenze: {a.consequences}</p>
                </div>
                {canApprove && (
                  <div className="flex gap-2 shrink-0">
                    <button data-testid={`approve-${a.id}`} disabled={a.blocked} onClick={() => act(a.id, "approve")}
                      className="rounded-sm bg-emerald-600 text-white px-3 py-2 text-sm hover:bg-emerald-500 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40">APPROVA</button>
                    <button data-testid={`reject-${a.id}`} onClick={() => act(a.id, "reject")}
                      className="rounded-sm border border-red-500/40 text-red-400 px-3 py-2 text-sm hover:bg-red-500/10 active:scale-[0.98] transition-colors duration-200">RIFIUTA</button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Field({ label, value, mono }) {
  return (
    <div>
      <div className="label-caps">{label}</div>
      <div className={`mt-0.5 ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}
