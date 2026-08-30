import { useState } from "react";
import { Sparkles, Send } from "lucide-react";
import { toast } from "sonner";

// Barra di richiesta: input reale e funzionante, ma NON collegata ad alcuna
// azione esterna o pubblicazione (come richiesto) — in questa fase registra
// solo un feedback locale, nessuna chiamata di rete.
export default function RequestBar() {
  const [text, setText] = useState("");

  const submit = () => {
    if (!text.trim()) return;
    toast.info("Richiesta registrata (demo): non è ancora collegata alla squadra reale.");
    setText("");
  };

  return (
    <div className="flex items-center gap-2 rounded-full border border-border/60 bg-card px-4 py-2.5">
      <Sparkles className="w-4 h-4 text-muted-foreground shrink-0" strokeWidth={1.75} />
      <input
        data-testid="meeting-request-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="Scrivi la tua richiesta alla squadra…"
        className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground min-w-0"
      />
      <button
        type="button"
        data-testid="meeting-request-send"
        onClick={submit}
        disabled={!text.trim()}
        aria-label="Invia richiesta"
        className="w-8 h-8 rounded-full bg-primary text-primary-foreground grid place-items-center shrink-0 hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40"
      >
        <Send className="w-3.5 h-3.5" strokeWidth={1.75} />
      </button>
    </div>
  );
}
