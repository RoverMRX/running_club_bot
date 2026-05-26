import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getProfile, getLeaderboard, getAchievements, getInitData } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";

const LEVEL_LABEL = (lvl) =>
  lvl >= 20 ? "Атлет" : lvl >= 10 ? "Мастер" : lvl >= 5 ? "Бегун" : "Новичок";

function StatGrid({ items }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 16 }}>
      {items.map(({ label, value }) => (
        <div key={label} style={{
          background: "var(--bg-input)", borderRadius: 8,
          padding: "12px 14px", border: "1px solid var(--border)"
        }}>
          <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.02em" }}>{value}</div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
        </div>
      ))}
    </div>
  );
}

function ProfileCard({ p }) {
  // xp_in_level и xp_to_next приходят с бэкенда
  const xpIn   = p.xp_in_level ?? (p.xp % 100);   // fallback для старых ответов
  const xpNext = p.xp_to_next  ?? 100;
  const pct    = xpNext > 0 ? Math.min(100, Math.round(xpIn / xpNext * 100)) : 0;

  return (
    <div>
      <div className="card" style={{ marginBottom: 8 }}>
        {/* Шапка: аватар + имя + XP */}
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{
            width: 52, height: 52, borderRadius: "50%",
            background: "var(--bg-input)", border: "1px solid var(--border)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 20, fontWeight: 700, color: "var(--text-muted)", flexShrink: 0,
          }}>
            {(p.school_nick || "?")[0].toUpperCase()}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 17 }}>{p.school_nick}</div>
            {p.username && <div className="hint">@{p.username}</div>}
            <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>
              {LEVEL_LABEL(p.level)} · Ур. {p.level}
            </div>
          </div>
          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{p.xp}</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>XP</div>
          </div>
        </div>

        {/* Прогресс-бар уровня */}
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span className="hint" style={{ fontSize: 12 }}>До уровня {p.level + 1}</span>
            <span className="hint" style={{ fontSize: 12 }}>{xpIn} / {xpNext} XP</span>
          </div>
          <div className="progress-wrap" style={{ height: 4 }}>
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <div style={{ fontSize: 10, color: "var(--text-dim)", textAlign: "right", marginTop: 3 }}>
            {pct}%
          </div>
        </div>
      </div>

      <StatGrid items={[
        { label: "Стрик",         value: `${p.streak} нед` },
        { label: "Сезон XP",      value: p.season_xp },
        { label: "Личный рекорд", value: p.best_km != null ? `${p.best_km} км` : "—" },
        { label: "Уровень",       value: p.level },
      ]} />
    </div>
  );
}


const CATEGORY_LABELS = {
  km:         "🏃 Километраж",
  streak:     "🔥 Стрик",
  pr:         "🏅 Личный рекорд",
  event:      "📋 Мероприятия",
  tournament: "🏆 Турниры",
  special:    "✨ Особые",
};

function AchievementBadge({ ach, onClick }) {
  const earned = ach.earned;
  return (
    <div onClick={() => onClick(ach)}
      style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        gap: 6, cursor: "pointer", opacity: earned ? 1 : 0.35,
      }}>
      <div style={{
        width: 64, height: 64, borderRadius: "50%",
        overflow: "hidden", background: "var(--bg-input)",
        border: earned ? "2px solid var(--accent)" : "2px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
      }}>
        {ach.image_url ? (
          <img
            src={ach.image_url}
            alt={ach.name}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
            onError={e => { e.target.style.display = "none"; e.target.nextSibling.style.display = "flex"; }}
          />
        ) : null}
        <div style={{
          display: ach.image_url ? "none" : "flex",
          width: "100%", height: "100%",
          alignItems: "center", justifyContent: "center",
          fontSize: 28,
        }}>🏅</div>
      </div>
      <div style={{
        fontSize: 10, textAlign: "center", lineHeight: 1.2,
        color: earned ? "var(--text)" : "var(--text-dim)",
        maxWidth: 64, wordBreak: "break-word",
      }}>{ach.name}</div>
    </div>
  );
}

function AchievementsModal({ ach, onClose }) {
  if (!ach) return null;
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, padding: 20,
    }} onClick={onClose}>
      <div style={{
        background: "var(--bg-card)", borderRadius: 16,
        padding: 24, maxWidth: 300, width: "100%",
        textAlign: "center",
      }} onClick={e => e.stopPropagation()}>
        <div style={{
          width: 96, height: 96, borderRadius: "50%",
          overflow: "hidden", margin: "0 auto 16px",
          background: "var(--bg-input)",
          border: ach.earned ? "3px solid var(--accent)" : "3px solid var(--border)",
          display: "flex", alignItems: "center", justifyContent: "center",
          opacity: ach.earned ? 1 : 0.4,
        }}>
          {ach.image_url
            ? <img src={ach.image_url} alt={ach.name} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            : <span style={{ fontSize: 48 }}>🏅</span>}
        </div>
        <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 8 }}>{ach.name}</div>
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>{ach.description}</div>
        {ach.earned
          ? <div style={{ fontSize: 12, color: "var(--success)" }}>
              ✅ Получена {new Date(ach.earned_at).toLocaleDateString("ru")}
            </div>
          : <div style={{ fontSize: 12, color: "var(--text-dim)" }}>Пока не получена</div>}
        <button className="btn btn-secondary" style={{ marginTop: 16 }} onClick={onClose}>Закрыть</button>
      </div>
    </div>
  );
}

function AchievementsPage({ data }) {
  const [selected, setSelected] = useState(null);
  const grouped = {};
  for (const ach of data) {
    if (!grouped[ach.category]) grouped[ach.category] = [];
    grouped[ach.category].push(ach);
  }
  const earnedCount = data.filter(a => a.earned).length;

  return (
    <div>
      <AchievementsModal ach={selected} onClose={() => setSelected(null)} />
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
        Получено: {earnedCount} / {data.length}
      </div>
      {Object.entries(grouped).map(([cat, achs]) => (
        <div key={cat} style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)",
            textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 12 }}>
            {CATEGORY_LABELS[cat] || cat}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
            {achs.map(a => <AchievementBadge key={a.slug} ach={a} onClick={setSelected} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

const PERIODS  = [{v:"alltime",l:"Всё время"},{v:"season",l:"Сезон"},{v:"month",l:"Месяц"},{v:"week",l:"Неделя"}];
const SORTS    = [{v:"xp",l:"XP"},{v:"km",l:"км"},{v:"runs",l:"пробежки"},{v:"streak",l:"стрик"}];

function PillBar({ options, value, onChange }) {
  return (
    <div style={{ display:"flex", gap:4, flexWrap:"wrap" }}>
      {options.map(o => (
        <button key={o.v} onClick={() => onChange(o.v)}
          style={{
            padding:"4px 10px", borderRadius:20, border:"1px solid var(--border)",
            background: value===o.v ? "var(--accent)" : "var(--bg-input)",
            color: value===o.v ? "#000" : "var(--text)",
            fontSize:12, cursor:"pointer", fontWeight: value===o.v ? 600 : 400,
          }}>
          {o.l}
        </button>
      ))}
    </div>
  );
}

function LeaderRow({ u, i, sortBy }) {
  const medalColors = ["#f0c040","#aaa","#cd7f32"];
  let metric = `${u.xp} XP`;
  let sub    = `Ур. ${u.level} · стрик ${u.streak}`;
  if (sortBy === "km" && u.km != null)    { metric = `${u.km.toFixed(1)} км`; sub = `${u.xp} XP · Ур. ${u.level}`; }
  if (sortBy === "runs" && u.runs != null) { metric = `${u.runs} бег`; sub = `${u.km?.toFixed(1) ?? "—"} км · ${u.xp} XP`; }
  if (sortBy === "streak")                { metric = `${u.streak} нед`; sub = `${u.xp} XP · Ур. ${u.level}`; }
  return (
    <div style={{
      display:"flex", alignItems:"center", gap:12,
      padding:"12px 16px",
      borderBottom: "1px solid var(--border)",
    }}>
      <div style={{
        width:28, textAlign:"center",
        fontSize: i < 3 ? 16 : 12,
        color: i < 3 ? medalColors[i] : "var(--text-dim)",
        fontWeight:600,
      }}>
        {i < 3 ? ["🥇","🥈","🥉"][i] : `${i+1}`}
      </div>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ fontWeight:500, fontSize:14 }}>{u.school_nick}</div>
        {u.username && <div className="hint" style={{ fontSize:12 }}>@{u.username}</div>}
      </div>
      <div style={{ textAlign:"right", flexShrink:0 }}>
        <div style={{ fontWeight:600, fontSize:14 }}>{metric}</div>
        <div className="hint" style={{ fontSize:11 }}>{sub}</div>
      </div>
    </div>
  );
}

function Leaderboard({ data, period, setPeriod, sortBy, setSortBy }) {
  return (
    <div>
      <div style={{ display:"flex", flexDirection:"column", gap:8, marginBottom:12 }}>
        <PillBar options={PERIODS} value={period} onChange={setPeriod} />
        <PillBar options={SORTS}   value={sortBy} onChange={setSortBy} />
      </div>
      <div className="card" style={{ padding:0, overflow:"hidden" }}>
        {data.length === 0 ? (
          <div style={{ padding:24, textAlign:"center", color:"var(--text-muted)" }}>Нет данных за этот период</div>
        ) : data.map((u, i) => (
          <LeaderRow key={u.tg_id} u={u} i={i} sortBy={sortBy} />
        ))}
      </div>
    </div>
  );
}

// Ждём пока появится initData ИЗ ЛЮБОГО источника
function useInitDataReady() {
  const [ready, setReady] = useState(() => !!getInitData());

  useEffect(() => {
    if (ready) return;
    let elapsed = 0;
    const id = setInterval(() => {
      elapsed += 100;
      if (getInitData() || elapsed >= 3000) {
        clearInterval(id);
        setReady(true);
      }
    }, 100);
    return () => clearInterval(id);
  }, []);

  return ready;
}

export default function Profile() {
  const [tab, setTab]       = useState("profile");
  const [period, setPeriod] = useState("alltime");
  const [sortBy, setSortBy] = useState("xp");
  const [achModal, setAchModal] = useState(null);
  const initReady = useInitDataReady();

  const profileQ = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
    enabled: initReady,
    staleTime: 30_000,
  });

  const leaderQ = useQuery({
    queryKey: ["leaderboard", period, sortBy],
    queryFn: () => getLeaderboard(period, sortBy),
    enabled: initReady && tab === "leaders",
    staleTime: 60_000,
  });

  const achQ = useQuery({
    queryKey: ["achievements"],
    queryFn: getAchievements,
    enabled: initReady,
    staleTime: 60_000,
  });

  if (!initReady || profileQ.isLoading) return <Loader />;
  if (profileQ.isError) return <ErrorMessage error={profileQ.error} />;

  return (
    <div>
      <div className="tabs">
        <button className={"tab" + (tab === "profile" ? " active" : "")} onClick={() => setTab("profile")}>Профиль</button>
        <button className={"tab" + (tab === "ach"     ? " active" : "")} onClick={() => setTab("ach")}>Ачивки</button>
        <button className={"tab" + (tab === "leaders" ? " active" : "")} onClick={() => setTab("leaders")}>Лидеры</button>
      </div>
      {tab === "profile" && (
        <div>
          <ProfileCard p={profileQ.data} />
          {achQ.data && achQ.data.filter(a => a.earned).length > 0 && (
            <div className="card" style={{ marginTop: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>🏅 Ачивки</div>
                <button style={{ fontSize: 12, color: "var(--accent)", background: "none",
                  border: "none", cursor: "pointer", padding: 0 }}
                  onClick={() => setTab("ach")}>
                  Все →
                </button>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {achQ.data.filter(a => a.earned).slice(0, 5).map(a => (
                  <AchievementBadge key={a.slug} ach={a} onClick={setAchModal} />
                ))}
              </div>
              <AchievementsModal ach={achModal} onClose={() => setAchModal(null)} />
            </div>
          )}
        </div>
      )}
      {tab === "ach" && (
        achQ.isLoading ? <Loader /> :
        achQ.isError   ? <ErrorMessage error={achQ.error} /> :
        <AchievementsPage data={achQ.data ?? []} />
      )}
      {tab === "leaders" && (
        leaderQ.isLoading ? <Loader /> :
        leaderQ.isError   ? <ErrorMessage error={leaderQ.error} /> :
        <Leaderboard data={leaderQ.data ?? []}
          period={period} setPeriod={p => { setPeriod(p); }}
          sortBy={sortBy} setSortBy={s => { setSortBy(s); }} />
      )}
    </div>
  );
}