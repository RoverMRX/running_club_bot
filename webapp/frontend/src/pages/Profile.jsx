import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getProfile, getLeaderboard, getInitData } from "../api";
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

function Leaderboard({ data }) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      {data.map((u, i) => (
        <div key={u.tg_id} style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "12px 16px",
          borderBottom: i < data.length - 1 ? "1px solid var(--border)" : "none",
        }}>
          <div style={{
            width: 28, textAlign: "center",
            fontSize: i < 3 ? 14 : 12,
            color: i === 0 ? "#f0c040" : i === 1 ? "#aaa" : i === 2 ? "#cd7f32" : "var(--text-dim)",
            fontWeight: 600,
          }}>
            {i < 3 ? ["1st", "2nd", "3rd"][i] : `${i + 1}`}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 500, fontSize: 14 }}>{u.school_nick}</div>
            {u.username && <div className="hint" style={{ fontSize: 12 }}>@{u.username}</div>}
          </div>
          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div style={{ fontWeight: 600 }}>{u.xp} XP</div>
            <div className="hint" style={{ fontSize: 12 }}>
              Ур. {u.level} · стрик {u.streak}
            </div>
          </div>
        </div>
      ))}
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
  const [tab, setTab] = useState("profile");
  const initReady = useInitDataReady();

  const profileQ = useQuery({
    queryKey: ["profile"],
    queryFn: getProfile,
    enabled: initReady,
    staleTime: 30_000,
  });

  const leaderQ = useQuery({
    queryKey: ["leaderboard"],
    queryFn: getLeaderboard,
    enabled: initReady && tab === "leaders",
    staleTime: 60_000,
  });

  if (!initReady || profileQ.isLoading) return <Loader />;
  if (profileQ.isError) return <ErrorMessage error={profileQ.error} />;

  return (
    <div>
      <div className="tabs">
        <button className={"tab" + (tab === "profile" ? " active" : "")} onClick={() => setTab("profile")}>Профиль</button>
        <button className={"tab" + (tab === "leaders" ? " active" : "")} onClick={() => setTab("leaders")}>Лидеры</button>
      </div>
      {tab === "profile" && <ProfileCard p={profileQ.data} />}
      {tab === "leaders" && (
        leaderQ.isLoading ? <Loader /> :
        leaderQ.isError   ? <ErrorMessage error={leaderQ.error} /> :
        <Leaderboard data={leaderQ.data} />
      )}
    </div>
  );
}