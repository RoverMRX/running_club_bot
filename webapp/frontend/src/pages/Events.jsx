import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getEvents, getPendingEvents, createEvent, joinEvent, leaveEvent, approveEvent, rejectEvent } from "../api";
import Loader from "../components/Loader";
import ErrorMessage from "../components/ErrorMessage";

function fmt(dt) {
  if (!dt) return "—";
  return new Date(dt).toLocaleString("ru", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function EventCard({ ev, isAdmin }) {
  const qc = useQueryClient();
  const inv = () => { qc.invalidateQueries(["events"]); qc.invalidateQueries(["events-pending"]); };
  const joinMut    = useMutation({ mutationFn: () => joinEvent(ev.id),    onSuccess: inv });
  const leaveMut   = useMutation({ mutationFn: () => leaveEvent(ev.id),   onSuccess: inv });
  const approveMut = useMutation({ mutationFn: () => approveEvent(ev.id), onSuccess: inv });
  const rejectMut  = useMutation({ mutationFn: () => rejectEvent(ev.id),  onSuccess: inv });

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
        <h3 style={{ flex: 1 }}>{ev.title}</h3>
        {ev.is_pending && <span className="badge badge-pending">Модерация</span>}
      </div>
      <div className="hint" style={{ fontSize: 13 }}>{fmt(ev.event_date)}</div>
      {ev.location    && <div className="hint" style={{ fontSize: 13 }}>{ev.location}</div>}
      {ev.distance_km && <div className="hint" style={{ fontSize: 13 }}>{ev.distance_km} км</div>}
      {ev.description && <div style={{ marginTop: 8, fontSize: 13 }}>{ev.description}</div>}

      <div className="divider" />

      <div style={{ display: "flex", gap: 20, fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>
        <span>{ev.going_count} идут</span>
        <span>{ev.not_going_count} не идут</span>
        <span>+{ev.xp_bonus} XP</span>
      </div>

      {!ev.is_pending && (
        ev.user_status === "going"
          ? <button className="btn btn-secondary" disabled={leaveMut.isPending} onClick={() => leaveMut.mutate()}>
              Участвую · Отменить
            </button>
          : <button className="btn btn-primary" disabled={joinMut.isPending} onClick={() => joinMut.mutate()}>
              Участвовать
            </button>
      )}

      {ev.is_pending && isAdmin && (
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-success" disabled={approveMut.isPending} onClick={() => approveMut.mutate()}>Опубликовать</button>
          <button className="btn btn-danger"  disabled={rejectMut.isPending}  onClick={() => rejectMut.mutate()}>Отклонить</button>
        </div>
      )}
    </div>
  );
}

function CreateForm({ onSuccess }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ title: "", description: "", location: "", event_date: "", distance_km: "" });
  const [err, setErr] = useState("");
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }));

  const mut = useMutation({
    mutationFn: createEvent,
    onSuccess: d => d.ok ? (qc.invalidateQueries(["events"]), onSuccess()) : setErr(d.reason),
  });

  return (
    <div>
      <button className="btn btn-secondary" style={{ width: "auto", padding: "7px 14px", marginBottom: 16, fontSize: 13 }} onClick={onSuccess}>
        ← Назад
      </button>
      <div className="card">
        <h2 style={{ marginBottom: 4 }}>Новое мероприятие</h2>
        <div className="hint" style={{ marginBottom: 16, fontSize: 13 }}>Уйдёт на модерацию администратору</div>

        <div className="form-group"><label>Название *</label>
          <input value={form.title} onChange={set("title")} placeholder="Long Run 10 км" /></div>
        <div className="form-group"><label>Дата и время * (ДД.ММ.ГГГГ ЧЧ:ММ)</label>
          <input value={form.event_date} onChange={set("event_date")} placeholder="22.06.2026 09:00" /></div>
        <div className="form-group"><label>Место</label>
          <input value={form.location} onChange={set("location")} placeholder="Парк..." /></div>
        <div className="form-group"><label>Дистанция (км)</label>
          <input value={form.distance_km} onChange={set("distance_km")} type="number" placeholder="10" /></div>
        <div className="form-group"><label>Описание</label>
          <textarea value={form.description} onChange={set("description")} placeholder="Подробности..." /></div>

        {err && <div style={{ color: "var(--danger)", fontSize: 13, marginBottom: 10 }}>{err}</div>}
        <button className="btn btn-primary" disabled={mut.isPending} onClick={() => {
          if (!form.title.trim()) { setErr("Введи название"); return; }
          if (!form.event_date.trim()) { setErr("Введи дату"); return; }
          setErr("");
          mut.mutate({ ...form, distance_km: form.distance_km ? +form.distance_km : null, description: form.description || null, location: form.location || null });
        }}>
          {mut.isPending ? "Отправка..." : "Отправить на модерацию"}
        </button>
      </div>
    </div>
  );
}

export default function Events() {
  const [tab, setTab] = useState("upcoming");
  const [create, setCreate] = useState(false);

  const evQ = useQuery({ queryKey: ["events"],         queryFn: getEvents,        enabled: tab === "upcoming" });
  const pdQ = useQuery({ queryKey: ["events-pending"], queryFn: getPendingEvents, enabled: tab === "pending"  });

  if (create) return <CreateForm onSuccess={() => setCreate(false)} />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
        <h1 style={{ margin: 0 }}>Мероприятия</h1>
        <button className="btn btn-secondary" style={{ width: "auto", padding: "7px 14px", fontSize: 13 }} onClick={() => setCreate(true)}>
          + Создать
        </button>
      </div>
      <div className="tabs">
        <button className={"tab" + (tab === "upcoming" ? " active" : "")} onClick={() => setTab("upcoming")}>Ближайшие</button>
        <button className={"tab" + (tab === "pending"  ? " active" : "")} onClick={() => setTab("pending")}>Модерация</button>
      </div>

      {tab === "upcoming" && (
        evQ.isLoading ? <Loader /> : evQ.isError ? <ErrorMessage error={evQ.error} /> :
        !evQ.data?.length
          ? <div className="empty-state"><div className="empty-icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg></div><div className="empty-title">Нет ближайших мероприятий</div></div>
          : evQ.data.map(ev => <EventCard key={ev.id} ev={ev} isAdmin={false} />)
      )}

      {tab === "pending" && (
        pdQ.isLoading ? <Loader /> : pdQ.isError ? <ErrorMessage error={pdQ.error} /> :
        !pdQ.data?.length
          ? <div className="empty-state"><div className="empty-icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div><div className="empty-title">Нет мероприятий на модерации</div></div>
          : pdQ.data.map(ev => <EventCard key={ev.id} ev={ev} isAdmin={true} />)
      )}
    </div>
  );
}