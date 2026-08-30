import { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card } from "@/components/Primitives";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";
import { toast } from "sonner";

const FIELDS = [
  ["ragione_sociale", "Ragione sociale"], ["nome_commerciale", "Nome commerciale"],
  ["settore", "Settore"], ["descrizione_attivita", "Descrizione attività", true],
  ["prodotti_servizi", "Prodotti e servizi", true], ["proposta_valore", "Proposta di valore", true],
  ["pubblico_target", "Pubblico target"], ["territori_serviti", "Territori serviti"],
  ["tono_di_voce", "Tono di voce"], ["linee_guida_brand", "Linee guida del brand", true],
  ["obiettivi_commerciali", "Obiettivi commerciali", true], ["canali_utilizzati", "Canali utilizzati"],
  ["sito_web", "Sito web"], ["contatti_aziendali", "Contatti aziendali"],
  ["firma_email", "Firma email", true], ["disclaimer", "Disclaimer", true],
  ["informazioni_compliance", "Informazioni di compliance", true], ["limiti_operativi", "Limiti operativi", true],
  ["attivita_vietate", "Attività vietate", true], ["budget", "Budget"],
  ["orari", "Orari"], ["kpi_principali", "KPI principali", true],
];

export default function OrgProfile() {
  const [form, setForm] = useState({});
  const { hasRole } = useAuth();
  const { refresh } = useSystem();
  const canEdit = hasRole("ADMIN", "OPERATORE");

  useEffect(() => { api.get("/org/profile").then((r) => setForm(r.data || {})).catch(() => {}); }, []);

  const save = async () => {
    try {
      const payload = {}; FIELDS.forEach(([k]) => payload[k] = form[k] || "");
      const { data } = await api.put("/org/profile", payload);
      setForm(data); refresh(); toast.success("Profilo salvato");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <PageHeader title="Profilo aziendale" subtitle="Dati usati dagli agenti. I dati personali sono minimizzati e modificabili."
        actions={canEdit && <button data-testid="profile-save" onClick={save} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200">Salva profilo</button>} />
      <Card className="p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {FIELDS.map(([k, label, area]) => (
            <div key={k} className={area ? "md:col-span-2" : ""}>
              <label className="label-caps block mb-1">{label}</label>
              {area ? (
                <textarea data-testid={`profile-${k}`} disabled={!canEdit} rows={2} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                  className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm resize-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none disabled:opacity-60" />
              ) : (
                <input data-testid={`profile-${k}`} disabled={!canEdit} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                  className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none disabled:opacity-60" />
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
