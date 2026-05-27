import { useQuery } from "@tanstack/react-query";
import { getPublicProfile } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";
import { useState } from "react";

const CATEGORY_LABELS = {
  km: "🏃 Километраж", streak: "🔥 Стрик", pr: "🏅 Личный рекорд",
  event: "📋 Мероприятия", tournament: "🏆 Турниры", special: "✨ Особые",
};

function AchBadge({ ach, onClick }) {
  return (
    <div onClick={() => onClick(ach)} style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      gap: 4, cursor: "pointer", opacity: ach.earned ? 1 : 0.3,
    }}>
      <div style={{
        width: 52, height: 52, borderRadius: "50%", overflow: "hidden",
        background: "var(--bg-input)",
        border: ach.earned ? "2px solid var(--accent)" : "2px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {ach.image_url
          ? <img src={ach.image_url} alt={ach.name}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
              onError={e => { e.target.style.display = "none"; }} />
          : <span style={{ fontSize: 22 }}>🏅</span>}
      </div>
      <div style={{ fontSize: 9, textAlign: "center", color: ach.earned ? "var(--text)" : "var(--text-dim)",
        maxWidth: 52, lineHeight: 1.2 }}>{ach.name}</div>
    </div>
  );
}

function AchModal({ ach, onClose }) {
  if (!ach) return null;
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, padding: 20 }} onClick={onClose}>
      <div style={{ background: "var(--bg-card)", borderRadius: 16,
        padding: 24, maxWidth: 280, width: "100%", textAlign: "center"
      }} onClick={e => e.stopPropagation()}>
        <div style={{ width: 80, height: 80, borderRadius: "50%", margin: "0 auto 12px",
          overflow: "hidden", background: "var(--bg-input)", opacity: ach.earned ? 1 : 0.4,
          display: "flex", alignItems: "center", justifyContent: "center" }}>
          {ach.image_url
            ? <img src={ach.image_url} alt={ach.name} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            : <span style={{ fontSize: 40 }}>🏅</span>}
        </div>
        <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 6 }}>{ach.name}</div>
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>{ach.description}</div>
        {ach.earned
          ? <div style={{ fontSize: 12, color: "var(--success)" }}>
              ✅ {new Date(ach.earned_at).toLocaleDateString("ru")}
            </div>
          : <div style={{ fontSize: 12, color: "var(--text-dim)" }}>Не получена</div>}
        <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={onClose}>Закрыть</button>
      </div>
    </div>
  );
}

export default function PublicProfile({ tg_id, onBack }) {
  const [modal, setModal] = useState(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["public-profile", tg_id],
    queryFn: () => getPublicProfile(tg_id),
    staleTime: 30_000,
  });

  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;

  const earned = data.achievements.filter(a => a.earned);
  const grouped = {};
  for (const a of data.achievements) {
    if (!grouped[a.category]) grouped[a.category] = [];
    grouped[a.category].push(a);
  }

  return (
    <div>
      <AchModal ach={modal} onClose={() => setModal(null)} />

      <button className="btn btn-secondary"
        style={{ width: "auto", padding: "7px 14px", marginBottom: 16, fontSize: 13 }}
        onClick={onBack}>← Назад</button>

      {/* Карточка профиля */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
          <div style={{ width: 56, height: 56, borderRadius: "50%",
            background: "var(--bg-input)", display: "flex", alignItems: "center",
            justifyContent: "center", fontSize: 24, flexShrink: 0 }}>
            🏃
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16 }}>{data.school_nick || data.full_name || "Бегун"}</div>
            {data.username && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>@{data.username}</div>}
            <div style={{ fontSize: 12, color: "var(--accent)", marginTop: 2 }}>
              Ур. {data.level} · {data.xp} XP
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
          {[
            { label: "Пробежек", value: data.total_runs },
            { label: "Всего км", value: `${data.total_km.toFixed(1)}` },
            { label: "Лучшая",   value: `${data.best_km.toFixed(1)} км` },
          ].map(s => (
            <div key={s.label} style={{ textAlign: "center", background: "var(--bg-input)",
              borderRadius: 8, padding: "8px 4px" }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>{s.value}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Ачивки */}
      {earned.length > 0 && (
        <div className="card">
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>
            🏅 Ачивки · {earned.length}/{data.achievements.length}
          </div>
          {Object.entries(grouped).map(([cat, achs]) => {
            const catEarned = achs.filter(a => a.earned);
            if (catEarned.length === 0) return null;
            return (
              <div key={cat} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                  textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
                  {CATEGORY_LABELS[cat] || cat}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
                  {achs.map(a => <AchBadge key={a.slug} ach={a} onClick={setModal} />)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
