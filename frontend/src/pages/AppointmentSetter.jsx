import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import {
  Plus, CalendarClock, CheckCircle2, XCircle, RefreshCw, Trash2, Link as LinkIcon,
} from "lucide-react";

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 10, pages: 0 };
const PROVIDER_LABELS = { google_calendar: "Google Calendar", microsoft_graph: "Microsoft Graph", calendly: "Calendly" };

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

export default function AppointmentSetter() {
  const [searchParams] = useSearchParams();
  const [connections, setConnections] = useState([]);
  const [proposals, setProposals] = useState(EMPTY_PAGE);
  const [bookings, setBookings] = useState(EMPTY_PAGE);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [creatingConn, setCreatingConn] = useState(false);
  const [creatingProposal, setCreatingProposal] = useState(false);
  const { hasRole } = useAuth();
  const canApprove = hasRole("ADMIN") || hasRole("APPROVATORE");

  const loadConnections = useCallback(() => {
    api.get("/appointments/connections").then((r) => setConnections(r.data)).catch(() => {});
  }, []);
  const loadProposals = useCallback((page = 1) => {
    api.get("/appointments/proposals", { params: { page, page_size: 10 } })
      .then((r) => setProposals(r.data)).catch(() => {});
  }, []);
  const loadBookings = useCallback((page = 1) => {
    api.get("/appointments/bookings", { params: { page, page_size: 10 } })
      .then((r) => setBookings(r.data)).catch(() => {});
  }, []);

  useEffect(() => { loadConnections(); loadProposals(); loadBookings(); }, [loadConnections, loadProposals, loadBookings]);

  useEffect(() => {
    const proposalId = searchParams.get("proposalId");
    if (proposalId) {
      api.get(`/appointments/proposals/${proposalId}`).then((r) => setSelected(r.data)).catch(() => {});
    }
  }, [searchParams]);

  // ---------- Connessioni ----------
  const [connForm, setConnForm] = useState({ name: "", provider_type: "google_calendar", calendar_id: "primary", timezone: "Europe/Rome", access_token: "", api_key: "" });
  const createConnection = async () => {
    setBusy(true);
    try {
      await api.post("/appointments/connections", {
        name: connForm.name || PROVIDER_LABELS[connForm.provider_type], provider_type: connForm.provider_type,
        calendar_id: connForm.calendar_id, timezone: connForm.timezone,
        access_token: connForm.access_token || null, api_key: connForm.api_key || null,
      });
      toast.success("Connessione creata.");
      setCreatingConn(false); loadConnections();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const testConnection = async (id) => {
    setBusy(true);
    try {
      const { data } = await api.post(`/appointments/connections/${id}/test`);
      toast[data.status === "VERIFICATO" ? "success" : "info"](`Stato connessione: ${data.status}`);
      loadConnections();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const deleteConnection = async (id) => {
    setBusy(true);
    try { await api.delete(`/appointments/connections/${id}`); toast.success("Connessione eliminata."); loadConnections(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Proposte ----------
  const [proposalForm, setProposalForm] = useState({ connection_id: "", lead_id: "", lead_type: "aziende", duration_minutes: 30, search_days: 7 });
  const createProposal = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/appointments/proposals", {
        connection_id: proposalForm.connection_id, lead_id: proposalForm.lead_id, lead_type: proposalForm.lead_type,
        duration_minutes: Number(proposalForm.duration_minutes), search_days: Number(proposalForm.search_days),
      });
      toast.success(data.proposed_slots.length ? `${data.proposed_slots.length} slot proposti.` : "Proposta creata (nessuno slot: connessione non configurata o nessuna disponibilità).");
      setCreatingProposal(false); loadProposals(); setSelected(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const approveProposal = async (approve) => {
    setBusy(true);
    try {
      await api.post(`/appointments/proposals/${selected.id}/approve`, { approve });
      toast.success(approve ? "Proposta approvata." : "Proposta rifiutata.");
      const { data } = await api.get(`/appointments/proposals/${selected.id}`);
      setSelected(data); loadProposals();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const bookSlot = async (slotIndex) => {
    setBusy(true);
    try {
      await api.post(`/appointments/proposals/${selected.id}/book`, { slot_index: slotIndex, confirm: true });
      toast.success("Prenotazione avviata: in elaborazione.");
      loadBookings();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Prenotazioni ----------
  const cancelBooking = async (id) => {
    const reason = window.prompt("Motivo della cancellazione:");
    if (!reason || !reason.trim()) return;
    setBusy(true);
    try { await api.post(`/appointments/bookings/${id}/cancel`, { reason }); toast.success("Prenotazione cancellata."); loadBookings(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Appointment Setter — laboratorio"
        subtitle="Proposta e prenotazione reale di appuntamenti da lead approvati. Nessuna prenotazione senza conferma verificabile del provider."
        actions={
          <div className="flex items-center gap-2">
            <button data-testid="new-appt-connection" onClick={() => setCreatingConn(true)}
              className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-2 text-sm hover:bg-muted/50 transition-colors duration-200">
              <LinkIcon className="w-4 h-4" /> Nuova connessione
            </button>
            <button data-testid="new-appt-proposal" onClick={() => setCreatingProposal(true)}
              className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 transition-colors duration-200">
              <Plus className="w-4 h-4" /> Nuova proposta
            </button>
          </div>
        } />

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
        <div className="space-y-6">
          <div>
            <h2 className="font-display text-sm label-caps mb-2">Connessioni calendario</h2>
            {connections.length === 0 ? <Empty text="Nessuna connessione." /> : (
              <div className="space-y-2" data-testid="appt-connections-list">
                {connections.map((c) => (
                  <Card key={c.id} className="p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm truncate">{c.name}</span>
                      <StatusBadge status={c.status} />
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">{PROVIDER_LABELS[c.provider_type] || c.provider_type}</div>
                    <div className="flex gap-2 mt-2">
                      <button onClick={() => testConnection(c.id)} disabled={busy}
                        className="text-[11px] text-primary hover:underline flex items-center gap-1"><RefreshCw className="w-3 h-3" /> Testa</button>
                      <button onClick={() => deleteConnection(c.id)} disabled={busy}
                        className="text-[11px] text-red-400 hover:underline flex items-center gap-1"><Trash2 className="w-3 h-3" /> Elimina</button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>

          <div>
            <h2 className="font-display text-sm label-caps mb-2">Proposte</h2>
            {proposals.items.length === 0 ? <Empty text="Nessuna proposta ancora." /> : (
              <>
                <div className="space-y-2" data-testid="appt-proposals-list">
                  {proposals.items.map((p) => (
                    <Card key={p.id} className={`p-3 cursor-pointer ${selected?.id === p.id ? "border-primary" : ""}`}
                      onClick={() => setSelected(p)}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs truncate">{p.lead_id}</span>
                        <StatusBadge status={p.status} />
                      </div>
                      <div className="text-[11px] text-muted-foreground mt-1">{(p.proposed_slots || []).length} slot proposti</div>
                    </Card>
                  ))}
                </div>
                <Pager data={proposals} onPage={loadProposals} />
              </>
            )}
          </div>

          <div>
            <h2 className="font-display text-sm label-caps mb-2">Prenotazioni</h2>
            {bookings.items.length === 0 ? <Empty text="Nessuna prenotazione ancora." /> : (
              <>
                <div className="space-y-2" data-testid="appt-bookings-list">
                  {bookings.items.map((b) => (
                    <Card key={b.id} className="p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-mono">{b.start?.slice(0, 16).replace("T", " ")}</span>
                        <StatusBadge status={b.status} />
                      </div>
                      {b.status === "CONFERMATA" && (
                        <button onClick={() => cancelBooking(b.id)} disabled={busy}
                          className="mt-2 text-[11px] text-red-400 hover:underline flex items-center gap-1"><XCircle className="w-3 h-3" /> Cancella</button>
                      )}
                    </Card>
                  ))}
                </div>
                <Pager data={bookings} onPage={loadBookings} />
              </>
            )}
          </div>
        </div>

        <div>
          {!selected ? <Empty text="Seleziona o crea una proposta di appuntamento." /> : (
            <Card className="p-5">
              <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
                <div>
                  <h3 className="font-display text-lg font-medium">Proposta — {selected.lead_id}</h3>
                  <div className="text-xs text-muted-foreground mt-1">Lead: {selected.lead_type} · Durata: {selected.duration_minutes} min</div>
                </div>
                <StatusBadge status={selected.status} />
              </div>

              {!selected.connection_configured && (
                <div className="mb-4 text-xs rounded-sm border border-amber-500/30 bg-amber-500/10 text-amber-400 px-3 py-2">
                  Connessione calendario non configurata: nessuno slot reale disponibile finché non collegata.
                </div>
              )}

              {selected.status === "IN_ATTESA_APPROVAZIONE" && canApprove && (
                <div className="flex gap-2 mb-4">
                  <button data-testid="appt-approve-btn" onClick={() => approveProposal(true)} disabled={busy}
                    className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-1.5 text-sm hover:opacity-90">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Approva
                  </button>
                  <button onClick={() => approveProposal(false)} disabled={busy}
                    className="flex items-center gap-1.5 border border-red-500/40 text-red-400 rounded-sm px-3 py-1.5 text-sm hover:bg-red-500/10">
                    <XCircle className="w-3.5 h-3.5" /> Rifiuta
                  </button>
                </div>
              )}

              <div className="label-caps mb-2 flex items-center gap-1.5"><CalendarClock className="w-3.5 h-3.5" /> Slot proposti</div>
              {(selected.proposed_slots || []).length === 0 ? <Empty text="Nessuno slot disponibile." /> : (
                <div className="space-y-2" data-testid="appt-slots-list">
                  {selected.proposed_slots.map((s, i) => (
                    <div key={i} className="flex items-center justify-between border border-border/60 rounded-sm px-3 py-2 text-xs">
                      <span>{s.start?.slice(0, 16).replace("T", " ")} → {s.end?.slice(11, 16)}</span>
                      {selected.status === "APPROVATA" && (
                        <button onClick={() => bookSlot(i)} disabled={busy}
                          className="rounded-sm bg-primary text-primary-foreground px-2 py-1 hover:opacity-90">Prenota</button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}
        </div>
      </div>

      {creatingConn && (
        <Modal onClose={() => setCreatingConn(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Nuova connessione calendario</h3>
          <div className="space-y-3">
            <Field label="Nome" value={connForm.name} onChange={(v) => setConnForm({ ...connForm, name: v })} />
            <div>
              <div className="label-caps mb-1">Provider</div>
              <select value={connForm.provider_type} onChange={(e) => setConnForm({ ...connForm, provider_type: e.target.value })}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm">
                <option value="google_calendar">Google Calendar</option>
                <option value="microsoft_graph">Microsoft Graph</option>
                <option value="calendly">Calendly</option>
              </select>
            </div>
            {connForm.provider_type === "calendly" ? (
              <Field label="Personal Access Token" value={connForm.api_key} onChange={(v) => setConnForm({ ...connForm, api_key: v })} />
            ) : (
              <Field label="Access token (avanzato/test — normalmente via OAuth)" value={connForm.access_token} onChange={(v) => setConnForm({ ...connForm, access_token: v })} />
            )}
            <Field label="Fuso orario" value={connForm.timezone} onChange={(v) => setConnForm({ ...connForm, timezone: v })} />
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={createConnection} disabled={busy}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Crea</button>
            <button onClick={() => setCreatingConn(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {creatingProposal && (
        <Modal onClose={() => setCreatingProposal(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Nuova proposta di appuntamento</h3>
          <div className="space-y-3">
            <div>
              <div className="label-caps mb-1">Connessione</div>
              <select value={proposalForm.connection_id} onChange={(e) => setProposalForm({ ...proposalForm, connection_id: e.target.value })}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm">
                <option value="">— seleziona —</option>
                {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <Field label="ID lead (da Lead Generation — approvato)" value={proposalForm.lead_id} onChange={(v) => setProposalForm({ ...proposalForm, lead_id: v })} />
            <div>
              <div className="label-caps mb-1">Tipo lead</div>
              <select value={proposalForm.lead_type} onChange={(e) => setProposalForm({ ...proposalForm, lead_type: e.target.value })}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm">
                <option value="aziende">Azienda</option>
                <option value="persone">Persona</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Durata (minuti)" type="number" value={proposalForm.duration_minutes} onChange={(v) => setProposalForm({ ...proposalForm, duration_minutes: v })} />
              <Field label="Giorni di ricerca" type="number" value={proposalForm.search_days} onChange={(v) => setProposalForm({ ...proposalForm, search_days: v })} />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={createProposal} disabled={busy || !proposalForm.connection_id || !proposalForm.lead_id}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Crea proposta</button>
            <button onClick={() => setCreatingProposal(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Field({ label, value, onChange, type = "text" }) {
  return (
    <div>
      <div className="label-caps mb-1">{label}</div>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)}
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
