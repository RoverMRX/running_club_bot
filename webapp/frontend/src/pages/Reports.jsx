import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getTournaments, joinTournament } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";

const TYPE_LABELS = { km: "Километры", minutes: "Минуты", days: "Дни", team_km: "Командные км" };

function fmt(dt) {
  return new Date(dt).toLocaleString("ru", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtScore(score, type) {
  if (type === "km" || type === "team_km") return `${score.toFixed(1)} км`;
  if (type === "minutes") return `${Math.round(score)} мин`;
  if (type === "days")    return `${Math.round(score)} дн`;
  return String(score);
}

function TournamentCard({ t }) {
  const qc = useQueryClient();
  const joinMut = useMutation({ mutationFn: () => joinTournament(t.id), onSuccess: () => qc.invalidateQueries(["tournaments"]) });

  const now = new Date();
  const end = new Date(t.end_date);
  const h   = Math.max(0, Math.round((end - now) / 3_600_000));
  const d   = Math.floor(h / 24);
  const timeStr = d > 0 ? `${d} дн` : `${h} ч`;

  // Цвета мест (строго, без золота)
  const posStyle = [
    { color: "#c8b560" },
    { color: "#909090" },
    { color: "#9e7240" },
  ];

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <h2 style={{ margin: 0, flex: 1 }}>{t.title}</h2>
        {t.is_active
          ? <span className="badge badge-active">{timeStr}</span>
          : <span className="badge">Завершён</span>
        }
      </div>
      <div className="hint" style={{ fontSize: 12, marginBottom: 4 }}>{TYPE_LABELS[t.tournament_type]}</div>
      <div className="hint" style={{ fontSize: 11 }}>{fmt(t.start_date)} — {fmt(t.end_date)}</div>

      {t.leaderboard.length > 0 && (
        <>
          <div className="divider" />
          <div style={{ fontSize: 12, fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--text-muted)", marginBottom: 8 }}>
            Таблица
          </div>
          {t.leaderboard.map((row) => (
            <div key={row.user_tg_id} style={{
              display: "flex", alignItems: "center", gap: 10, padding: "6px 0",
              borderBottom: "1px solid var(--border)",
            }}>
              <div style={{ width: 24, fontWeight: 700, fontSize: 13, ...(posStyle[row.position - 1] || { color: "var(--text-dim)" }) }}>
                {row.position}
              </div>
              <div style={{ flex: 1, fontSize: 14 }}>{row.school_nick}</div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{fmtScore(row.score, t.tournament_type)}</div>
            </div>
          ))}
        </>
      )}

      {t.leaderboard.length === 0 && (
        <div className="hint" style={{ textAlign: "center", padding: "12px 0", fontSize: 13 }}>Пока никто не участвует</div>
      )}

      {t.is_active && (
        <div style={{ marginTop: 12 }}>
          {t.user_joined
            ? <div className="btn btn-secondary" style={{ cursor: "default", opacity: 0.6 }}>Ты участвуешь</div>
            : <button className="btn btn-primary" disabled={joinMut.isPending} onClick={() => joinMut.mutate()}>
                {joinMut.isPending ? "..." : "Принять вызов"}
              </button>
          }
        </div>
      )}
    </div>
  );
}

export default function Tournaments() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tournaments"], queryFn: () => getTournaments(true),
  });

  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;

  return (
    <div>
      <h1>Турниры</h1>
      {!data?.length
        ? <div className="empty-state">
            <div className="empty-icon">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2">
                <path d="M6 9H4a2 2 0 000 4h2"/><path d="M18 9h2a2 2 0 010 4h-2"/>
                <path d="M6 9V5h12v4"/><path d="M6 13c0 3.3 2.7 6 6 6s6-2.7 6-6"/>
                <path d="M12 19v2M9 21h6"/>
              </svg>
            </div>
            <div className="empty-title">Нет активных турниров</div>
            <div style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 4 }}>Турниры создаёт администратор</div>
          </div>
        : data.map(t => <TournamentCard key={t.id} t={t} />)
      }
    </div>
  );
}