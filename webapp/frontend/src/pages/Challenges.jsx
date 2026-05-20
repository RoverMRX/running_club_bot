import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getMyChallenges, getClubChallenges, getClubChallengesCount, getChallenge, joinChallenge } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";

const TYPE_LABELS = {
  weekly_runs: "Регулярный",
  daily_km:    "Дневной",
  weekly_km:   "Недельный",
  monthly_km:  "Месячный",
  race:        "Забег",
};

function goalStr(ch) {
  if (ch.ch_type === "weekly_runs") {
    const cond = [];
    if (ch.min_per_run > 0) cond.push(`${ch.min_per_run} км`);
    if (ch.min_minutes_per_run > 0) cond.push(`${ch.min_minutes_per_run} мин`);
    return `${ch.goal_runs} пробежек / нед · мин: ${cond.join(" или ") || "любая"}`;
  }
  if (ch.ch_type === "race" && ch.deadline)
    return `${ch.goal_value.toFixed(1)} км · ${new Date(ch.deadline).toLocaleDateString("ru")}`;
  return `${ch.goal_value.toFixed(1)} км`;
}

function ProgressBar({ value, max }) {
  const pct = max > 0 ? Math.min(100, Math.round(value / max * 100)) : 0;
  return (
    <div>
      <div className="progress-wrap"><div className="progress-fill" style={{ width: `${pct}%` }}/></div>
      <div style={{ fontSize: 11, color: "var(--text-dim)", textAlign: "right", marginTop: 2 }}>{pct}%</div>
    </div>
  );
}

function ChallengeRow({ ch, onClick }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "12px 16px", cursor: "pointer",
      borderBottom: "1px solid var(--border)",
    }} onClick={() => onClick(ch.id)}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 2 }}>{ch.title}</div>
        <div className="hint" style={{ fontSize: 12 }}>{TYPE_LABELS[ch.ch_type]} · {goalStr(ch)}</div>
        {ch.ch_type === "weekly_runs"
          ? <ProgressBar value={ch.current_runs}  max={ch.goal_runs} />
          : <ProgressBar value={ch.current_value} max={ch.goal_value} />
        }
      </div>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-dim)" strokeWidth="2" strokeLinecap="round">
        <path d="M9 18l6-6-6-6"/>
      </svg>
    </div>
  );
}

function ChallengeDetail({ id, onBack }) {
  const qc = useQueryClient();
  const { data: ch, isLoading, isError, error } = useQuery({
    queryKey: ["challenge", id], queryFn: () => getChallenge(id),
  });
  const [penalty, setPenalty] = useState("");
  const [showForm, setShowForm] = useState(false);

  const joinMut = useMutation({
    mutationFn: (p) => joinChallenge(id, p || null),
    onSuccess: () => {
      qc.invalidateQueries(["challenge", id]);
      qc.invalidateQueries(["challenges-club"]);
      qc.invalidateQueries(["challenges-my"]);
    },
  });

  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;

  const isJoined = ch.participants.some(p => p.school_nick === ch.author_nick);

  return (
    <div>
      <button className="btn btn-secondary" style={{ width: "auto", padding: "7px 14px", marginBottom: 16, fontSize: 13 }} onClick={onBack}>
        ← Назад
      </button>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
          <h2 style={{ margin: 0, flex: 1 }}>{ch.title}</h2>
          <span className="badge">{TYPE_LABELS[ch.ch_type]}</span>
        </div>
        <div className="hint" style={{ fontSize: 13 }}>{goalStr(ch)}</div>
        <div className="hint" style={{ fontSize: 12, marginTop: 4 }}>Автор: {ch.author_nick}</div>
        {ch.penalty && <div style={{ marginTop: 8, fontSize: 13, color: "var(--text-muted)" }}>Ставка автора: {ch.penalty}</div>}
      </div>

      {ch.participants.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "10px 16px 0", fontSize: 12, fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--text-muted)" }}>
            Участники
          </div>
          {ch.participants.map((p, i) => (
            <div key={p.user_id} style={{
              display: "flex", alignItems: "center", gap: 12, padding: "10px 16px",
              borderBottom: i < ch.participants.length - 1 ? "1px solid var(--border)" : "none",
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 500 }}>{p.school_nick}</div>
                {p.penalty && <div className="hint" style={{ fontSize: 12 }}>Ставка: {p.penalty}</div>}
              </div>
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                {ch.ch_type === "weekly_runs" ? `${p.current_runs} пробежек` : `${p.current_value.toFixed(1)} км`}
              </div>
            </div>
          ))}
        </div>
      )}

      {!isJoined && (
        <div style={{ marginTop: 8 }}>
          {!showForm ? (
            <button className="btn btn-primary" onClick={() => setShowForm(true)}>Присоединиться</button>
          ) : (
            <div className="card">
              <div className="form-group">
                <label>Твоя ставка (необязательно)</label>
                <input value={penalty} onChange={e => setPenalty(e.target.value)} placeholder="Например: куплю всем кофе" />
              </div>
              {joinMut.data && !joinMut.data.ok && (
                <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 10 }}>{joinMut.data.reason}</div>
              )}
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-primary" disabled={joinMut.isPending} onClick={() => joinMut.mutate(penalty)}>
                  {joinMut.isPending ? "..." : "Подтвердить"}
                </button>
                <button className="btn btn-secondary" onClick={() => setShowForm(false)}>Отмена</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ChallengeList({ queryKey, queryFn, extraArgs = [], paginated = false }) {
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(null);
  const PAGE_SIZE = 10;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: [queryKey, page],
    queryFn: () => paginated ? queryFn(page) : queryFn(),
  });
  const countQ = useQuery({
    queryKey: [queryKey + "-count"],
    queryFn: getClubChallengesCount,
    enabled: paginated,
  });

  if (selected) return <ChallengeDetail id={selected} onBack={() => setSelected(null)} />;
  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;
  if (!data?.length) return (
    <div className="empty-state">
      <div className="empty-icon">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2">
          <circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>
        </svg>
      </div>
      <div className="empty-title">Нет челленджей</div>
    </div>
  );

  const total = countQ.data?.total || 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {data.map((ch, i) => (
          <div key={ch.id} style={{ borderBottom: i < data.length - 1 ? "1px solid var(--border)" : "none" }}>
            <ChallengeRow ch={ch} onClick={setSelected} />
          </div>
        ))}
      </div>
      {paginated && totalPages > 1 && (
        <div className="pagination">
          <button disabled={page === 0} onClick={() => setPage(p => p - 1)}>←</button>
          <span className="page-info">{page + 1} / {totalPages}</span>
          <button disabled={page + 1 >= totalPages} onClick={() => setPage(p => p + 1)}>→</button>
        </div>
      )}
    </div>
  );
}

export default function Challenges() {
  const [tab, setTab] = useState("my");
  return (
    <div>
      <h1>Челленджи</h1>
      <div className="tabs">
        <button className={"tab" + (tab === "my"   ? " active" : "")} onClick={() => setTab("my")}>Мои</button>
        <button className={"tab" + (tab === "club" ? " active" : "")} onClick={() => setTab("club")}>Клуб</button>
      </div>
      {tab === "my"   && <ChallengeList queryKey="challenges-my"   queryFn={getMyChallenges} />}
      {tab === "club" && <ChallengeList queryKey="challenges-club" queryFn={getClubChallenges} paginated />}
    </div>
  );
}