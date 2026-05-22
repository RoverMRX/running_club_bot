import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getEvents, getArchiveEvents, getEvent,
  getEventTemplates, createEvent,
  joinEvent, leaveEvent,
} from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";

// ─── Утилиты ─────────────────────────────────────────────────

function fmt(dt) {
  if (!dt) return "—";
  return new Date(dt).toLocaleString("ru", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function defaultDatetime() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T09:00`;
}

function parseDatetimeInput(val) {
  if (!val) return "";
  const [date, time] = val.split("T");
  const [y, m, d] = date.split("-");
  return `${d}.${m}.${y} ${time}`;
}


// ─── Список участников ───────────────────────────────────────

function ParticipantsList({ participants }) {
  const going    = participants.filter(p => p.status === "going");
  const notGoing = participants.filter(p => p.status === "not_going");

  if (participants.length === 0) return (
    <div className="hint" style={{ textAlign: "center", padding: "8px 0", fontSize: 13 }}>
      Пока никто не записался
    </div>
  );

  return (
    <div>
      {going.length > 0 && (
        <>
          <div style={{ fontSize: 12, fontWeight: 500, textTransform: "uppercase",
            letterSpacing: "0.04em", color: "var(--text-muted)", margin: "8px 0 4px" }}>
            🏃 Идут ({going.length})
          </div>
          {going.map(p => (
            <div key={p.tg_id} style={{ display: "flex", alignItems: "center", gap: 8,
              padding: "6px 0", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
              <span style={{ fontWeight: 500 }}>{p.school_nick}</span>
              {p.username && <span className="hint">@{p.username}</span>}
            </div>
          ))}
        </>
      )}
      {notGoing.length > 0 && (
        <>
          <div style={{ fontSize: 12, fontWeight: 500, textTransform: "uppercase",
            letterSpacing: "0.04em", color: "var(--text-muted)", margin: "8px 0 4px" }}>
            ❌ Не идут ({notGoing.length})
          </div>
          {notGoing.map(p => (
            <div key={p.tg_id} style={{ display: "flex", alignItems: "center", gap: 8,
              padding: "6px 0", fontSize: 13, opacity: 0.6 }}>
              <span>{p.school_nick}</span>
              {p.username && <span className="hint">@{p.username}</span>}
            </div>
          ))}
        </>
      )}
    </div>
  );
}


// ─── Детальная карточка ──────────────────────────────────────

function EventDetail({ id, onBack }) {
  const qc = useQueryClient();
  const [showParticipants, setShowParticipants] = useState(false);

  const { data: ev, isLoading, isError, error } = useQuery({
    queryKey: ["event", id],
    queryFn: () => getEvent(id),
    staleTime: 15_000,
  });

  const inv = () => {
    qc.invalidateQueries({ queryKey: ["event", id] });
    qc.invalidateQueries({ queryKey: ["events"] });
    qc.invalidateQueries({ queryKey: ["events-archive"] });
  };

  const joinMut  = useMutation({ mutationFn: () => joinEvent(id),  onSuccess: inv });
  const leaveMut = useMutation({ mutationFn: () => leaveEvent(id), onSuccess: inv });

  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;

  const isPast = ev.event_date && new Date(ev.event_date) < new Date();

  return (
    <div>
      <button className="btn btn-secondary"
        style={{ width: "auto", padding: "7px 14px", marginBottom: 16, fontSize: 13 }}
        onClick={onBack}>← Назад</button>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
          <h2 style={{ margin: 0, flex: 1 }}>{ev.title}</h2>
          {ev.is_pending && (
            <span className="badge badge-pending">На модерации</span>
          )}
          {isPast && !ev.is_pending && (
            <span className="badge" style={{ background: "var(--text-dim)" }}>Прошло</span>
          )}
        </div>

        <div className="hint" style={{ fontSize: 13, marginBottom: 4 }}>📅 {fmt(ev.event_date)}</div>
        {ev.location    && <div className="hint" style={{ fontSize: 13 }}>📍 {ev.location}</div>}
        {ev.distance_km && <div className="hint" style={{ fontSize: 13 }}>🏃 {ev.distance_km} км</div>}
        {ev.description && <div style={{ marginTop: 8, fontSize: 13 }}>{ev.description}</div>}
        {ev.created_by_nick && (
          <div className="hint" style={{ fontSize: 12, marginTop: 6 }}>
            Организатор: {ev.created_by_nick}
          </div>
        )}

        <div className="divider" />

        <div style={{ display: "flex", gap: 16, fontSize: 13,
          color: "var(--text-muted)", marginBottom: 12 }}>
          <span>🏃 {ev.going_count} идут</span>
          <span>❌ {ev.not_going_count} не идут</span>
          <span>⭐ +{ev.xp_bonus} XP</span>
        </div>

        {/* Кнопки участия — только для опубликованных и не прошедших */}
        {!ev.is_pending && !isPast && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {ev.user_status === "going" ? (
              <button className="btn btn-secondary" disabled={leaveMut.isPending}
                onClick={() => leaveMut.mutate()}>
                ✅ Участвую · Отменить
              </button>
            ) : ev.user_status === "not_going" ? (
              <>
                <button className="btn btn-primary" disabled={joinMut.isPending}
                  onClick={() => joinMut.mutate()}>
                  {joinMut.isPending ? "..." : "🏃 Участвую"}
                </button>
                <span style={{ fontSize: 13, color: "var(--text-dim)", alignSelf: "center" }}>
                  · сейчас ты отказался
                </span>
              </>
            ) : (
              <>
                <button className="btn btn-primary" disabled={joinMut.isPending}
                  onClick={() => joinMut.mutate()}>
                  {joinMut.isPending ? "..." : "🏃 Участвую"}
                </button>
                <button className="btn btn-secondary" disabled={leaveMut.isPending}
                  onClick={() => leaveMut.mutate()}>
                  {leaveMut.isPending ? "..." : "❌ Не пойду"}
                </button>
              </>
            )}
          </div>
        )}

        {/* Мероприятие на модерации — информационный блок */}
        {ev.is_pending && (
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4 }}>
            ⏳ Ожидает публикации модератором
          </div>
        )}
      </div>

      {/* Участники */}
      <div className="card" style={{ marginTop: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between",
          alignItems: "center", cursor: "pointer" }}
          onClick={() => setShowParticipants(v => !v)}>
          <span style={{ fontWeight: 500, fontSize: 14 }}>
            👥 Участники ({ev.going_count})
          </span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke="var(--text-dim)" strokeWidth="2" strokeLinecap="round"
            style={{ transform: showParticipants ? "rotate(90deg)" : "none",
              transition: "transform 0.2s" }}>
            <path d="M9 18l6-6-6-6"/>
          </svg>
        </div>
        {showParticipants && (
          <div style={{ marginTop: 8 }}>
            <ParticipantsList participants={ev.participants || []} />
          </div>
        )}
      </div>
    </div>
  );
}


// ─── Карточка в списке ───────────────────────────────────────

function EventCard({ ev, onClick }) {
  const isPast = ev.event_date && new Date(ev.event_date) < new Date();

  return (
    <div className="card" style={{ cursor: "pointer", opacity: isPast ? 0.75 : 1 }}
      onClick={() => onClick(ev.id)}>
      <div style={{ display: "flex", justifyContent: "space-between",
        gap: 8, marginBottom: 4 }}>
        <h3 style={{ margin: 0, flex: 1, fontSize: 15 }}>{ev.title}</h3>
        {ev.is_pending && <span className="badge badge-pending" style={{ fontSize: 11 }}>На модерации</span>}
        {isPast && !ev.is_pending && (
          <span className="badge" style={{ background: "var(--text-dim)", fontSize: 11 }}>Прошло</span>
        )}
      </div>
      <div className="hint" style={{ fontSize: 13 }}>{fmt(ev.event_date)}</div>
      {ev.location && <div className="hint" style={{ fontSize: 12 }}>📍 {ev.location}</div>}
      <div style={{ display: "flex", gap: 12, fontSize: 12,
        color: "var(--text-dim)", marginTop: 6 }}>
        <span>🏃 {ev.going_count}</span>
        {ev.distance_km && <span>{ev.distance_km} км</span>}
        <span>+{ev.xp_bonus} XP</span>
        {ev.user_status === "going" && (
          <span style={{ color: "var(--accent)" }}>✓ Участвую</span>
        )}
      </div>
    </div>
  );
}


// ─── Форма создания ──────────────────────────────────────────

function CreateForm({ onSuccess }) {
  const qc = useQueryClient();
  const [useTemplate, setUseTemplate] = useState(null);
  const [form, setForm] = useState({
    title: "", description: "", location: "",
    event_date: defaultDatetime(), distance_km: "",
    xp_bonus: "100", xp_multiplier: "1.5",
  });
  const [err, setErr] = useState("");
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }));

  const templatesQ = useQuery({
    queryKey: ["event-templates"],
    queryFn: getEventTemplates,
    staleTime: 300_000,
  });

  const mut = useMutation({
    mutationFn: createEvent,
    onSuccess: d => {
      if (d.ok) {
        qc.invalidateQueries({ queryKey: ["events"] });
        onSuccess();
      } else {
        setErr(d.reason);
      }
    },
  });

  const applyTemplate = tpl => {
    setUseTemplate(tpl.id);
    setForm(f => ({
      ...f,
      title:         tpl.name,
      description:   tpl.description || "",
      location:      tpl.location    || "",
      distance_km:   tpl.distance_km ? String(tpl.distance_km) : "",
      xp_bonus:      String(tpl.xp_bonus),
      xp_multiplier: String(tpl.xp_multiplier),
    }));
  };

  const handleSubmit = () => {
    if (!form.title.trim()) { setErr("Введи название"); return; }
    if (!form.event_date)   { setErr("Введи дату");     return; }
    setErr("");
    mut.mutate({
      title:         form.title.trim(),
      description:   form.description.trim() || null,
      location:      form.location.trim()    || null,
      event_date:    parseDatetimeInput(form.event_date),
      distance_km:   form.distance_km ? +form.distance_km : null,
      xp_bonus:      +form.xp_bonus    || 100,
      xp_multiplier: +form.xp_multiplier || 1.5,
      template_id:   typeof useTemplate === "number" ? useTemplate : null,
    });
  };

  return (
    <div>
      <button className="btn btn-secondary"
        style={{ width: "auto", padding: "7px 14px", marginBottom: 16, fontSize: 13 }}
        onClick={onSuccess}>← Назад</button>

      {/* Шаг 1: выбор шаблона */}
      {useTemplate === null && (
        <div className="card">
          <h2 style={{ marginBottom: 4 }}>Новое мероприятие</h2>
          <div className="hint" style={{ marginBottom: 16, fontSize: 13 }}>
            Выбери шаблон или создай с нуля
          </div>

          {templatesQ.isLoading && <Loader />}
          {templatesQ.data?.length > 0 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 500, textTransform: "uppercase",
                letterSpacing: "0.04em", color: "var(--text-muted)", marginBottom: 8 }}>
                Шаблоны
              </div>
              {templatesQ.data.map(tpl => (
                <div key={tpl.id} style={{
                  padding: "10px 12px", borderRadius: 8, border: "1px solid var(--border)",
                  marginBottom: 6, cursor: "pointer", background: "var(--bg-input)",
                }} onClick={() => applyTemplate(tpl)}>
                  <div style={{ fontWeight: 500, fontSize: 14 }}>
                    {tpl.is_external ? "🌍" : "🏃"} {tpl.name}
                  </div>
                  <div className="hint" style={{ fontSize: 12, marginTop: 2 }}>
                    {[tpl.location, tpl.distance_km && `${tpl.distance_km} км`]
                      .filter(Boolean).join(" · ")}
                  </div>
                </div>
              ))}
              <div style={{ margin: "4px 0 8px", textAlign: "center",
                fontSize: 13, color: "var(--text-dim)" }}>или</div>
            </>
          )}
          <button className="btn btn-secondary" onClick={() => setUseTemplate(false)}>
            ✏️ Создать без шаблона
          </button>
        </div>
      )}

      {/* Шаг 2: форма */}
      {useTemplate !== null && (
        <div className="card">
          {typeof useTemplate === "number" && (
            <div style={{ fontSize: 12, color: "var(--accent)", marginBottom: 12 }}>
              📋 Шаблон применён ·{" "}
              <span style={{ cursor: "pointer", textDecoration: "underline" }}
                onClick={() => setUseTemplate(null)}>изменить</span>
            </div>
          )}

          <div className="form-group">
            <label>Название *</label>
            <input value={form.title} onChange={set("title")} placeholder="Long Run 10 км" />
          </div>
          <div className="form-group">
            <label>Дата и время *</label>
            <input type="datetime-local" value={form.event_date} onChange={set("event_date")} />
          </div>
          <div className="form-group">
            <label>Место</label>
            <input value={form.location} onChange={set("location")} placeholder="Парк..." />
          </div>
          <div className="form-group">
            <label>Дистанция (км)</label>
            <input value={form.distance_km} onChange={set("distance_km")}
              type="number" step="0.1" placeholder="10" />
          </div>
          <div className="form-group">
            <label>Описание</label>
            <textarea value={form.description} onChange={set("description")}
              placeholder="Подробности..." rows={3} />
          </div>

          {err && <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 10 }}>{err}</div>}

          <div className="hint" style={{ fontSize: 12, marginBottom: 12 }}>
            После отправки модератор получит уведомление в боте и опубликует анонс в группу
          </div>
          <button className="btn btn-primary" disabled={mut.isPending} onClick={handleSubmit}>
            {mut.isPending ? "Отправка..." : "Отправить на модерацию"}
          </button>
        </div>
      )}
    </div>
  );
}


// ─── Список ──────────────────────────────────────────────────

function EventList({ queryKey, queryFn, emptyText }) {
  const [selected, setSelected] = useState(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: [queryKey],
    queryFn,
    staleTime: 30_000,
  });

  if (selected !== null) return (
    <EventDetail id={selected} onBack={() => setSelected(null)} />
  );
  if (isLoading) return <Loader />;
  if (isError)   return <ErrorMessage error={error} />;
  if (!data?.length) return (
    <div className="empty-state">
      <div className="empty-icon">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="1.2">
          <rect x="3" y="4" width="18" height="18" rx="2"/>
          <path d="M16 2v4M8 2v4M3 10h18"/>
        </svg>
      </div>
      <div className="empty-title">{emptyText}</div>
    </div>
  );

  return (
    <div>
      {data.map(ev => (
        <EventCard key={ev.id} ev={ev} onClick={setSelected} />
      ))}
    </div>
  );
}


// ─── Главный компонент ───────────────────────────────────────

export default function Events() {
  const [tab, setTab]       = useState("upcoming");
  const [create, setCreate] = useState(false);

  if (create) return <CreateForm onSuccess={() => setCreate(false)} />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 18 }}>
        <h1 style={{ margin: 0 }}>Мероприятия</h1>
        <button className="btn btn-secondary"
          style={{ width: "auto", padding: "7px 14px", fontSize: 13 }}
          onClick={() => setCreate(true)}>
          + Создать
        </button>
      </div>

      <div className="tabs">
        <button className={"tab" + (tab === "upcoming" ? " active" : "")}
          onClick={() => setTab("upcoming")}>Ближайшие</button>
        <button className={"tab" + (tab === "archive" ? " active" : "")}
          onClick={() => setTab("archive")}>Архив</button>
      </div>

      {tab === "upcoming" && (
        <EventList
          queryKey="events"
          queryFn={getEvents}
          emptyText="Нет ближайших мероприятий"
        />
      )}
      {tab === "archive" && (
        <EventList
          queryKey="events-archive"
          queryFn={getArchiveEvents}
          emptyText="Архив пуст"
        />
      )}
    </div>
  );
}