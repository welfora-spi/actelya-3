import { cn } from "@/lib/utils";

const TONE_CLASSES = {
  slate: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  emerald: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  amber: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  blue: "bg-sky-500/15 text-sky-400 border-sky-500/30",
  red: "bg-red-500/15 text-red-400 border-red-500/30",
};

const DOT_CLASSES = {
  slate: "bg-slate-400",
  emerald: "bg-emerald-400",
  amber: "bg-amber-400",
  blue: "bg-sky-400",
  red: "bg-red-400",
};

export default function SeatStatusBadge({ label, tone = "slate", className, testid }) {
  return (
    <span
      data-testid={testid}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wide whitespace-nowrap",
        TONE_CLASSES[tone] || TONE_CLASSES.slate,
        className
      )}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full", DOT_CLASSES[tone] || DOT_CLASSES.slate)} />
      {label}
    </span>
  );
}
