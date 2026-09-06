import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { Wrench } from "lucide-react";

const CATEGORY_LABELS = {
  llm: "Cervello e modelli IA", web_research: "Ricerca e navigazione web", observability: "Monitoraggio tecnico",
  media_generation: "Immagini e video IA", audio: "Voce, audio e montaggio", brand_creative: "Grafica e Brand",
  social_network: "Social network", advertising: "Pubblicità", crm: "CRM",
  prospect_research: "Ricerca e qualificazione prospect", individual_comms: "Comunicazioni individuali",
  email_marketing: "Email marketing", calendar: "Calendari", analytics_seo: "Analytics e SEO", sms: "SMS",
  booking: "Prenotazione", local_business: "Attività locali", site_management: "Gestione siti",
  ecommerce: "E-commerce", documents: "Documenti e file", ocr: "OCR e documenti complessi",
  external_automation: "Automazioni esterne",
};

export default function ToolRegistry() {
  const [tools, setTools] = useState(null);
  const [categories, setCategories] = useState([]);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [agentFilter, setAgentFilter] = useState("");

  const load = useCallback(() => {
    const params = {};
    if (categoryFilter) params.category = categoryFilter;
    if (agentFilter) params.agent_id = agentFilter;
    api.get("/tool-registry", { params }).then((r) => {
      setTools(r.data.tools);
      setCategories(r.data.categories);
    }).catch(() => setTools([]));
  }, [categoryFilter, agentFilter]);

  useEffect(() => { load(); }, [load]);

  const grouped = (tools || []).reduce((acc, t) => {
    (acc[t.category] = acc[t.category] || []).push(t);
    return acc;
  }, {});

  return (
    <div data-testid="tool-registry-page">
      <PageHeader title="Registro strumenti professionali"
        subtitle="Catalogo canonico di ogni provider che ACTELYA può usare: stato reale per organizzazione, mai un nome soltanto." />

      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}
          className="bg-background border border-border rounded-sm px-3 py-2 text-sm">
          <option value="">Tutte le categorie</option>
          {categories.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c] || c}</option>)}
        </select>
        <input placeholder="Filtra per agent_id (es. lead-gen-specialist)" value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="bg-background border border-border rounded-sm px-3 py-2 text-sm flex-1 min-w-[220px]" />
      </div>

      {!tools ? <p className="text-sm text-muted-foreground">Caricamento…</p> : tools.length === 0 ? (
        <Empty text="Nessuno strumento corrisponde ai filtri." />
      ) : (
        <div className="space-y-6" data-testid="tool-registry-groups">
          {Object.entries(grouped).map(([cat, items]) => (
            <div key={cat}>
              <h2 className="font-display text-sm label-caps mb-2 flex items-center gap-1.5">
                <Wrench className="w-3.5 h-3.5" /> {CATEGORY_LABELS[cat] || cat}
              </h2>
              <div className="space-y-2">
                {items.map((t) => (
                  <Card key={t.tool_id} className="p-3" data-testid={`tool-${t.tool_id}`}>
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <span className="text-sm font-medium">{t.provider}</span>
                      <StatusBadge status={t.status} />
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      Agenti: {t.allowed_agents.join(", ")}
                    </div>
                    {t.note && <div className="text-[11px] text-muted-foreground mt-1 italic">{t.note}</div>}
                    {!t.code_complete && t.env_vars.length > 0 && (
                      <div className="text-[10px] font-mono text-muted-foreground mt-1">
                        Variabili previste: {t.env_vars.join(", ")}
                      </div>
                    )}
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
