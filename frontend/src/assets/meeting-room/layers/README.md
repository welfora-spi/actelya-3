# Asset — Sala Riunioni (livelli)

Questa cartella riceverà gli asset grafici reali dell'architettura a livelli
di `RoomBackdrop.jsx`. Finché i file elencati qui sotto non esistono, l'app
mostra placeholder chiaramente identificati (nessuna immagine inventata).

## Specifiche comuni (obbligatorie per tutti i file)

- Canvas identico: **1680 × 945 px** (16:9), stessa inquadratura per tutti.
- Nessuna deformazione/ricentratura: la persona è già collocata nella propria
  posizione fissa dentro l'immagine — il codice non applica mai top/left/
  scale individuali, solo `position:absolute; inset:0`.
- Formato: WebP (preferito) o PNG.

## File attesi

| File | Contenuto | Sfondo |
|---|---|---|
| `meeting-room-base-empty.webp` | Sala, tavolo, tutte le sedie vuote, imprenditore a capotavola. Nessun collaboratore. | Opaco (fotografia reale) |
| `person-marketing.webp` | Solo Responsabile marketing, seduto/a in `left-1` | Trasparente |
| `person-social-media.webp` | Solo Social media manager, seduto/a in `left-2` | Trasparente |
| `person-advertising.webp` | Solo Specialista advertising, seduto/a in `left-3` | Trasparente |
| `person-lead-generation.webp` | Solo Lead generation specialist, seduto/a in `left-4` | Trasparente |
| `person-nurturing.webp` | Solo Specialista nurturing, seduto/a in `left-5` | Trasparente |
| `person-performance.webp` | Solo Analista performance, seduto/a in `right-1` | Trasparente |
| `person-appointment-setter.webp` | Solo Appointment setter, seduto/a in `right-2` | Trasparente |
| `person-copywriter.webp` | Solo Copywriter, seduto/a in `right-3` | Trasparente |
| `person-compliance.webp` | Solo Responsabile compliance, seduto/a in `right-4` | Trasparente |

Il Coordinatore ACTELYA non ha un asset persona (resta il riquadro digitale
sullo schermo, vedi `CoordinatorScreen.jsx`).

`left-*`/`right-*` sono i `seat_id` fissi definiti in `agentRegistry.js`,
coerenti con `design/actelya3-full-team-final-labeled-reference.png`.

## Come collegare un asset reale

In `agentRegistry.js`, per la voce corrispondente:

```js
import personMarketing from "@/assets/meeting-room/layers/person-marketing.webp";
// ...
{
  agent_id: "resp-marketing",
  // ...
  person_asset: personMarketing, // al posto di null
}
```

Per la base, in `RoomBackdrop.jsx`:

```js
import ROOM_BASE_PHOTO from "@/assets/meeting-room/layers/meeting-room-base-empty.webp";
```
