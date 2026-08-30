import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";

export default function Audit() {
  const [rows, setRows] = useState([]);
  const load = useCallback(() => { api.get("/audit?limit=300").then((r) => setRows(r.data)).catch(() => {}); }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  return (
    <div>
      <PageHeader title="Audit Log" subtitle="Ogni operazione rilevante è registrata. Nessun segreto (API key, password, token) viene mai memorizzato." />
      {rows.length === 0 ? <Empty text="Nessun evento." /> : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm" data-testid="audit-table">
            <thead className="border-b border-border/60">
              <tr className="[&>th]:label-caps [&>th]:text-left [&>th]:px-4 [&>th]:py-2.5">
                <th>Data</th><th>Attore</th><th>Azione</th><th>Entità</th><th>Stato</th><th>Dettagli</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border/40 hover:bg-muted/50 transition-colors duration-200 align-top">
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground whitespace-nowrap">{new Date(r.at).toLocaleString()}</td>
                  <td className="px-4 py-2 text-xs">{r.actor}</td>
                  <td className="px-4 py-2"><span className="text-[10px] font-mono border border-border rounded-sm px-1.5 py-0.5">{r.action}</span></td>
                  <td className="px-4 py-2 font-mono text-xs">{r.entity_type}{r.entity_id ? `:${r.entity_id.slice(0, 10)}` : ""}</td>
                  <td className="px-4 py-2 text-xs">{r.status === "OK" ? <span className="text-emerald-400">OK</span> : <span className="text-red-400">{r.status}</span>}</td>
                  <td className="px-4 py-2 font-mono text-[11px] text-muted-foreground max-w-xs truncate">{JSON.stringify(r.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
