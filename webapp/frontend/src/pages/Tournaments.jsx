import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getTournaments, joinTournament } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";

const TYPE_LABELS = {
  km:      "🏃 Больше километров",
  minutes: "⏱ Больше минут",
  days:    "📅 Больше дней",
  team_km: "👥 Командные км",
};

function formatDate(dt) {
  return new Date(dt).toLocaleString("ru", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function formatScore(score, type) {
  if (type === "km" || type === "team_km") return `${score.toFixed(1)} км`;
  if (type === "minutes") return `${Math.round(score)} мин`;
  if (type === "days")    return `${Math.round(score)} дн`;
  return String(score);
}

function TournamentCard({ t }) {
  const qc = useQueryClient();
  const joinMut = useMutation({
    mutationFn: () => joinTournament(t.id),
    onSuccess: () => qc.invalidateQueries(["tournaments"]),
  });

  const medals = ["🥇", "🥈", "🥉"];
  const now = new Date();
  const end = new Date(t.end_date);
  const hoursLeft = Math.max(0, Math.round((end - now) / 3_600_000));
  const daysLeft  = Math.floor(hoursLeft / 24);
  const timeStr   = daysLeft > 0 ? `${daysLeft} дн` : `${hoursLeft} ч`;

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ marginBottom: 4 }}>{t.title}</h2>
          <div className="hint">{TYPE_LABELS[t.tournament_type] || t.tournament_type}</div>
        </div>
        {t.is_active
          ? <span className="badge" style={{ whiteSpace: "nowrap" }}>⏳ {timeStr}</span>
          : <span className="badge" style={{ background: "var(--tg-hint)" }}>Завершён</span>
        }
      </div>

      <div className="hint" style={{ fontSize: 12, marginTop: 4 }}>
        {formatDate(t.start_date)} — {formatDate(t.end_date)}
      </div>

      {/* Таблица лидеров */}
      {t.leaderboard.length > 0 && (
        <div>
          <div className="divider" />
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>🏆 Топ участников</div>
          {t.leaderboard.map((row) => (
            <div key={row.user_tg_id} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "6px 0",
              borderBottom: "1px solid rgba(0,0,0,0.05)",
            }}>
              <span style={{ fontSize: 18, width: 28 }}>
                {medals[row.position - 1] || `${row.position}.`}
              </span>
              <div style={{ flex: 1 }}>
                <span style={{ fontWeight: 600 }}>{row.school_nick}</span>
                {row.username && <span className="hint"> @{row.username}</span>}
              </div>
              <span style={{ fontWeight: 700 }}>
                {formatScore(row.score, t.tournament_type)}
              </span>
            </div>
          ))}
        </div>
      )}

      {t.leaderboard.length === 0 && (
        <div className="hint" style={{ textAlign: "center", padding: "12px 0" }}>
          Пока никто не участвует
        </div>
      )}

      {/* Кнопка участия */}
      {t.is_active && (
        <div style={{ marginTop: 12 }}>
          {t.user_joined ? (
            <div className="btn btn-secondary" style={{ cursor: "default", opacity: 0.7 }}>
              ✅ Ты участвуешь
            </div>
          ) : (
            <button
              className="btn btn-primary"
              disabled={joinMut.isPending}
              onClick={() => joinMut.mutate()}
            >
              {joinMut.isPending ? "..." : "🏆 Принять вызов"}
            </button>
          )}
          {joinMut.data && !joinMut.data.ok && (
            <div style={{ color: "#ff3b30", fontSize: 13, marginTop: 6 }}>
              {joinMut.data.reason}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Tournaments() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => getTournaments(true),
  });

  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;

  return (
    <div>
      <h1>🏆 Турниры</h1>
      {data.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 24 }}>
          <div style={{ fontSize: 32 }}>🏆</div>
          <div style={{ marginTop: 8 }}>Нет активных турниров</div>
          <div className="hint" style={{ marginTop: 4 }}>
            Турниры создаёт администратор клуба
          </div>
        </div>
      ) : (
        data.map(t => <TournamentCard key={t.id} t={t} />)
      )}
    </div>
  );
}