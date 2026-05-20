export default function ErrorMessage({ error }) {
  const msg =
    error?.response?.data?.detail ||
    error?.message ||
    "Что-то пошло не так";

  return (
    <div className="empty-state">
      <div className="empty-icon">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 8v4M12 16h.01"/>
        </svg>
      </div>
      <div className="empty-title">Ошибка</div>
      <div style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 4 }}>{msg}</div>
    </div>
  );
}