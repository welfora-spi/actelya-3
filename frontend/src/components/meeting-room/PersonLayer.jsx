import { useState } from "react";
import { UserRound } from "lucide-react";

// Layer-persona: se agent.person_asset esiste, viene renderizzato SEMPRE a
// piena tela (position:absolute, inset:0) — nessun top/left/scale
// individuale: la persona è già collocata nella propria posizione dentro
// l'immagine stessa (stesso canvas 16:9 della base, 1680×945, sfondo
// trasparente). Questo evita qualunque nuovo disallineamento tra layer.
//
// Se l'asset manca (o il caricamento fallisce), mostra un placeholder
// COMPATTO ancorato a label_position — l'unica coordinata nota in assenza
// dell'immagine — mai un layer a piena tela inventato.
const EXPECTED_WIDTH = 1680;
const EXPECTED_HEIGHT = 945;

export default function PersonLayer({ agent }) {
  const [failed, setFailed] = useState(false);
  const hasAsset = Boolean(agent.person_asset) && !failed;

  const handleLoad = (e) => {
    if (process.env.NODE_ENV !== "development") return;
    const { naturalWidth: w, naturalHeight: h } = e.target;
    if (w !== EXPECTED_WIDTH || h !== EXPECTED_HEIGHT) {
      console.warn(
        `[PersonLayer] "${agent.agent_id}": dimensioni ${w}×${h}, attese ${EXPECTED_WIDTH}×${EXPECTED_HEIGHT} (stesso canvas della base)`
      );
    }
  };

  if (hasAsset) {
    return (
      <img
        src={agent.person_asset}
        alt={agent.role_name}
        data-testid={`person-layer-${agent.agent_id}`}
        style={{ zIndex: agent.z_index }}
        className="absolute inset-0 w-full h-full pointer-events-none"
        onLoad={handleLoad}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <div
      data-testid={`person-layer-placeholder-${agent.agent_id}`}
      style={{ top: agent.label_position.top, left: agent.label_position.left, zIndex: agent.z_index }}
      className="absolute -translate-x-1/2 -translate-y-[170%] w-9 h-9 rounded-full border-2 border-dashed border-white/40 bg-black/50 grid place-items-center pointer-events-none"
    >
      <UserRound className="w-4 h-4 text-white/50" strokeWidth={1.5} />
    </div>
  );
}
