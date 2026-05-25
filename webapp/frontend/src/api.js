import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * Получаем initData. Пробуем три источника:
 * 1. window.Telegram.WebApp.initData — стандартный путь (мобила, новые десктопы)
 * 2. URL hash, параметр tgWebAppData — fallback для старых десктопов
 * 3. sessionStorage — кэш на случай если хеш почистили после редиректа
 */
export const getInitData = () => {
  // 1. Стандарт
  const tgData = window.Telegram?.WebApp?.initData;
  if (tgData && tgData.length > 0) {
    sessionStorage.setItem("tg_init_data", tgData);
    return tgData;
  }

  // 2. Из URL hash
  const hash = window.location.hash;
  if (hash && hash.includes("tgWebAppData=")) {
    const params = new URLSearchParams(hash.replace(/^#/, ""));
    const data = params.get("tgWebAppData");
    if (data && data.length > 0) {
      sessionStorage.setItem("tg_init_data", data);
      return data;
    }
  }

  // 3. Из sessionStorage (если хеш был и почистился)
  const cached = sessionStorage.getItem("tg_init_data");
  if (cached && cached.length > 0) return cached;

  return null;
};

const api = axios.create({ baseURL: BASE_URL });

api.interceptors.request.use((config) => {
  const initData = getInitData();
  if (initData) config.headers["X-Init-Data"] = initData;
  return config;
});

// ─── Профиль ─────────────────────────────────────────────────
export const getProfile       = () => api.get("/profile").then(r => r.data);
export const getLeaderboard   = (period="alltime", sort_by="xp") => api.get("/profile/leaderboard", { params: { period, sort_by } }).then(r => r.data);

// ─── Челленджи ───────────────────────────────────────────────
export const getMyChallenges        = () => api.get("/challenges/my").then(r => r.data);
export const getMyChallengesHistory = () => api.get("/challenges/my/history").then(r => r.data);
export const getClubChallenges      = (page = 0) => api.get("/challenges/club", { params: { page, page_size: 10 } }).then(r => r.data);
export const getClubChallengesCount = () => api.get("/challenges/club/count").then(r => r.data);
export const getChallenge           = (id) => api.get(`/challenges/${id}`).then(r => r.data);
export const createChallenge        = (data) => api.post("/challenges", data).then(r => r.data);
export const joinChallenge          = (id, penalty = null) => api.post(`/challenges/${id}/join`, { penalty }).then(r => r.data);
export const leaveChallenge         = (id) => api.post(`/challenges/${id}/leave`).then(r => r.data);
export const closeChallenge         = (id) => api.post(`/challenges/${id}/close`).then(r => r.data);

// ─── Отчёты ──────────────────────────────────────────────────
export const getReports   = (page = 0) => api.get("/reports",    { params: { page, page_size: 20 } }).then(r => r.data);
export const getMyReports = (page = 0) => api.get("/reports/my", { params: { page, page_size: 20 } }).then(r => r.data);

// ─── Мероприятия ─────────────────────────────────────────────
export const getEvents         = (upcomingOnly = true) => api.get("/events", { params: { upcoming_only: upcomingOnly } }).then(r => r.data);
export const getArchiveEvents  = () => api.get("/events", { params: { upcoming_only: false } }).then(r => r.data);
export const getEvent          = (id) => api.get(`/events/${id}`).then(r => r.data);
export const getEventTemplates = () => api.get("/events/templates").then(r => r.data);
export const createEvent       = (data) => api.post("/events", data).then(r => r.data);
export const joinEvent         = (id) => api.post(`/events/${id}/join`).then(r => r.data);
export const leaveEvent        = (id) => api.post(`/events/${id}/leave`).then(r => r.data);

// ─── Турниры ─────────────────────────────────────────────────
export const getTournaments        = () => api.get("/tournaments").then(r => r.data);
export const getTournamentsArchive = () => api.get("/tournaments/archive").then(r => r.data);
export const getTournament         = (id) => api.get(`/tournaments/${id}`).then(r => r.data);
export const joinTournament        = (id) => api.post(`/tournaments/${id}/join`).then(r => r.data);

// ─── Челленджи — доп. действия ───────────────────────────────
export const requestCloseChallenge = (id) => api.post(`/challenges/${id}/request-close`).then(r => r.data);
export const freezeChallenge        = (id, days) => api.post(`/challenges/${id}/freeze`, { days }).then(r => r.data);
export const requestPauseChallenge  = (id, reason) => api.post(`/challenges/${id}/request-pause`, { reason }).then(r => r.data);
export const requestUnfreezeChallenge = (id) => api.post(`/challenges/${id}/request-unfreeze`).then(r => r.data);
export const surrenderChallenge              = (id) => api.post(`/challenges/${id}/surrender`).then(r => r.data);
export const requestCloseParticipation       = (id) => api.post(`/challenges/${id}/request-close-participation`).then(r => r.data);
export const requestPauseParticipation       = (id, reason) => api.post(`/challenges/${id}/request-pause-participation`, { reason }).then(r => r.data);