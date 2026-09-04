import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, withCredentials: true });

// Alcuni asset (es. immagini flyer persistite, GET /flyer/assets/:id) sono
// serviti dal backend come percorso RELATIVO ("/api/..."): un <img>/<video>
// non passa dall'istanza axios sopra (che aggiunge credenziali/baseURL da
// sola), quindi va reso assoluto esplicitamente qui, in un solo punto.
export function absoluteAssetUrl(url) {
  if (!url) return url;
  if (/^https?:\/\//i.test(url)) return url; // gia' assoluto (es. URL esterno Runway/Requesty)
  return `${BACKEND_URL}${url}`;
}

export function formatApiError(detail) {
  if (detail == null) return "Errore imprevisto. Riprova.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export default api;
