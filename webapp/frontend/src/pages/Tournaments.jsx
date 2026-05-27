import { useState } from "react";
import PublicProfile from "./PublicProfile";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getTournaments, getTournamentsArchive, joinTournament } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";

const TYPE_LABELS = {
  km:      "🏃 Больше километров",
  minutes: "⏱ Больше минут",
  days:    "📅 Больше дней с пробежкой",
  team_km: "👥 Командные км",
};

function fmtDate(dt) {
  return new Date(dt).toLocaleString("ru", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtScore(score, type) {
  if (type === "km" || type === "team_km") return `${score.toFixed(1)} км`;
  if (type === "minutes") return `${Math.round(score)} мин`;
  if (type === "days")    return `${Math.round(score)} дн`;
  return String(score);
}

const MEDAL_COLORS = ["#f0c040", "#a0a0a0", "#cd7f32"];

function Leaderboard({ leaderboard, type, onUserClick }) {
  if (leaderboard.length === 0) return (
    <div className="hint" style={{ textAlign: "center", padding: "12px 0", fontSize: 13 }}>
      Пока никто не участвует
    </div>
  );

  return (
    <div>
      {leaderboard.map(row => (
        <div key={row.user_tg_id}
          onClick={() => onUserClick && onUserClick(row.user_tg_id)}
          style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "7px 0", borderBottom: "1px solid var(--border)",
            cursor: onUserClick ? "pointer" : "default",
          }}>
          <div style={{
            width: 24, fontWeight: 700, fontSize: 14, textAlign: "center",
            color: MEDAL_COLORS[row.position - 1] || "var(--text-dim)",
          }}>
            {row.position <= 3 ? ["🥇","🥈","🥉"][row.position - 1] : row.position}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 500, fontSize: 14 }}>{row.school_nick}</div>
            {row.username && <div className="hint" style={{ fontSize: 11 }}>@{row.username}</div>}
          </div>
          <div style={{ fontWeight: 700, fontSize: 14 }}>
            {fmtScore(row.score, type)}
          </div>
        </div>
      ))}
    </div>
  );
}

function TournamentCard({ t, onUserClick }) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);

  const joinMut = useMutation({
    mutationFn: () => joinTournament(t.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tournaments"] });
      qc.invalidateQueries({ queryKey: ["tournaments-archive"] });
    },
  });

  const now      = new Date();
  const end      = new Date(t.end_date);
  const msLeft   = Math.max(0, end - now);
  const daysLeft = Math.floor(msLeft / 86_400_000);
  const hrsLeft  = Math.floor((msLeft % 86_400_000) / 3_600_000);
  const timeStr  = daysLeft > 0 ? `${daysLeft} дн ${hrsLeft} ч` : `${hrsLeft} ч`;

  return (
    <div className="card">
      {/* Шапка */}
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "flex-start", marginBottom: 4 }}>
        <h2 style={{ margin: 0, flex: 1, fontSize: 17 }}>{t.title}</h2>
        {t.is_active
          ? <span className="badge" style={{ whiteSpace: "nowrap" }}>⏳ {timeStr}</span>
          : <span className="badge" style={{ background: "var(--text-dim)" }}>Завершён</span>
        }
      </div>
      <div className="hint" style={{ fontSize: 13, marginBottom: 2 }}>
        {TYPE_LABELS[t.tournament_type] || t.tournament_type}
      </div>
      <div className="hint" style={{ fontSize: 11 }}>
        {fmtDate(t.start_date)} — {fmtDate(t.end_date)}
      </div>

      {/* Топ-3 всегда виден */}
      {t.leaderboard.length > 0 && (
        <>
          <div className="divider" />
          <Leaderboard
            leaderboard={expanded ? t.leaderboard : t.leaderboard.slice(0, 3)}
            type={t.tournament_type}
            onUserClick={onUserClick}
          />
          {t.leaderboard.length > 3 && (
            <button
              style={{ background: "none", border: "none", color: "var(--accent)",
                fontSize: 13, cursor: "pointer", padding: "4px 0", marginTop: 4 }}
              onClick={() => setExpanded(v => !v)}
            >
              {expanded ? "Свернуть" : `Показать всех (${t.leaderboard.length})`}
            </button>
          )}
        </>
      )}

      {t.leaderboard.length === 0 && (
        <>
          <div className="divider" />
          <div className="hint" style={{ textAlign: "center", padding: "8px 0", fontSize: 13 }}>
            Пока никто не участвует
          </div>
        </>
      )}

      {/* Кнопка участия — только для активных */}
      {t.is_active && (
        <div style={{ marginTop: 12 }}>
          {t.user_joined ? (
            <div style={{ fontSize: 13, color: "var(--accent)", fontWeight: 500 }}>
              ✅ Ты участвуешь
            </div>
          ) : (
            <button className="btn btn-primary" disabled={joinMut.isPending}
              onClick={() => joinMut.mutate()}>
              {joinMut.isPending ? "..." : "🏆 Принять вызов"}
            </button>
          )}
          {joinMut.data && !joinMut.data.ok && (
            <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 6 }}>
              {joinMut.data.reason}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TournamentList({ queryKey, queryFn, emptyText, emptyHint, onUserClick }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: [queryKey],
    queryFn,
    staleTime: 30_000,
  });

  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;
  if (!data?.length) return (
    <div className="empty-state">
      <div className="empty-icon">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="1.2">
          <path d="M6 9H4a2 2 0 000 4h2"/>
          <path d="M18 9h2a2 2 0 010 4h-2"/>
          <path d="M6 9V5h12v4"/>
          <path d="M6 13c0 3.3 2.7 6 6 6s6-2.7 6-6"/>
          <path d="M12 19v2M9 21h6"/>
        </svg>
      </div>
      <div className="empty-title">{emptyText}</div>
      {emptyHint && <div style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 4 }}>{emptyHint}</div>}
    </div>
  );

  return <div>{data.map(t => <TournamentCard key={t.id} t={t} onUserClick={onUserClick} />)}</div>;
}

export default function Tournaments() {
  const [tab, setTab]       = useState("active");
  const [viewUser, setViewUser] = useState(null);

  if (viewUser) return <PublicProfile tg_id={viewUser} onBack={() => setViewUser(null)} />;

  return (
    <div>
      <h1 style={{ marginBottom: 18 }}>Турниры</h1>

      <div className="tabs">
        <button className={"tab" + (tab === "active"  ? " active" : "")}
          onClick={() => setTab("active")}>Активные</button>
        <button className={"tab" + (tab === "archive" ? " active" : "")}
          onClick={() => setTab("archive")}>Архив</button>
      </div>

      {tab === "active" && (
        <TournamentList
          queryKey="tournaments"
          queryFn={getTournaments}
          emptyText="Нет активных турниров"
          emptyHint="Турниры создаёт администратор клуба"
          onUserClick={setViewUser}
        />
      )}
      {tab === "archive" && (
        <TournamentList
          queryKey="tournaments-archive"
          queryFn={getTournamentsArchive}
          emptyText="Архив пуст"
          onUserClick={setViewUser}
        />
      )}
    </div>
  );
}