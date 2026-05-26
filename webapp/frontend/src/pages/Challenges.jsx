import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getMyChallenges, getMyChallengesHistory,
  getClubChallenges, getClubChallengesCount,
  getChallenge, createChallenge,
  joinChallenge, closeChallenge,
  requestCloseChallenge,
  requestPauseChallenge,
  requestUnfreezeChallenge,
  surrenderChallenge,
  requestCloseParticipation,
  requestPauseParticipation,
} from "../api";
import { useEffect, useRef } from "react";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";

// ─── Константы ───────────────────────────────────────────────

const TYPE_LABELS = {
  weekly_runs: "Регулярный",
  daily_km:    "Дневной",
  weekly_km:   "Недельный",
  monthly_km:  "Месячный",
  race:        "Забег",
};

const TYPE_DESCRIPTIONS = {
  weekly_runs: "N пробежек в неделю",
  daily_km:    "Набеги за 1 день",
  weekly_km:   "Набеги за 7 дней",
  monthly_km:  "Набеги за 30 дней",
  race:        "Забег до дедлайна",
};


// ─── Утилиты ─────────────────────────────────────────────────

function goalStr(ch) {
  if (ch.ch_type === "weekly_runs") {
    const cond = [];
    if (ch.min_per_run > 0)         cond.push(`≥${ch.min_per_run} км`);
    if (ch.min_minutes_per_run > 0) cond.push(`≥${ch.min_minutes_per_run} мин`);
    return `${ch.goal_runs} пробежек/нед` + (cond.length ? ` · мин: ${cond.join(" или ")}` : "");
  }
  const deadline = ch.deadline ? ` · до ${new Date(ch.deadline).toLocaleDateString("ru")}` : "";
  return `${ch.goal_value.toFixed(1)} км${deadline}`;
}

function progressValue(ch) {
  // Дочерний: прогресс хранится прямо в ch.current_*
  if (ch.is_child) {
    return ch.ch_type === "weekly_runs" ? ch.current_runs : ch.current_value;
  }
  // Участник в чужом (старая схема / club view)
  if (ch.is_participant && !ch.is_owner) {
    return ch.ch_type === "weekly_runs" ? ch.my_current_runs : ch.my_current_value;
  }
  return ch.ch_type === "weekly_runs" ? ch.current_runs : ch.current_value;
}
function progressMax(ch) {
  return ch.ch_type === "weekly_runs" ? ch.goal_runs : ch.goal_value;
}
function progressPct(ch) {
  const max = progressMax(ch);
  return max > 0 ? Math.min(100, Math.round(progressValue(ch) / max * 100)) : 0;
}
function progressLabel(ch) {
  if (ch.is_child) {
    if (ch.ch_type === "weekly_runs") return `${ch.current_runs} / ${ch.goal_runs} пробежек`;
    return `${ch.current_value.toFixed(1)} / ${ch.goal_value.toFixed(1)} км`;
  }
  if (ch.is_participant && !ch.is_owner) {
    if (ch.ch_type === "weekly_runs") {
      return `${ch.my_current_runs} / ${ch.goal_runs} пробежек`;
    }
    return `${(ch.my_current_value || 0).toFixed(1)} / ${ch.goal_value.toFixed(1)} км`;
  }
  if (ch.ch_type === "weekly_runs") return `${ch.current_runs} / ${ch.goal_runs} пробежек`;
  return `${ch.current_value.toFixed(1)} / ${ch.goal_value.toFixed(1)} км`;
}

function fmtDate(dt) {
  if (!dt) return null;
  return new Date(dt).toLocaleDateString("ru", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// Дефолт дедлайна — через 30 дней
function defaultDeadline() {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().split("T")[0]; // YYYY-MM-DD для input[type=date]
}

function dateInputToApi(val) {
  if (!val) return "";
  const [y, m, d] = val.split("-");
  return `${d}.${m}.${y}`;
}


// ─── Прогресс-бар ────────────────────────────────────────────

function ProgressBar({ ch, style }) {
  const pct = progressPct(ch);
  return (
    <div style={style}>
      <div className="progress-wrap">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between",
        fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>
        <span>{progressLabel(ch)}</span>
        <span>{pct}%</span>
      </div>
    </div>
  );
}


// ─── Детальная карточка ──────────────────────────────────────

function ChallengeDetail({ id, onBack }) {
  const qc = useQueryClient();
  const [penalty, setPenalty] = useState("");
  const [showJoinForm, setShowJoinForm] = useState(false);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  const [showCloseForm, setShowCloseForm] = useState(false);
  const [closeReason, setCloseReason] = useState("");
  const [showPauseForm, setShowPauseForm] = useState(false);
  const [pauseReason, setPauseReason] = useState("");
  const [showSurrender, setShowSurrender] = useState(false);
  const [surrenderCountdown, setSurrenderCountdown] = useState(0);
  const surrenderTimer = useRef(null);

  const { data: ch, isLoading, isError, error } = useQuery({
    queryKey: ["challenge", id],
    queryFn: () => getChallenge(id),
    staleTime: 15_000,
  });

  const inv = () => {
    qc.invalidateQueries({ queryKey: ["challenge", id] });
    qc.invalidateQueries({ queryKey: ["challenges-my"] });
    qc.invalidateQueries({ queryKey: ["challenges-club"] });
    qc.invalidateQueries({ queryKey: ["challenges-history"] });
  };

  const joinMut  = useMutation({ mutationFn: () => joinChallenge(id, penalty || null), onSuccess: inv });
  const closeMut        = useMutation({ mutationFn: () => closeChallenge(id), onSuccess: () => { inv(); onBack(); } });
  const requestCloseMut    = useMutation({ mutationFn: () => requestCloseChallenge(id, closeReason), onSuccess: () => { inv(); setShowCloseForm(false); } });
  const requestPauseMut    = useMutation({ mutationFn: () => requestPauseChallenge(id, pauseReason), onSuccess: () => { inv(); setShowPauseForm(false); } });
  const requestUnfreezeMut = useMutation({ mutationFn: () => requestUnfreezeChallenge(id), onSuccess: inv });
  const surrenderMut           = useMutation({ mutationFn: () => surrenderChallenge(id), onSuccess: () => { inv(); setShowSurrender(false); } });
  const reqClosePartMut        = useMutation({ mutationFn: () => requestCloseParticipation(id, closeReason), onSuccess: () => { inv(); setShowCloseForm(false); } });
  const reqPausePartMut        = useMutation({ mutationFn: () => requestPauseParticipation(id, pauseReason), onSuccess: () => { inv(); setShowPauseForm(false); } });

  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;

  const pct = progressPct(ch);

  return (
    <div>
      <button className="btn btn-secondary"
        style={{ width: "auto", padding: "7px 14px", marginBottom: 16, fontSize: 13 }}
        onClick={onBack}>← Назад</button>

      {/* Основная карточка */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
          <h2 style={{ margin: 0, flex: 1 }}>{ch.title}</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
            <span className="badge">{TYPE_LABELS[ch.ch_type]}</span>
            {ch.is_child && <span className="badge" style={{ background: "var(--success)", fontSize: 11 }}>🤝 участие</span>}
          </div>
        </div>

        <div className="hint" style={{ fontSize: 13, marginBottom: 4 }}>{goalStr(ch)}</div>
        <div className="hint" style={{ fontSize: 12 }}>Автор: {ch.author_nick}</div>

        {ch.penalty && (
          <div style={{ marginTop: 6, fontSize: 13, color: "var(--text-muted)" }}>
            Ставка автора: {ch.penalty}
          </div>
        )}

        {ch.deadline && (
          <div style={{ marginTop: 4, fontSize: 12, color: ch.days_left === 0 ? "var(--warning)" : "var(--text-dim)" }}>
            {ch.days_left !== null
              ? ch.days_left === 0 ? "⏰ Последний день!" : `⏳ ${ch.days_left} дн. до конца`
              : `До ${fmtDate(ch.deadline)}`}
          </div>
        )}
        {ch.is_paused && (
          <div style={{ marginTop: 4, fontSize: 12, color: "#4a9eff", fontWeight: 500 }}>
            ❄️ Заморожен до разморозки администратором
          </div>
        )}
        {!ch.is_active && ch.result === "completed" && (
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--success)", fontWeight: 500 }}>
            🏆 Выполнен
          </div>
        )}
        {!ch.is_active && ch.result === "failed" && (
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--danger)", fontWeight: 500 }}>
            😔 Не выполнен
          </div>
        )}
        {!ch.is_active && ch.result === "closed" && (
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-muted)", fontWeight: 500 }}>
            🏁 Завершён по запросу
          </div>
        )}

        <div className="divider" />

        {/* Прогресс */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 500, textTransform: "uppercase",
            letterSpacing: "0.04em", color: "var(--text-muted)", marginBottom: 6 }}>
            {ch.is_owner ? "Мой прогресс" : ch.is_participant ? "Мой прогресс" : "Прогресс автора"}
          </div>
          <ProgressBar ch={ch} />
        </div>

        {/* Кнопки действий */}
        {ch.is_active && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {ch.is_owner && !ch.close_requested && !ch.pause_requested && !ch.is_paused && (
              <button className="btn btn-secondary" style={{ fontSize: 13, opacity: 0.7 }}
                onClick={() => setShowCloseForm(v => !v)}>
                🏁 Запросить завершение
              </button>
            )}
            {ch.is_owner && ch.close_requested && (
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                ⏳ Запрос на завершение отправлен администратору
              </div>
            )}
            {ch.is_owner && !ch.is_paused && !ch.pause_requested && !ch.close_requested && (
              <button className="btn btn-secondary" style={{ fontSize: 13, opacity: 0.7 }}
                onClick={() => setShowPauseForm(v => !v)}>
                ⏸ Запросить паузу
              </button>
            )}
            {ch.is_owner && ch.pause_requested && !ch.is_paused && (
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                ⏳ Запрос на паузу отправлен администратору
              </div>
            )}
            {ch.is_owner && ch.is_paused && (
              <button className="btn btn-secondary" style={{ fontSize: 13, opacity: 0.7 }}
                disabled={requestUnfreezeMut.isPending}
                onClick={() => requestUnfreezeMut.mutate()}>
                {requestUnfreezeMut.isPending ? "..." : "▶️ Запросить разморозку"}
              </button>
            )}
            {ch.is_owner && ch.is_active && !ch.result && (
              <button className="btn btn-danger" style={{ fontSize: 13 }}
                onClick={() => {
                  setShowSurrender(true);
                  setSurrenderCountdown(10);
                  if (surrenderTimer.current) clearInterval(surrenderTimer.current);
                  surrenderTimer.current = setInterval(() => {
                    setSurrenderCountdown(v => {
                      if (v <= 1) { clearInterval(surrenderTimer.current); return 0; }
                      return v - 1;
                    });
                  }, 1000);
                }}>
                🏳️ Сдаться
              </button>
            )}
            {ch.is_child && ch.is_active && !ch.result && (() => {
              // Дочерний челлендж — кнопки участника (новая архитектура)
              return (
                <>
                  {!ch.close_requested ? (
                    <button className="btn btn-secondary" style={{ fontSize: 13, opacity: 0.8 }}
                      onClick={() => setShowCloseForm(v => !v)}>
                      🏁 Запросить завершение
                    </button>
                  ) : (
                    <div style={{ fontSize: 13, color: "var(--text-muted)" }}>⏳ Завершение на рассмотрении</div>
                  )}
                  {!ch.is_paused && !ch.pause_requested && (
                    <button className="btn btn-secondary" style={{ fontSize: 13, opacity: 0.8 }}
                      onClick={() => setShowPauseForm(v => !v)}>
                      ⏸ Запросить паузу
                    </button>
                  )}
                  {ch.pause_requested && !ch.is_paused && (
                    <div style={{ fontSize: 13, color: "var(--text-muted)" }}>⏳ Пауза на рассмотрении</div>
                  )}
                  {ch.is_paused && (
                    <button className="btn btn-secondary" style={{ fontSize: 13, opacity: 0.7 }}
                      disabled={requestUnfreezeMut.isPending}
                      onClick={() => requestUnfreezeMut.mutate()}>
                      {requestUnfreezeMut.isPending ? "..." : "▶️ Запросить разморозку"}
                    </button>
                  )}
                  <button className="btn btn-danger" style={{ fontSize: 13 }}
                    onClick={() => {
                      setShowSurrender(true);
                      setSurrenderCountdown(10);
                      if (surrenderTimer.current) clearInterval(surrenderTimer.current);
                      surrenderTimer.current = setInterval(() => {
                        setSurrenderCountdown(v => {
                          if (v <= 1) { clearInterval(surrenderTimer.current); return 0; }
                          return v - 1;
                        });
                      }, 1000);
                    }}>
                    🏳️ Сдаться
                  </button>
                </>
              );
            })()}
            {ch.is_participant && !ch.is_owner && !ch.is_child && (() => {
              // Старая архитектура совместимость — показываем только факт участия
              const myPart = ch.participants.find(p => p.user_id === ch.viewer_id);
              if (myPart?.result) return null;
              return (
                <div style={{ fontSize: 13, color: "var(--text-muted)" }}>✅ Ты участвуешь</div>
              );
            })()}

            {!ch.is_owner && !ch.is_participant && !ch.is_child && ch.author_nick && (
              !showJoinForm ? (
                <button className="btn btn-primary" onClick={() => setShowJoinForm(true)}>
                  Присоединиться
                </button>
              ) : null
            )}
          </div>
        )}
      </div>

      {/* Форма присоединения */}
      {/* Подтверждение сдачи */}
      {showSurrender && (
        <div className="card" style={{ marginTop: 0, borderColor: "var(--danger)" }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: "var(--danger)" }}>
            🏳️ Подтверди сдачу
          </div>
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>
            Результат будет зафиксирован как не выполнен.
            {ch.penalty && (
              <span style={{ color: "var(--warning)" }}>
                {" "}Ставка: {ch.penalty}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-danger"
              disabled={surrenderCountdown > 0 || surrenderMut.isPending}
              onClick={() => surrenderMut.mutate()}>
              {surrenderCountdown > 0 ? `Подождите ${surrenderCountdown}с` : (surrenderMut.isPending ? "..." : "Подтвердить")}
            </button>
            <button className="btn btn-secondary" onClick={() => {
              setShowSurrender(false);
              if (surrenderTimer.current) clearInterval(surrenderTimer.current);
            }}>
              Отмена
            </button>
          </div>
        </div>
      )}

      {/* Форма причины завершения (для owner и is_child) */}
      {showCloseForm && ch.is_active && (
        <div className="card" style={{ marginTop: 0 }}>
          <div className="form-group">
            <label>Причина завершения (необязательно)</label>
            <input value={closeReason} onChange={e => setCloseReason(e.target.value)}
              placeholder="Например: выполнил цель досрочно, изменились планы..." />
          </div>
          {(ch.is_owner ? requestCloseMut.data : reqClosePartMut.data) &&
           !(ch.is_owner ? requestCloseMut.data?.ok : reqClosePartMut.data?.ok) && (
            <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 8 }}>
              {(ch.is_owner ? requestCloseMut.data?.reason : reqClosePartMut.data?.reason)}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary"
              disabled={ch.is_owner ? requestCloseMut.isPending : reqClosePartMut.isPending}
              onClick={() => ch.is_owner ? requestCloseMut.mutate() : reqClosePartMut.mutate()}>
              {(ch.is_owner ? requestCloseMut.isPending : reqClosePartMut.isPending) ? "..." : "Отправить запрос"}
            </button>
            <button className="btn btn-secondary" onClick={() => setShowCloseForm(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}

      {/* Форма причины паузы */}
      {showPauseForm && ch.is_active && !ch.is_paused && (
        <div className="card" style={{ marginTop: 0 }}>
          <div className="form-group">
            <label>Причина паузы (необязательно)</label>
            <input value={pauseReason} onChange={e => setPauseReason(e.target.value)}
              placeholder="Например: травма, командировка..." />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary"
              disabled={ch.is_owner || ch.is_child ? (ch.is_child ? reqPausePartMut.isPending : requestPauseMut.isPending) : reqPausePartMut.isPending}
              onClick={() => ch.is_child ? reqPausePartMut.mutate() : requestPauseMut.mutate()}>
              {(ch.is_child ? reqPausePartMut.isPending : requestPauseMut.isPending) ? "..." : "Отправить запрос"}
            </button>
            <button className="btn btn-secondary" onClick={() => setShowPauseForm(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}

      {showJoinForm && ch.is_active && !ch.is_owner && !ch.is_participant && (
        <div className="card" style={{ marginTop: 0 }}>
          <div className="form-group">
            <label>Твоя ставка (необязательно)</label>
            <input value={penalty} onChange={e => setPenalty(e.target.value)}
              placeholder="Например: куплю всем кофе" />
          </div>
          {joinMut.data && !joinMut.data.ok && (
            <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 8 }}>
              {joinMut.data.reason}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" disabled={joinMut.isPending}
              onClick={() => joinMut.mutate()}>
              {joinMut.isPending ? "..." : "Подтвердить"}
            </button>
            <button className="btn btn-secondary" onClick={() => setShowJoinForm(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}

      {/* Участники */}
      {ch.participants.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden", marginTop: 0 }}>
          <div style={{ padding: "10px 16px 0", fontSize: 12, fontWeight: 500,
            textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--text-muted)" }}>
            Участники ({ch.participants.length})
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
              <div style={{ fontSize: 13, color: "var(--text-muted)", textAlign: "right" }}>
                {ch.ch_type === "weekly_runs"
                  ? `${p.current_runs} пробежек`
                  : `${p.current_value.toFixed(1)} км`}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// ─── Строка в списке ─────────────────────────────────────────

function ChallengeRow({ ch, onClick }) {
  const pct = progressPct(ch);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "12px 16px", cursor: "pointer",
      borderBottom: "1px solid var(--border)",
      opacity: ch.is_active ? 1 : 0.6,
    }} onClick={() => onClick(ch.id)}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 2 }}>
          {ch.is_child && <span style={{ fontSize: 11, color: "var(--success)", marginRight: 5 }}>🤝</span>}
          {ch.title}
          {!ch.is_active && <span style={{ marginLeft: 6, fontSize: 11,
            color: "var(--text-dim)", fontWeight: 400 }}>завершён</span>}
        </div>
        <div className="hint" style={{ fontSize: 12 }}>
          {TYPE_LABELS[ch.ch_type]} · {goalStr(ch)}
        </div>
        {ch.is_active && <ProgressBar ch={ch} style={{ marginTop: 4 }} />}
        {ch.is_active && ch.days_left !== null && ch.days_left <= 3 && (
          <div style={{ fontSize: 11, color: ch.days_left === 0 ? "var(--danger)" : "#f0a000", marginTop: 2 }}>
            {ch.days_left === 0 ? "⏰ Последний день!" : `⏳ ${ch.days_left} дн. осталось`}
          </div>
        )}
      </div>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
        stroke="var(--text-dim)" strokeWidth="2" strokeLinecap="round">
        <path d="M9 18l6-6-6-6"/>
      </svg>
    </div>
  );
}


// ─── Форма создания ──────────────────────────────────────────

const TYPES = [
  { id: "weekly_runs", label: "📜 Регулярный",        desc: "N пробежек в неделю" },
  { id: "daily_km",   label: "🎯 Дневной спринт",     desc: "N км за 1 день" },
  { id: "weekly_km",  label: "📅 Недельный спринт",   desc: "N км за 7 дней" },
  { id: "monthly_km", label: "📆 Месячный спринт",    desc: "N км за 30 дней" },
  { id: "race",       label: "🏁 Забег",              desc: "N км до дедлайна" },
];

function CreateForm({ onSuccess }) {
  const qc = useQueryClient();
  const [step, setStep] = useState("type"); // "type" | "form"
  const [chType, setChType] = useState(null);
  function todayStr() {
    return new Date().toISOString().split("T")[0];
  }
  const [form, setForm] = useState({
    title: "", penalty: "", is_public: true,
    goal_runs: "", goal_value: "",
    min_per_run: "", min_minutes_per_run: "",
    started_at: todayStr(),
    deadline: defaultDeadline(), has_deadline: false,
  });
  const [err, setErr] = useState("");
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }));
  const setB = k => e => setForm(f => ({ ...f, [k]: e.target.checked }));

  const mut = useMutation({
    mutationFn: createChallenge,
    onSuccess: d => {
      if (d.ok) {
        qc.invalidateQueries({ queryKey: ["challenges-my"] });
        onSuccess();
      } else {
        setErr(d.reason);
      }
    },
  });

  const handleSubmit = () => {
    if (!form.title.trim()) { setErr("Введи название"); return; }
    if (chType === "weekly_runs" && !form.goal_runs) { setErr("Укажи количество пробежек"); return; }
    if (["daily_km","weekly_km","monthly_km","race"].includes(chType) && !form.goal_value) {
      setErr("Укажи целевую дистанцию"); return;
    }
    setErr("");
    mut.mutate({
      title:               form.title.trim(),
      ch_type:             chType,
      penalty:             form.penalty.trim() || null,
      is_public:           form.is_public,
      goal_runs:           +form.goal_runs    || 0,
      goal_value:          +form.goal_value   || 0,
      min_per_run:         +form.min_per_run  || 0,
      min_minutes_per_run: +form.min_minutes_per_run || 0,
      started_at:          form.started_at ? dateInputToApi(form.started_at) : null,
      deadline:            (chType === "weekly_runs" || chType === "race") && form.deadline && (chType === "race" || form.has_deadline)
        ? dateInputToApi(form.deadline) : null,
    });
  };

  if (step === "type") return (
    <div>
      <button className="btn btn-secondary"
        style={{ width: "auto", padding: "7px 14px", marginBottom: 16, fontSize: 13 }}
        onClick={onSuccess}>← Назад</button>
      <div className="card">
        <h2 style={{ marginBottom: 4 }}>Новый челлендж</h2>
        <div className="hint" style={{ marginBottom: 16, fontSize: 13 }}>Выбери тип</div>
        {TYPES.map(t => (
          <div key={t.id} style={{
            padding: "12px 14px", borderRadius: 8, border: "1px solid var(--border)",
            marginBottom: 8, cursor: "pointer", background: "var(--bg-input)",
          }} onClick={() => { setChType(t.id); setStep("form"); }}>
            <div style={{ fontWeight: 500, fontSize: 14 }}>{t.label}</div>
            <div className="hint" style={{ fontSize: 12, marginTop: 2 }}>{t.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );

  // Форма по типу
  const isWeeklyRuns = chType === "weekly_runs";
  const isSprint     = ["daily_km","weekly_km","monthly_km"].includes(chType);
  const isRace       = chType === "race";

  return (
    <div>
      <button className="btn btn-secondary"
        style={{ width: "auto", padding: "7px 14px", marginBottom: 16, fontSize: 13 }}
        onClick={() => setStep("type")}>← Тип</button>

      <div className="card">
        <div style={{ fontSize: 12, color: "var(--accent)", marginBottom: 12 }}>
          {TYPES.find(t => t.id === chType)?.label}
        </div>

        <div className="form-group">
          <label>Название *</label>
          <input value={form.title} onChange={set("title")} placeholder="Например: 100 км за месяц" />
        </div>

        <div className="form-group">
          <label>Дата старта</label>
          <input value={form.started_at} onChange={set("started_at")} type="date"
            min={new Date().toISOString().split("T")[0]} />
          <div className="hint" style={{ fontSize: 11, marginTop: 4 }}>
            Сегодня или в будущем. Для забега — дата самого забега.
          </div>
        </div>

        {isWeeklyRuns && (
          <>
            <div className="form-group">
              <label>Пробежек в неделю *</label>
              <input value={form.goal_runs} onChange={set("goal_runs")} type="number" min="1" placeholder="3" />
            </div>
            <div className="form-group">
              <label>Мин. км за пробежку (или 0)</label>
              <input value={form.min_per_run} onChange={set("min_per_run")} type="number" step="0.1" placeholder="0" />
            </div>
            <div className="form-group">
              <label>Мин. минут за пробежку (или 0)</label>
              <input value={form.min_minutes_per_run} onChange={set("min_minutes_per_run")} type="number" placeholder="0" />
            </div>
            <div className="hint" style={{ fontSize: 12, marginBottom: 12 }}>
              Условия объединяются через ИЛИ: засчитывается если выполнено любое из них
            </div>
            <div className="form-group" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input type="checkbox" id="has_deadline" checked={!!form.has_deadline}
                onChange={e => setForm(f => ({ ...f, has_deadline: e.target.checked, deadline: e.target.checked ? defaultDeadline() : "" }))} />
              <label htmlFor="has_deadline" style={{ marginBottom: 0 }}>Установить дедлайн</label>
            </div>
            {form.has_deadline && (
              <div className="form-group">
                <input value={form.deadline} onChange={set("deadline")} type="date" />
              </div>
            )}
          </>
        )}

        {(isSprint || isRace) && (
          <div className="form-group">
            <label>Целевая дистанция (км) *</label>
            <input value={form.goal_value} onChange={set("goal_value")} type="number" step="0.1" placeholder="50" />
          </div>
        )}

        {isRace && (
          <div className="form-group">
            <label>Дедлайн *</label>
            <input value={form.deadline} onChange={set("deadline")} type="date" />
          </div>
        )}

        {isSprint && (
          <div className="hint" style={{ fontSize: 12, marginBottom: 12 }}>
            Срок: {chType === "daily_km" ? "1 день" : chType === "weekly_km" ? "7 дней" : "30 дней"} с момента создания
          </div>
        )}

        <div className="form-group">
          <label>Твоя ставка (необязательно)</label>
          <input value={form.penalty} onChange={set("penalty")} placeholder="Куплю кофе проигравшему" />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
          <input type="checkbox" id="is_public" checked={form.is_public} onChange={setB("is_public")} />
          <label htmlFor="is_public" style={{ fontSize: 13, cursor: "pointer" }}>
            Публичный (виден всему клубу)
          </label>
        </div>

        {err && <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 10 }}>{err}</div>}

        <button className="btn btn-primary" disabled={mut.isPending} onClick={handleSubmit}>
          {mut.isPending ? "Создание..." : "Создать челлендж"}
        </button>
      </div>
    </div>
  );
}


// ─── Список с пагинацией ─────────────────────────────────────

function ChallengeList({ queryKey, queryFn, paginated = false, emptyText }) {
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(null);
  const PAGE_SIZE = 10;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: [queryKey, page],
    queryFn: () => paginated ? queryFn(page) : queryFn(),
    staleTime: 20_000,
  });
  const countQ = useQuery({
    queryKey: [queryKey + "-count"],
    queryFn: getClubChallengesCount,
    enabled: paginated,
    staleTime: 60_000,
  });

  if (selected !== null) return (
    <ChallengeDetail id={selected} onBack={() => setSelected(null)} />
  );
  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;
  if (!data?.length) return (
    <div className="empty-state">
      <div className="empty-icon">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="1.2">
          <circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>
        </svg>
      </div>
      <div className="empty-title">{emptyText}</div>
    </div>
  );

  const total = countQ.data?.total || 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {data.map((ch, i) => (
          <div key={ch.id}
            style={{ borderBottom: i < data.length - 1 ? "1px solid var(--border)" : "none" }}>
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


// ─── Главный компонент ───────────────────────────────────────

export default function Challenges() {
  const [tab, setTab]       = useState("my");
  const [create, setCreate] = useState(false);

  if (create) return <CreateForm onSuccess={() => setCreate(false)} />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 18 }}>
        <h1 style={{ margin: 0 }}>Челленджи</h1>
        <button className="btn btn-secondary"
          style={{ width: "auto", padding: "7px 14px", fontSize: 13 }}
          onClick={() => setCreate(true)}>
          + Создать
        </button>
      </div>

      <div className="tabs">
        <button className={"tab" + (tab === "my"      ? " active" : "")} onClick={() => setTab("my")}>Мои</button>
        <button className={"tab" + (tab === "club"    ? " active" : "")} onClick={() => setTab("club")}>Клуб</button>
        <button className={"tab" + (tab === "history" ? " active" : "")} onClick={() => setTab("history")}>История</button>
      </div>

      {tab === "my" && (
        <ChallengeList
          queryKey="challenges-my"
          queryFn={getMyChallenges}
          emptyText="Нет активных челленджей"
        />
      )}
      {tab === "club" && (
        <ChallengeList
          queryKey="challenges-club"
          queryFn={getClubChallenges}
          paginated
          emptyText="Нет публичных челленджей"
        />
      )}
      {tab === "history" && (
        <ChallengeList
          queryKey="challenges-history"
          queryFn={getMyChallengesHistory}
          emptyText="История пуста"
        />
      )}
    </div>
  );
}