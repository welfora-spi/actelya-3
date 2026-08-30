export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex items-start justify-between mb-6 gap-4 flex-wrap">
      <div>
        <h1 className="font-display text-2xl sm:text-3xl tracking-tight font-semibold">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground mt-1 max-w-2xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ children, className = "" }) {
  return <div className={`bg-card border border-border/60 rounded-sm ${className}`}>{children}</div>;
}

export function Empty({ text }) {
  return <div className="text-sm text-muted-foreground py-10 text-center border border-dashed border-border/60 rounded-sm">{text}</div>;
}
