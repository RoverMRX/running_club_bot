import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getReports, getMyReports, getMyStats } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

// ─── Утилиты ─────────────────────────────────────────────────

function fmtDate(dt) {
  return new Date(dt).toLocaleString("ru", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/** Форматирует секунды → ЧЧ:ММ:СС или ММ:СС */
function fmtDuration(sec) {
  if (!sec) return null;
  const h  = Math.floor(sec / 3600);
  const mn = Math.floor((sec % 3600) / 60);
  const sc = sec % 60;
  if (h > 0) return `${h}:${String(mn).padStart(2, "0")}:${String(sc).padStart(2, "0")}`;
  return `${mn}:${String(sc).padStart(2, "0")}`;
}

// ─── Одна карточка отчёта ─────────────────────────────────────

function ReportCard({ r, showAuthor = true }) {
  const timeStr = fmtDuration(r.duration_sec);

  let statusBadge;
  if (r.is_approved) {
    statusBadge = (
      <span className="badge badge-active" style={{ fontSize: 11 }}>✅ Одобрен</span>
    );
  } else if (r.is_rejected) {
    statusBadge = (
      <span className="badge" style={{ background: "var(--danger)", fontSize: 11 }}>❌ Отклонён</span>
    );
  } else {
    statusBadge = (
      <span className="badge" style={{ background: "var(--warning)", fontSize: 11 }}>⏳ На проверке</span>
    );
  }

  return (
    <div className="card" style={{ padding: "12px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          {showAuthor && (
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>
              {r.username ? `@${r.username}` : r.school_nick}
            </div>
          )}
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: 20, fontWeight: 700, color: "var(--accent)" }}>
              {r.km.toFixed(1)}
            </span>
            <span style={{ fontSize: 13, color: "var(--text-muted)" }}>км</span>
            {timeStr && (
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                ⏱ {timeStr}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
          {statusBadge}
          <span style={{ fontSize: 11, color: "var(--text-dim)" }}>
            {fmtDate(r.created_at)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── Главный компонент ────────────────────────────────────────


// ─── График статистики ────────────────────────────────────────

function StatsBlock() {
  const [view, setView] = useState("weekly"); // "daily" | "weekly"

  const { data, isLoading, isError } = useQuery({
    queryKey: ["reports-stats"],
    queryFn: getMyStats,
    staleTime: 60_000,
  });

  if (isLoading) return <Loader />;
  if (isError || !data) return null;

  const chartData = view === "weekly"
    ? data.weekly.map(w => ({ label: w.week.replace(/.*-W/, "нед "), km: w.km, runs: w.runs }))
    : data.daily.map(d => ({
        label: new Date(d.date).toLocaleDateString("ru", { day: "2-digit", month: "2-digit" }),
        km: d.km, runs: d.runs,
      }));

  const maxKm = Math.max(...chartData.map(d => d.km), 1);

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      {/* Итоги */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 16 }}>
        {[
          { label: "Пробежек",   value: data.total_runs },
          { label: "Всего км",   value: data.total_km.toFixed(1) },
          { label: "Лучшая",     value: `${data.best_km.toFixed(1)} км` },
          { label: "Средняя",    value: `${data.avg_km.toFixed(1)} км` },
        ].map(s => (
          <div key={s.label} style={{ textAlign: "center" }}>
            <div style={{ fontWeight: 700, fontSize: 16 }}>{s.value}</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Переключатель */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {[["weekly","По неделям"],["daily","По дням"]].map(([v, l]) => (
          <button key={v} onClick={() => setView(v)}
            style={{
              fontSize: 12, padding: "4px 10px", borderRadius: 20, cursor: "pointer",
              border: "1px solid var(--border)",
              background: view === v ? "var(--accent)" : "var(--bg-input)",
              color: view === v ? "#000" : "var(--text)",
              fontWeight: view === v ? 600 : 400,
            }}>{l}</button>
        ))}
      </div>

      {/* График */}
      {chartData.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: "20px 0" }}>
          Нет данных
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={chartData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--text-dim)" }}
              interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: "var(--text-dim)" }} />
            <Tooltip
              formatter={(val) => [`${val} км`, "Пробег"]}
              contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)",
                borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: "var(--text-muted)" }}
            />
            <Bar dataKey="km" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, i) => (
                <Cell key={i}
                  fill={entry.km >= maxKm * 0.8 ? "var(--accent)" : "rgba(224,224,224,0.3)"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

export default function Reports() {
  const [tab, setTab] = useState("club");    // "club" | "my"
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;

  const clubQuery = useQuery({
    queryKey: ["reports", "club", page],
    queryFn: () => getReports(page),
    enabled: tab === "club",
    keepPreviousData: true,
  });

  const myQuery = useQuery({
    queryKey: ["reports", "my", page],
    queryFn: () => getMyReports(page),
    enabled: tab === "my",
    keepPreviousData: true,
  });

  const query   = tab === "club" ? clubQuery : myQuery;
  const reports = query.data || [];

  return (
    <div>
      <h1>Отчёты</h1>

      {/* Переключатель */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {["club", "my"].map(t => (
          <button
            key={t}
            className={`btn ${tab === t ? "btn-primary" : "btn-secondary"}`}
            style={{ flex: 1, fontSize: 13 }}
            onClick={() => { setTab(t); setPage(0); }}
          >
            {t === "club" ? "🌍 Клуб" : "📋 Мои"}
          </button>
        ))}
      </div>

      {tab === "my" && <StatsBlock />}
      {query.isLoading && <Loader />}
      {query.isError   && <ErrorMessage error={query.error} />}

      {!query.isLoading && !query.isError && (
        <>
          {reports.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="1.2">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="16" y1="13" x2="8" y2="13"/>
                  <line x1="16" y1="17" x2="8" y2="17"/>
                  <polyline points="10 9 9 9 8 9"/>
                </svg>
              </div>
              <div className="empty-title">
                {tab === "my" ? "Твоих отчётов пока нет" : "Нет отчётов"}
              </div>
              {tab === "my" && (
                <div style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 4 }}>
                  Публикуй #отчет в группе
                </div>
              )}
            </div>
          ) : (
            <>
              {reports.map(r => (
                <ReportCard key={r.id} r={r} showAuthor={tab === "club"} />
              ))}

              {/* Пагинация */}
              <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "center" }}>
                {page > 0 && (
                  <button className="btn btn-secondary" style={{ fontSize: 13 }}
                    onClick={() => setPage(p => p - 1)}>
                    ← Назад
                  </button>
                )}
                {reports.length === PAGE_SIZE && (
                  <button className="btn btn-secondary" style={{ fontSize: 13 }}
                    onClick={() => setPage(p => p + 1)}>
                    Ещё →
                  </button>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
