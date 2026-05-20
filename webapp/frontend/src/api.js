/**
 * api.js — все запросы к FastAPI бэкенду.
 *
 * Telegram передаёт initData через window.Telegram.WebApp.initData
 * Мы кладём его в заголовок X-Init-Data при каждом запросе.
 *
 * В dev-режиме (localhost без Telegram) initData будет пустым —
 * бэкенд вернёт 401, поэтому для локальной разработки используем
 * тестовый bypass (см. auth.py DEV_MODE).
 */

import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Получаем initData от Telegram
const getInitData = () => {
  if (window.Telegram?.WebApp?.initData) {
    return window.Telegram.WebApp.initData;
  }
  // Для локальной разработки — фиктивный токен (см. DEV_MODE в auth.py)
  return import.meta.env.VITE_DEV_INIT_DATA || "";
};

const api = axios.create({
  baseURL: BASE_URL,
});

// Добавляем initData к каждому запросу
api.interceptors.request.use((config) => {
  config.headers["X-Init-Data"] = getInitData();
  return config;
});

// ─── Профиль ─────────────────────────────────────────────────────────────────

export const getProfile = () =>
  api.get("/profile").then((r) => r.data);

export const getLeaderboard = () =>
  api.get("/profile/leaderboard").then((r) => r.data);

// ─── Челленджи ───────────────────────────────────────────────────────────────

export const getMyChallenges = () =>
  api.get("/challenges/my").then((r) => r.data);

export const getClubChallenges = (page = 0) =>
  api.get("/challenges/club", { params: { page, page_size: 10 } }).then((r) => r.data);

export const getClubChallengesCount = () =>
  api.get("/challenges/club/count").then((r) => r.data);

export const getChallenge = (id) =>
  api.get(`/challenges/${id}`).then((r) => r.data);

export const joinChallenge = (id, penalty = null) =>
  api.post(`/challenges/${id}/join`, { penalty }).then((r) => r.data);

// ─── Отчёты ──────────────────────────────────────────────────────────────────

export const getReports = (page = 0) =>
  api.get("/reports", { params: { page, page_size: 20 } }).then((r) => r.data);

export const getMyReports = (page = 0) =>
  api.get("/reports/my", { params: { page, page_size: 20 } }).then((r) => r.data);

// ─── Мероприятия ─────────────────────────────────────────────────────────────

export const getEvents = (upcomingOnly = true) =>
  api.get("/events", { params: { upcoming_only: upcomingOnly } }).then((r) => r.data);

export const getPendingEvents = () =>
  api.get("/events/pending").then((r) => r.data);

export const createEvent = (data) =>
  api.post("/events", data).then((r) => r.data);

export const joinEvent = (id) =>
  api.post(`/events/${id}/join`).then((r) => r.data);

export const leaveEvent = (id) =>
  api.post(`/events/${id}/leave`).then((r) => r.data);

export const approveEvent = (id) =>
  api.post(`/events/${id}/approve`).then((r) => r.data);

export const rejectEvent = (id) =>
  api.post(`/events/${id}/reject`).then((r) => r.data);

// ─── Турниры ─────────────────────────────────────────────────────────────────

export const getTournaments = (activeOnly = true) =>
  api.get("/tournaments", { params: { active_only: activeOnly } }).then((r) => r.data);

export const getTournament = (id) =>
  api.get(`/tournaments/${id}`).then((r) => r.data);

export const joinTournament = (id) =>
  api.post(`/tournaments/${id}/join`).then((r) => r.data);