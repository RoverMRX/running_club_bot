export default function Loader({ text = "Загрузка..." }) {
  return (
    <div style={{ textAlign: "center", padding: "48px 0", color: "var(--text-dim)" }}>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" style={{ animation: "spin 1s linear infinite", marginBottom: 10 }}>
        <circle cx="12" cy="12" r="10" strokeOpacity="0.2"/>
        <path d="M12 2a10 10 0 0110 10" strokeLinecap="round"/>
      </svg>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      <div style={{ fontSize: 13 }}>{text}</div>
    </div>
  );
}