import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, withCredentials: true });

// Sessione: il cookie access_token scade dopo un'ora (backend/app/config.py
// ACCESS_TOKEN_MINUTES). Un 401 tenta UNA volta il refresh gia' esposto dal
// backend (POST /auth/refresh, cookie refresh_token) e ripete la richiesta
// originale; piu' 401 arrivati insieme condividono lo stesso tentativo di
// refresh (nessuna raffica di refresh paralleli). Login e refresh restano
// esclusi dal recupero per non creare un loop. Se anche il refresh fallisce
// la sessione e' davvero finita: si avvisa l'app invece di continuare a
// interrogare in silenzio endpoint autenticati senza esito.
const AUTH_ROUTES_EXCLUDED_FROM_RETRY = ["/auth/login", "/auth/refresh"];

let sessionExpiredHandler = null;
export function setSessionExpiredHandler(fn) {
  sessionExpiredHandler = fn;
}

let refreshPromise = null;

export async function handleAuthRetry(error) {
  const { config, response } = error;
  if (!config || !response || response.status !== 401 || config.__authRetried ||
      AUTH_ROUTES_EXCLUDED_FROM_RETRY.includes(config.url)) {
    return Promise.reject(error);
  }
  config.__authRetried = true;
  if (!refreshPromise) {
    refreshPromise = api.post("/auth/refresh").finally(() => { refreshPromise = null; });
  }
  try {
    await refreshPromise;
  } catch {
    if (sessionExpiredHandler) sessionExpiredHandler();
    return Promise.reject(error);
  }
  return api.request(config);
}

api.interceptors.response.use((response) => response, handleAuthRetry);

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
