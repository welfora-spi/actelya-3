import { FileText, CalendarDays, Image as ImageIcon, MoreVertical } from "lucide-react";
import { Card } from "@/components/Primitives";
import { DELIVERABLE_STATUS_META } from "./adapter";

const ICON_BY_TYPE = {
  strategy: FileText,
  editorial: CalendarDays,
  social: ImageIcon,
};

// Classi statiche (mai interpolate): Tailwind rileva solo stringhe letterali
// nel sorgente, un `bg-${tone}-400` costruito a runtime non verrebbe generato.
const DOT_TONE_CLASSES = {
  blue: "bg-sky-400",
  emerald: "bg-emerald-400",
  amber: "bg-amber-400",
  red: "bg-red-400",
};

export default function DeliverableCard({ deliverable, selected, onSelect }) {
  const Icon = ICON_BY_TYPE[deliverable.type] || FileText;
  const meta = DELIVERABLE_STATUS_META[deliverable.status];

  return (
    <Card
      className={`p-4 flex items-start gap-3 cursor-pointer transition-colors duration-200 hover:bg-muted/30 ${selected ? "border-primary/60" : ""}`}
      onClick={() => onSelect?.(deliverable)}
    >
      <div className="w-9 h-9 rounded-md bg-muted grid place-items-center shrink-0">
        <Icon className="w-4 h-4 text-muted-foreground" strokeWidth={1.75} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium truncate" data-testid={`deliverable-card-title-${deliverable.id}`}>
            {deliverable.title}
          </span>
          <MoreVertical className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        </div>
        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
          {meta && (
            <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
              <span className={`w-1.5 h-1.5 rounded-full ${DOT_TONE_CLASSES[meta.tone] || "bg-slate-400"}`} />
              {meta.label}
            </span>
          )}
          <span className="text-[10px] font-mono text-muted-foreground">v{deliverable.version}</span>
        </div>
      </div>
    </Card>
  );
}
