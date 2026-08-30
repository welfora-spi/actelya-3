import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { Timeline } from "@/components/Timeline";

export default function Executions() {
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [params] = useSearchParams();

  const load = useCallback(() => {
    api.get("/executions").then((r) => {
      setRows(r.data);
      if (!selected && r.data.length) {
        const focus = params.get("focus");
        setSelected(focus && r.data.find((x) => x.id === focus) ? focus : r.data[0].id);
      }
    }).catch(() => {});
  }, [selected, params]);

  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, [load]);
  useEffect(() => {
    if (!selected) return;
    const fetchDetail = () => api.get(`/executions/${selected}`).then((r) => setDetail(r.data)).catch(() => {});
    fetchDetail();
    const t = setInterval(fetchDetail, 3000);
    return () => clearInterval(t);
  }, [selected]);

  return (
    <div>
      <PageHeader title="Esecuzioni" subtitle="Timeline unica a 3 sezioni. Stati tecnici, deliverable e azione esterna sono separati." />
      {rows.length === 0 ? <Empty text="Nessuna esecuzione. Crea e approva un obiettivo." /> : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-2 lg:col-span-1" data-testid="executions-list">
            {rows.map((e) => (
              <button key={e.id} onClick={() => setSelected(e.id)} data-testid={`exec-row-${e.id}`}
                className={`w-full text-left p-3 rounded-sm border transition-colors duration-200 ${selected === e.id ? "border-primary bg-secondary" : "border-border/60 hover:bg-muted/50"}`}>
                <div className="font-mono text-xs text-muted-foreground truncate">{e.id}</div>
                <div className="text-sm truncate mt-0.5">{e.goal_text}</div>
                <div className="flex flex-wrap gap-1 mt-2">
                  <StatusBadge status={e.execution_status} />
                  <StatusBadge status={e.deliverable_status} />
                  <StatusBadge status={e.action_status} />
                </div>
              </button>
            ))}
          </div>

          <div className="lg:col-span-2 space-y-4">
            {detail?.execution && (
              <>
                <Timeline execution={detail.execution} />
                <Card className="p-5">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    <Metric label="Costo reale (sim)" value={`$${(detail.execution.real_cost || 0).toFixed(5)}`} />
                    <Metric label="Token in/out" value={`${detail.execution.tokens_input}/${detail.execution.tokens_output}`} />
                    <Metric label="Preventivo prob." value={`$${(detail.execution.estimate?.cost_probable || 0).toFixed(5)}`} />
                    <Metric label="Agenti" value={detail.execution.agents.length} />
                  </div>
                  {detail.execution.warnings?.length > 0 && (
                    <div className="mt-4">
                      <div className="label-caps mb-1">Warning</div>
                      <ul className="text-xs text-yellow-400 list-disc pl-4 space-y-0.5">
                        {detail.execution.warnings.map((w, i) => <li key={i}>{w}</li>)}
                      </ul>
                    </div>
                  )}
                </Card>

                <Card className="p-5">
                  <div className="label-caps mb-2">Agent runs</div>
                  <div className="space-y-1.5">
                    {detail.execution.agent_runs.map((r, i) => (
                      <div key={i} className="flex items-center justify-between text-sm border-b border-border/40 py-1.5 last:border-0">
                        <span>{r.agent_name}</span>
                        <span className="flex items-center gap-3 font-mono text-xs">
                          <span className="text-muted-foreground">{r.tokens_input}/{r.tokens_output} tok</span>
                          <span>${r.cost.toFixed(5)}</span>
                          <StatusBadge status={r.status} />
                        </span>
                      </div>
                    ))}
                  </div>
                </Card>

                {detail.deliverable && <EmailPreview d={detail.deliverable} />}
                {detail.execution.execution_status === "COMPLETATA" && detail.execution.deliverable_status !== "BLOCCATO" && detail.execution.action_status === "NON_RICHIESTA" && (
                  <div className="text-sm border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 rounded-sm px-3 py-2" data-testid="draft-not-sent">
                    Bozza prodotta ma non inviata.
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return <div><div className="label-caps">{label}</div><div className="font-mono mt-0.5">{value}</div></div>;
}

export function EmailPreview({ d }) {
  const c = d.content || {};
  return (
    <Card className="p-0 overflow-hidden" >
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/60 bg-muted/30">
        <span className="label-caps">Deliverable email</span>
        <StatusBadge status={d.status} testid="deliverable-status-badge" />
      </div>
      <div className="p-5 space-y-3" data-testid="email-preview">
        <div><span className="label-caps">Oggetto</span><div className="text-sm font-medium mt-0.5">{c.oggetto || c.hook}</div></div>
        <div className="whitespace-pre-wrap text-sm text-foreground/90 border-l-2 border-border pl-4">{c.contenuto_completo}</div>
        <div><span className="label-caps">CTA</span><div className="text-sm mt-0.5">{c.cta}</div></div>
        {d.warnings?.length > 0 && <div className="text-xs text-yellow-400">Avvisi: {d.warnings.join(" ")}</div>}
      </div>
    </Card>
  );
}
