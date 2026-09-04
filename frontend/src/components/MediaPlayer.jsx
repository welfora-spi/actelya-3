import { Download, Loader2, AlertTriangle, Clock, FileQuestion } from "lucide-react";

/**
 * Lettore multimediale riutilizzabile per i risultati degli agenti (video,
 * immagine, audio). Non assume mai che il media sia pronto: se `src` manca o
 * `status` non è un esito riproducibile, mostra sempre uno stato/messaggio
 * chiaro invece di un player vuoto o rotto. Mai un placeholder spacciato per
 * contenuto reale.
 *
 * Props:
 * - kind: "video" | "image" | "audio" (obbligatorio se src è presente)
 * - src: URL del media pronto, oppure null/undefined se non ancora disponibile
 * - status: stringa di stato applicativo (es. "IN_GENERAZIONE", "VIDEO_PRONTO", "FALLITO"...)
 * - message: messaggio leggibile da mostrare quando non c'è un media pronto
 * - downloadable: se true e src presente, mostra anche un link di download
 */
export function MediaPlayer({ kind = "video", src, status, message, downloadable = false }) {
  if (src) {
    return (
      <div className="space-y-2">
        <div className="rounded-sm overflow-hidden border border-border/60 bg-black/40">
          {kind === "video" && (
            <video data-testid="media-player-video" src={src} controls className="w-full max-h-[480px] mx-auto" />
          )}
          {kind === "image" && (
            <img data-testid="media-player-image" src={src} alt="Risultato generato" className="w-full max-h-[480px] object-contain mx-auto" />
          )}
          {kind === "audio" && (
            <audio data-testid="media-player-audio" src={src} controls className="w-full p-3" />
          )}
        </div>
        {downloadable && (
          <a href={src} target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors duration-200">
            <Download className="w-3.5 h-3.5" /> Apri / scarica originale
          </a>
        )}
      </div>
    );
  }

  const { Icon, tone } = _statusVisual(status);
  return (
    <div data-testid="media-player-not-ready"
      className={`rounded-sm border border-dashed px-4 py-8 text-center text-sm ${tone}`}>
      <Icon className="w-5 h-5 mx-auto mb-2 opacity-70" />
      <div className="font-mono text-xs uppercase tracking-wide opacity-80">{status || "NON_DISPONIBILE"}</div>
      <div className="mt-1 text-muted-foreground">{message || "Il media non è ancora pronto."}</div>
    </div>
  );
}

function _statusVisual(status) {
  if (status === "IN_CODA" || status === "IN_GENERAZIONE") return { Icon: Loader2, tone: "border-blue-500/30 text-blue-400" };
  if (status === "FALLITO" || status === "BLOCCATO") return { Icon: AlertTriangle, tone: "border-red-500/30 text-red-400" };
  if (status === "ESITO_INCERTO") return { Icon: Clock, tone: "border-amber-500/30 text-amber-400" };
  return { Icon: FileQuestion, tone: "border-border/60 text-muted-foreground" };
}
