import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Send, CalendarClock, CheckCircle2, XCircle, BarChart3, RefreshCw, FlaskConical, Facebook, Instagram } from "lucide-react";

// item 13: stato connessione Meta (Facebook/Instagram) — SOLO lettura, mai
// un token in vista. "Non configurato" e' uno stato onesto, mai nascosto:
// la pubblicazione resta comunque disponibile in modalità simulata.
function ConnectorBadge({ icon: Icon, label, connected, statusLabel }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] rounded-sm border px-1.5 py-0.5 ${
      connected ? "border-emerald-500/40 text-emerald-400 bg-emerald-500/10" : "border-border/60 text-muted-foreground"
    }`}>
      <Icon className="w-3 h-3" /> {label}: {connected ? "Connesso" : statusLabel || "Non configurato"}
    </span>
  );
}

// Pannello di pubblicazione (item 14/15/16): visibile SOLO quando testo e
// media del progetto sorgente sono già entrambi approvati (il chiamante lo
// garantisce). Un solo pacchetto per canale alla volta viene mostrato (il
// più recente): "Annulla" permette di crearne uno nuovo per un canale
// diverso o dopo un ripensamento.
const CHANNELS = [
  { value: "instagram", label: "Instagram" },
  { value: "facebook", label: "Facebook" },
];

export default function SocialPublishingPanel({ sourceKind, sourceProjectId }) {
  const [packages, setPackages] = useState(null);
  const [channel, setChannel] = useState("instagram");
  const [busy, setBusy] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduleAt, setScheduleAt] = useState("");
  const [metrics, setMetrics] = useState(null);
  const [connectorStatus, setConnectorStatus] = useState(null);
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");
  const canApprovePublish = hasRole("ADMIN") || hasRole("APPROVATORE");

  const load = useCallback(() => {
    api.get("/social/publishing/packages", { params: { source_project_id: sourceProjectId } })
      .then((r) => setPackages(r.data))
      .catch(() => setPackages([]));
  }, [sourceProjectId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.get("/social/connectors/meta/status").then((r) => setConnectorStatus(r.data)).catch(() => setConnectorStatus(null));
  }, []);

  if (packages === null) return <p className="text-xs text-muted-foreground">Caricamento pubblicazione…</p>;

  const pkg = packages.find((p) => !["CANCELLED"].includes(p.status)) || null;

  const createPackage = async () => {
    setBusy(true);
    try {
      await api.post("/social/publishing/packages", { source_kind: sourceKind, source_project_id: sourceProjectId, channel });
      toast.success("Pacchetto di pubblicazione creato: in attesa di approvazione.");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const approve = async () => {
    setBusy(true);
    try { await api.post(`/social/publishing/packages/${pkg.id}/approve`); toast.success("Pubblicazione approvata."); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const cancel = async () => {
    setBusy(true);
    try { await api.post(`/social/publishing/packages/${pkg.id}/cancel`); toast.success("Pubblicazione annullata."); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const schedule = async () => {
    if (!scheduleAt) return;
    setBusy(true);
    try {
      await api.post(`/social/publishing/packages/${pkg.id}/schedule`, { scheduled_at: new Date(scheduleAt).toISOString() });
      toast.success("Pubblicazione programmata.");
      setScheduleOpen(false); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const publishNow = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/social/publishing/packages/${pkg.id}/publish`, { confirm: true });
      toast.success(data.dry_run ? "Pubblicazione eseguita in modalità dry-run (nessun connector reale configurato)." : "Pubblicato.");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const refreshMetrics = async () => {
    setBusy(true);
    try { const { data } = await api.post(`/social/publishing/packages/${pkg.id}/metrics/refresh`); setMetrics(data); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const resolveUncertain = async (foundId) => {
    const nota = window.prompt(
      foundId
        ? "Hai verificato su Meta che il post esiste davvero? Conferma con una nota:"
        : "Hai verificato su Meta che il post NON è stato pubblicato? Conferma con una nota:"
    );
    if (!nota || !nota.trim()) return;
    setBusy(true);
    try {
      await api.post(`/social/publishing/packages/${pkg.id}/resolve-uncertain`, {
        nota: nota.trim(), found_external_post_id: foundId || null,
      });
      toast.success("Esito incerto risolto.");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="border-t border-border/60 pt-3 space-y-2.5" data-testid="social-publishing-panel">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="label-caps">Pubblicazione</span>
        {pkg && <StatusBadge status={pkg.status} />}
        {pkg?.dry_run && (
          <span className="text-[11px] flex items-center gap-1 text-amber-400">
            <FlaskConical className="w-3.5 h-3.5" /> Simulata (dry-run): nessun connector reale attivo per questo canale
          </span>
        )}
      </div>

      {/* item 13: stato connessione Meta, sempre visibile e mai un token in vista. */}
      {connectorStatus && (
        <div className="flex items-center gap-2 flex-wrap">
          <ConnectorBadge icon={Facebook} label="Facebook" connected={connectorStatus.facebook_page?.connected}
            statusLabel={connectorStatus.configured ? connectorStatus.facebook_page?.status : "Non configurato"} />
          <ConnectorBadge icon={Instagram} label="Instagram" connected={connectorStatus.instagram?.connected}
            statusLabel={connectorStatus.configured ? connectorStatus.instagram?.status : "Non configurato"} />
          {!connectorStatus.configured && (
            <span className="text-[11px] text-muted-foreground">Configura le credenziali Meta in Connessioni e API per abilitare la pubblicazione reale.</span>
          )}
        </div>
      )}

      {!pkg && (
        <div className="flex items-center gap-2 flex-wrap">
          <select value={channel} onChange={(e) => setChannel(e.target.value)}
            className="bg-background border border-border rounded-sm px-2 py-1.5 text-xs">
            {CHANNELS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <button onClick={createPackage} disabled={busy}
            className="flex items-center gap-1.5 rounded-sm border border-primary/50 text-primary px-2.5 py-1.5 text-xs hover:bg-primary/10">
            <Send className="w-3.5 h-3.5" /> Prepara pubblicazione
          </button>
        </div>
      )}

      {pkg && (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">
            Canale: <b className="text-foreground">{pkg.channel}</b>
            {pkg.scheduled_at && <> · Programmata per: <b className="text-foreground">{new Date(pkg.scheduled_at).toLocaleString("it-IT")}</b></>}
          </div>

          {pkg.status === "AWAITING_APPROVAL" && (
            <div className="flex gap-2 flex-wrap">
              {canApprovePublish && (
                <button onClick={approve} disabled={busy}
                  className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-2.5 py-1.5 text-xs">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Approva pubblicazione
                </button>
              )}
              <button onClick={cancel} disabled={busy} className="flex items-center gap-1.5 rounded-sm border border-border px-2.5 py-1.5 text-xs">
                <XCircle className="w-3.5 h-3.5" /> Annulla
              </button>
            </div>
          )}

          {(pkg.status === "APPROVED" || pkg.status === "SCHEDULED") && (
            <div className="flex gap-2 flex-wrap items-center">
              {isAdmin && (
                <button onClick={publishNow} disabled={busy}
                  className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-2.5 py-1.5 text-xs">
                  <Send className="w-3.5 h-3.5" /> Pubblica ora
                </button>
              )}
              <button onClick={() => setScheduleOpen((v) => !v)} className="flex items-center gap-1.5 rounded-sm border border-border px-2.5 py-1.5 text-xs">
                <CalendarClock className="w-3.5 h-3.5" /> Programma
              </button>
              <button onClick={cancel} disabled={busy} className="flex items-center gap-1.5 rounded-sm border border-border px-2.5 py-1.5 text-xs">
                <XCircle className="w-3.5 h-3.5" /> Annulla
              </button>
            </div>
          )}
          {scheduleOpen && (
            <div className="flex items-center gap-2">
              <input type="datetime-local" value={scheduleAt} onChange={(e) => setScheduleAt(e.target.value)}
                className="bg-background border border-border rounded-sm px-2 py-1.5 text-xs" />
              <button onClick={schedule} disabled={busy || !scheduleAt} className="rounded-sm bg-primary text-primary-foreground px-2.5 py-1.5 text-xs disabled:opacity-40">Conferma</button>
            </div>
          )}

          {pkg.status === "PUBLISH_UNCERTAIN" && (
            <div className="space-y-2">
              <div className="text-xs rounded-sm border border-amber-500/30 bg-amber-500/10 text-amber-400 px-3 py-2">
                Esito incerto: la richiesta è partita ma non è arrivata risposta in tempo. Verifica manualmente su Meta prima di continuare.
                {pkg.error_message && <div className="mt-1 opacity-80">{pkg.error_message}</div>}
              </div>
              {isAdmin && (
                <div className="flex gap-2 flex-wrap">
                  <button onClick={() => resolveUncertain(null)} disabled={busy} className="flex items-center gap-1.5 rounded-sm border border-border px-2.5 py-1.5 text-xs">
                    Non pubblicato — riprova
                  </button>
                  <button onClick={() => {
                    const id = window.prompt("ID del post trovato manualmente su Meta:");
                    if (id && id.trim()) resolveUncertain(id.trim());
                  }} disabled={busy} className="flex items-center gap-1.5 rounded-sm border border-emerald-500/40 text-emerald-400 px-2.5 py-1.5 text-xs">
                    Pubblicato — segna come completato
                  </button>
                </div>
              )}
            </div>
          )}

          {pkg.status === "FAILED" && (
            <div className="space-y-2">
              <div className="text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2">
                [{pkg.error_code}] {pkg.error_message}
              </div>
              {isAdmin && (
                <button onClick={publishNow} disabled={busy} className="flex items-center gap-1.5 rounded-sm border border-primary/50 text-primary px-2.5 py-1.5 text-xs">
                  <RefreshCw className="w-3.5 h-3.5" /> Riprova
                </button>
              )}
            </div>
          )}

          {pkg.status === "PUBLISHED" && (
            <div className="space-y-2">
              <button onClick={refreshMetrics} disabled={busy} className="flex items-center gap-1.5 rounded-sm border border-border px-2.5 py-1.5 text-xs hover:bg-muted/50">
                <BarChart3 className="w-3.5 h-3.5" /> Aggiorna metriche
              </button>
              {metrics && (
                metrics.data_available ? (
                  <div className="grid grid-cols-4 gap-2 text-xs">
                    <Metric l="Impressions" v={metrics.impressions} /><Metric l="Reach" v={metrics.reach} />
                    <Metric l="Like" v={metrics.likes} /><Metric l="Commenti" v={metrics.comments} />
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">{metrics.note || "Nessun dato disponibile: nessun connector reale configurato per questo canale."}</p>
                )
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({ l, v }) {
  return (
    <div className="border border-border/60 rounded-sm px-2 py-1.5">
      <div className="label-caps">{l}</div>
      <div className="font-mono">{v ?? "non disponibile"}</div>
    </div>
  );
}
