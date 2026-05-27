import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMyReports, getMyStats } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

function fmtDate(dt) {
  return new Date(dt).toLocaleString("ru", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtDuration(sec) {
  if (!sec) return null;
  const h  = Math.floor(sec / 3600);
  const mn = Math.floor((sec % 3600) / 60);
  const sc = sec % 60;
  if (h > 0) return `${h}:${String(mn).padStart(2, "0")}:${String(sc).padStart(2, "0")}`;
  return `${mn}:${String(sc).padStart(2, "0")}`;
}

// ─── Статистика + график ──────────────────────────────────────

function StatsBlock() {
  const [view, setView] = useState("weekly");

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
    <div>
      {/* Итоги */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8, marginBottom: 12 }}>
        {[
          { label: "Всего пробежек", value: data.total_runs, icon: "🏃" },
          { label: "Всего км",       value: `${data.total_km.toFixed(1)} км`, icon: "📍" },
          { label: "Лучшая пробежка",value: `${data.best_km.toFixed(1)} км`, icon: "🏆" },
          { label: "Средняя",        value: `${data.avg_km.toFixed(1)} км`, icon: "📊" },
        ].map(s => (
          <div key={s.label} className="card" style={{ padding: "12px 16px", marginBottom: 0 }}>
            <div style={{ fontSize: 20, marginBottom: 4 }}>{s.icon}</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{s.value}</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* График */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>График пробегов</div>
          <div style={{ display: "flex", gap: 6 }}>
            {[["weekly", "Недели"], ["daily", "Дни"]].map(([v, l]) => (
              <button key={v} onClick={() => setView(v)} style={{
                fontSize: 11, padding: "3px 8px", borderRadius: 20, cursor: "pointer",
                border: "1px solid var(--border)",
                background: view === v ? "var(--accent)" : "var(--bg-input)",
                color: view === v ? "#000" : "var(--text)",
                fontWeight: view === v ? 600 : 400,
              }}>{l}</button>
            ))}
          </div>
        </div>

        {chartData.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: "20px 0" }}>
            Нет данных за этот период
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={150}>
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
                    fill={entry.km >= maxKm * 0.8 ? "var(--accent)" : "rgba(224,224,224,0.25)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

// ─── История пробежек ─────────────────────────────────────────

function ReportRow({ r }) {
  const timeStr = fmtDuration(r.duration_sec);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "10px 0",
      borderBottom: "1px solid var(--border)",
    }}>
      <div style={{ fontSize: 22, flexShrink: 0 }}>🏃</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontWeight: 700, fontSize: 16 }}>{r.km.toFixed(1)}</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>км</span>
          {timeStr && <span style={{ fontSize: 12, color: "var(--text-muted)" }}>· ⏱ {timeStr}</span>}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>{fmtDate(r.created_at)}</div>
      </div>
      <div style={{ flexShrink: 0 }}>
        {r.is_approved
          ? <span style={{ fontSize: 11, color: "var(--success)" }}>✅</span>
          : r.is_rejected
          ? <span style={{ fontSize: 11, color: "var(--danger)" }}>❌</span>
          : <span style={{ fontSize: 11, color: "var(--warning)" }}>⏳</span>}
      </div>
    </div>
  );
}

// ─── Главный компонент ────────────────────────────────────────

export default function Reports() {
  const [page, setPage] = useState(0);
  const [tab, setTab]   = useState("stats");
  const PAGE_SIZE = 20;

  const myQuery = useQuery({
    queryKey: ["reports", "my", page],
    queryFn: () => getMyReports(page),
    enabled: tab === "history",
    staleTime: 30_000,
  });

  const reports = myQuery.data || [];

  return (
    <div>
      <h1 style={{ marginBottom: 16 }}>Мои пробежки</h1>

      <div className="tabs" style={{ marginBottom: 16 }}>
        <button className={"tab" + (tab === "stats"   ? " active" : "")} onClick={() => setTab("stats")}>
          📊 Статистика
        </button>
        <button className={"tab" + (tab === "history" ? " active" : "")} onClick={() => setTab("history")}>
          📋 История
        </button>
      </div>

      {tab === "stats" && <StatsBlock />}

      {tab === "history" && (
        <>
          {myQuery.isLoading && <Loader />}
          {myQuery.isError   && <ErrorMessage error={myQuery.error} />}
          {!myQuery.isLoading && !myQuery.isError && (
            reports.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">🏃</div>
                <div className="empty-title">Пробежек пока нет</div>
                <div style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 4 }}>
                  Публикуй #отчет в группе
                </div>
              </div>
            ) : (
              <div className="card" style={{ padding: "0 16px" }}>
                {reports.map(r => <ReportRow key={r.id} r={r} />)}
                <div style={{ display: "flex", gap: 8, padding: "12px 0", justifyContent: "center" }}>
                  {page > 0 && (
                    <button className="btn btn-secondary" style={{ fontSize: 13 }}
                      onClick={() => setPage(p => p - 1)}>← Назад</button>
                  )}
                  {reports.length === PAGE_SIZE && (
                    <button className="btn btn-secondary" style={{ fontSize: 13 }}
                      onClick={() => setPage(p => p + 1)}>Ещё →</button>
                  )}
                </div>
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}
