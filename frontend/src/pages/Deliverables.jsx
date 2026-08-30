import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, Empty } from "@/components/Primitives";
import { EmailPreview } from "@/pages/Executions";

export default function Deliverables() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/deliverables").then((r) => setRows(r.data)).catch(() => {}); }, []);
  return (
    <div>
      <PageHeader title="Deliverable / Contenuti"
        subtitle="Solo i deliverable persistiti e validi sono conteggiati come contenuto prodotto." />
      {rows.length === 0 ? <Empty text="Nessun deliverable prodotto." /> : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="deliverables-list">
          {rows.map((d) => <EmailPreview key={d.id} d={d} />)}
        </div>
      )}
    </div>
  );
}
