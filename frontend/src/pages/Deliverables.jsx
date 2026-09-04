import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { EmailPreview } from "@/pages/Executions";
import MultimodalProjectPanel from "@/components/MultimodalProjectPanel";

// Deliverable multimodale (video/immagine) prodotto da una skill REALE (vedi
// brain/skills.py): renderizzato QUI, per intero (contenuto, verifica
// semantica, generazione/approvazione) tramite il renderer universale
// condiviso con Sala Riunioni -- MAI solo un rimando a una pagina laboratorio.
const REAL_SKILL_PANEL_KIND = { video_reel_project: "reel", flyer_project: "flyer" };

function RealSkillDeliverableCard({ d }) {
  const kind = REAL_SKILL_PANEL_KIND[d.deliverable_type];
  const projectId = d.content?.reel_project_id || d.content?.flyer_project_id;
  return (
    <Card className="p-5">
      <MultimodalProjectPanel kind={kind} projectId={projectId} />
    </Card>
  );
}

export default function Deliverables() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/deliverables").then((r) => setRows(r.data)).catch(() => {}); }, []);
  return (
    <div>
      <PageHeader title="Deliverable / Contenuti"
        subtitle="Solo i deliverable persistiti e validi sono conteggiati come contenuto prodotto." />
      {rows.length === 0 ? <Empty text="Nessun deliverable prodotto." /> : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="deliverables-list">
          {rows.map((d) => REAL_SKILL_PANEL_KIND[d.deliverable_type]
            ? <RealSkillDeliverableCard key={d.id} d={d} />
            : <EmailPreview key={d.id} d={d} />)}
        </div>
      )}
    </div>
  );
}
