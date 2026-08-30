import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card } from "@/components/Primitives";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";
import { toast } from "sonner";
import { ShieldAlert, FlaskConical } from "lucide-react";

export default function Settings() {
  const [s, setS] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const { hasRole } = useAuth();
  const { refresh } = useSystem();
  const isAdmin = hasRole("ADMIN");

  const load = () => api.get("/settings").then((r) => setS(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const toggle = async (enable) => {
    try {
      await api.put("/settings/real-mode", { enable, confirm: true });
      toast.success(enable ? "Modalità AI REALE attivata (nessuna chiamata automatica)" : "Tornato in SIMULAZIONE");
      setConfirm(false); load(); refresh();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const real = s?.ai_real_mode;
  const ready = s?.can_enable_real_mode;

  return (
    <div>
      <PageHeader title="Impostazioni" subtitle="Controllo della modalità operativa del sistema." />
      <Card className={`p-6 border ${real ? "border-red-500/40" : "border-amber-500/40"}`}>
        <div className="flex items-center gap-2 mb-2">
          {real ? <ShieldAlert className="w-5 h-5 text-red-500" /> : <FlaskConical className="w-5 h-5 text-amber-500" />}
          <h2 className="font-display text-xl font-medium">Interruttore AI REALE</h2>
        </div>
        <p className="text-sm text-muted-foreground mb-4 max-w-2xl">
          In SIMULAZIONE nessuna chiamata AI reale viene effettuata. L'attivazione della modalità REALE
          richiede: almeno una connessione AI verificata, un budget configurato, conferma esplicita e ruolo ADMIN.
          L'attivazione non effettua alcuna chiamata automaticamente.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          <Cond ok={s?.verified_connections > 0} label={`Connessioni verificate: ${s?.verified_connections ?? 0}`} />
          <Cond ok={s?.budget_configured} label="Budget configurato" />
          <Cond ok={isAdmin} label="Ruolo ADMIN" />
        </div>

        <div className="flex items-center gap-3">
          <span data-testid="current-mode" className={`font-mono text-sm px-3 py-1.5 rounded-sm border ${real ? "border-red-500/30 bg-red-500/10 text-red-500" : "border-amber-500/30 bg-amber-500/10 text-amber-500"}`}>
            {real ? "MODALITÀ REALE" : "MODALITÀ SIMULAZIONE"}
          </span>
          {isAdmin && (real
            ? <button data-testid="disable-real" onClick={() => toggle(false)} className="rounded-sm border border-border px-4 py-2 text-sm hover:bg-muted/50 transition-colors duration-200">Torna a SIMULAZIONE</button>
            : <button data-testid="enable-real" disabled={!ready} onClick={() => setConfirm(true)} className="rounded-sm bg-red-600 text-white px-4 py-2 text-sm hover:bg-red-500 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40">Attiva AI REALE</button>
          )}
        </div>
        {!ready && !real && <p className="text-xs text-amber-400 mt-2">Prerequisiti non soddisfatti: configura una connessione AI verificata e un budget.</p>}
      </Card>

      {confirm && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={() => setConfirm(false)}>
          <div className="bg-card border border-red-500/40 rounded-sm p-6 w-full max-w-md shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-display text-lg font-medium mb-2 flex items-center gap-2"><ShieldAlert className="w-5 h-5 text-red-500" /> Conferma attivazione AI REALE</h3>
            <p className="text-sm text-muted-foreground mb-4">
              Da questo momento saranno possibili chiamate AI reali (a costo). Nessuna chiamata verrà eseguita automaticamente:
              ogni esecuzione richiederà comunque approvazione.
            </p>
            <div className="flex gap-2">
              <button data-testid="confirm-real" onClick={() => toggle(true)} className="bg-red-600 text-white rounded-sm px-4 py-2 text-sm">Confermo, attiva</button>
              <button onClick={() => setConfirm(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Cond({ ok, label }) {
  return (
    <div className={`flex items-center gap-2 text-sm rounded-sm border px-3 py-2 ${ok ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : "border-border text-muted-foreground"}`}>
      <span className="font-mono">{ok ? "✓" : "○"}</span> {label}
    </div>
  );
}
