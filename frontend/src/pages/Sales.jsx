import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Plus, MessageSquareText, CheckCircle2, Link as LinkIcon, RefreshCw, ArrowRight } from "lucide-react";

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 10, pages: 0 };
const RESPONSE_TYPES = [
  "POSITIVA", "NEGATIVA", "RICHIESTA_INFORMAZIONI", "OBIEZIONE_PREZZO",
  "NON_INTERESSATO", "RICONTATTO_FUTURO", "NESSUNA_RISPOSTA", "ESCALATION", "RICHIESTA_APPUNTAMENTO",
];
const STAGE_TARDIVI = ["OPPORTUNITA", "PROPOSTA", "NEGOZIAZIONE", "VINTO", "PERSO"];

function Pager({ data, onPage }) {
  if (!data || data.pages <= 1) return null;
  return (
    <div className="flex items-center justify-between mt-2 text-[11px] text-muted-foreground">
      <span>{`Pagina ${data.page} di ${data.pages}`}</span>
      <div className="flex gap-1.5">
        <button disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}
          className="rounded-sm border border-border px-2 py-0.5 disabled:opacity-40">Precedente</button>
        <button disabled={data.page >= data.pages} onClick={() => onPage(data.page + 1)}
          className="rounded-sm border border-border px-2 py-0.5 disabled:opacity-40">Successiva</button>
      </div>
    </div>
  );
}

export default function Sales() {
  const [opportunities, setOpportunities] = useState(EMPTY_PAGE);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [responding, setResponding] = useState(false);
  const { hasRole } = useAuth();
  const canApprove = hasRole("ADMIN") || hasRole("APPROVATORE");

  const loadOpportunities = useCallback((page = 1) => {
    api.get("/sales/opportunities", { params: { page, page_size: 10 } })
      .then((r) => setOpportunities(r.data)).catch(() => {});
  }, []);

  useEffect(() => { loadOpportunities(); }, [loadOpportunities]);

  const refreshSelected = async (id) => {
    const { data } = await api.get(`/sales/opportunities/${id}`);
    setSelected(data);
  };

  // ---------- Creazione ----------
  const [form, setForm] = useState({ lead_id: "", lead_type: "aziende" });
  const createOpportunity = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/sales/opportunities", form);
      toast.success(`Opportunità creata — stage ${data.stage}.`);
      setCreating(false); loadOpportunities(); setSelected(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Azioni ----------
  const requestMessage = async () => {
    setBusy(true);
    try {
      await api.post(`/sales/opportunities/${selected.id}/request-message`, {});
      toast.success("Messaggio richiesto a Content Creator.");
      await refreshSelected(selected.id); loadOpportunities();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const markContacted = async () => {
    setBusy(true);
    try {
      await api.post(`/sales/opportunities/${selected.id}/mark-contacted`);
      toast.success("Contatto confermato.");
      await refreshSelected(selected.id); loadOpportunities();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const [responseForm, setResponseForm] = useState({ response_type: "POSITIVA", note: "" });
  const recordResponse = async () => {
    setBusy(true);
    try {
      await api.post(`/sales/opportunities/${selected.id}/record-response`, responseForm);
      toast.success("Risposta registrata.");
      setResponding(false); await refreshSelected(selected.id); loadOpportunities();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const linkAppointment = async () => {
    const proposal_id = window.prompt("ID proposta già creata in Appointment Setter — laboratorio:");
    if (!proposal_id || !proposal_id.trim()) return;
    setBusy(true);
    try {
      await api.post(`/sales/opportunities/${selected.id}/link-appointment`, { proposal_id });
      toast.success("Appuntamento collegato.");
      await refreshSelected(selected.id); loadOpportunities();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const syncAppointment = async () => {
    setBusy(true);
    try {
      await api.post(`/sales/opportunities/${selected.id}/sync-appointment`);
      toast.info("Stato appuntamento aggiornato.");
      await refreshSelected(selected.id); loadOpportunities();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const advanceStage = async (newStage) => {
    setBusy(true);
    try {
      await api.post(`/sales/opportunities/${selected.id}/advance-stage`, null, { params: { new_stage: newStage } });
      toast.success(`Avanzato a ${newStage}.`);
      await refreshSelected(selected.id); loadOpportunities();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const resolveEscalation = async () => {
    const note = window.prompt("Nota di risoluzione (obbligatoria):");
    if (!note || !note.trim()) return;
    setBusy(true);
    try {
      await api.post(`/sales/opportunities/${selected.id}/resolve-escalation`, { note });
      toast.success("Escalation risolta.");
      await refreshSelected(selected.id); loadOpportunities();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Sales — laboratorio"
        subtitle="Pipeline commerciale da lead qualificati: strategia, canale, next-best-action, gestione risposte e obiezioni."
        actions={
          <button data-testid="new-opportunity" onClick={() => setCreating(true)}
            className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 transition-colors duration-200">
            <Plus className="w-4 h-4" /> Nuova opportunità
          </button>
        } />

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
        <div>
          <h2 className="font-display text-sm label-caps mb-2">Opportunità</h2>
          {opportunities.items.length === 0 ? <Empty text="Nessuna opportunità ancora." /> : (
            <>
              <div className="space-y-2" data-testid="opportunities-list">
                {opportunities.items.map((o) => (
                  <Card key={o.id} className={`p-3 cursor-pointer ${selected?.id === o.id ? "border-primary" : ""}`}
                    onClick={() => setSelected(o)}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs truncate">{o.lead_id}</span>
                      <StatusBadge status={o.stage} />
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">{o.next_best_action}</div>
                  </Card>
                ))}
              </div>
              <Pager data={opportunities} onPage={loadOpportunities} />
            </>
          )}
        </div>

        <div>
          {!selected ? <Empty text="Seleziona o crea un'opportunità commerciale." /> : (
            <Card className="p-5">
              <div className="flex items-center justify-between flex-wrap gap-3 mb-2">
                <div>
                  <h3 className="font-display text-lg font-medium">Lead {selected.lead_id}</h3>
                  <div className="text-xs text-muted-foreground mt-1">Interesse stimato: {selected.analysis?.stima_interesse}</div>
                </div>
                <StatusBadge status={selected.stage} />
              </div>

              {selected.escalation_richiesta && (
                <div className="mb-4 flex items-center justify-between text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2">
                  <span>Richiede intervento umano (escalation).</span>
                  <button onClick={resolveEscalation} disabled={busy} className="underline">Risolvi</button>
                </div>
              )}

              <div className="text-xs text-muted-foreground mb-4 space-y-1">
                <div>{selected.analysis?.pain_point}</div>
                <div>{selected.analysis?.value_proposition}</div>
              </div>

              <div className="flex flex-wrap gap-2 mb-4">
                {["QUALIFICATO", "FOLLOW_UP"].includes(selected.stage) && !selected.message_content_item_id && (
                  <button data-testid="request-message-btn" onClick={requestMessage} disabled={busy}
                    className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-1.5 text-sm hover:opacity-90">
                    <MessageSquareText className="w-3.5 h-3.5" /> Richiedi messaggio a Content Creator
                  </button>
                )}
                {selected.stage === "QUALIFICATO" && selected.message_content_item_id && (
                  <button data-testid="mark-contacted-btn" onClick={markContacted} disabled={busy}
                    className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Conferma invio messaggio
                  </button>
                )}
                {["CONTATTATO", "IN_RELAZIONE", "FOLLOW_UP"].includes(selected.stage) && (
                  <button data-testid="record-response-btn" onClick={() => setResponding(true)} disabled={busy}
                    className="border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">Registra risposta prospect</button>
                )}
                {selected.stage === "RICHIESTA_APPUNTAMENTO" && (
                  <button onClick={linkAppointment} disabled={busy}
                    className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">
                    <LinkIcon className="w-3.5 h-3.5" /> Collega appuntamento
                  </button>
                )}
                {selected.appointment_proposal_id && ["RICHIESTA_APPUNTAMENTO", "APPUNTAMENTO_FISSATO"].includes(selected.stage) && (
                  <button onClick={syncAppointment} disabled={busy}
                    className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">
                    <RefreshCw className="w-3.5 h-3.5" /> Aggiorna stato appuntamento
                  </button>
                )}
                {canApprove && STAGE_TARDIVI.slice(0, -2).includes(selected.stage) && (
                  <button data-testid="advance-stage-btn"
                    onClick={() => advanceStage(STAGE_TARDIVI[STAGE_TARDIVI.indexOf(selected.stage) + 1])}
                    disabled={busy}
                    className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">
                    <ArrowRight className="w-3.5 h-3.5" /> Avanza stage
                  </button>
                )}
                {canApprove && selected.stage === "APPUNTAMENTO_FISSATO" && (
                  <button onClick={() => advanceStage("OPPORTUNITA")} disabled={busy}
                    className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">
                    <ArrowRight className="w-3.5 h-3.5" /> Segna come Opportunità
                  </button>
                )}
              </div>
            </Card>
          )}
        </div>
      </div>

      {creating && (
        <Modal onClose={() => setCreating(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Nuova opportunità commerciale</h3>
          <div className="space-y-3">
            <Field label="ID lead (da Lead Generation — PRONTO_PER_SALES)" value={form.lead_id}
                  onChange={(v) => setForm({ ...form, lead_id: v })} />
            <div>
              <div className="label-caps mb-1">Tipo lead</div>
              <select value={form.lead_type} onChange={(e) => setForm({ ...form, lead_type: e.target.value })}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm">
                <option value="aziende">Azienda</option>
                <option value="persone">Persona</option>
              </select>
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={createOpportunity} disabled={busy || !form.lead_id.trim()}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Crea</button>
            <button onClick={() => setCreating(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {responding && (
        <Modal onClose={() => setResponding(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Registra risposta del prospect</h3>
          <div className="space-y-3">
            <div>
              <div className="label-caps mb-1">Tipo di risposta</div>
              <select value={responseForm.response_type}
                onChange={(e) => setResponseForm({ ...responseForm, response_type: e.target.value })}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm">
                {RESPONSE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <Field label="Nota" value={responseForm.note} onChange={(v) => setResponseForm({ ...responseForm, note: v })} />
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={recordResponse} disabled={busy}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Registra</button>
            <button onClick={() => setResponding(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Field({ label, value, onChange }) {
  return (
    <div>
      <div className="label-caps mb-1">{label}</div>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
    </div>
  );
}
function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-sm p-6 w-full max-w-2xl shadow-xl max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}
