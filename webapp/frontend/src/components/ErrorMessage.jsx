export default function ErrorMessage({ error }) {
  const status  = error?.response?.status;
  const detail  = error?.response?.data?.detail || error?.message || "";
  const tg      = window.Telegram?.WebApp;
  const hasData = !!(tg?.initData?.length > 0);

  if (status === 401 || status === 422) {
    if (!tg || !hasData) {
      return (
        <div className="empty-state" style={{ padding: "40px 24px", textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🔐</div>
          <div className="empty-title" style={{ marginBottom: 8 }}>Ошибка авторизации</div>
          <div style={{ fontSize: 14, color: "var(--text-dim)", lineHeight: 1.6 }}>
            Закрой приложение и открой снова через кнопку бота.<br/>
            <span style={{ fontSize: 12, opacity: 0.5 }}>initData не получен от Telegram</span>
          </div>
        </div>
      );
    }
    return (
      <div className="empty-state" style={{ padding: "40px 24px", textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>🔐</div>
        <div className="empty-title" style={{ marginBottom: 8 }}>Ошибка авторизации</div>
        <div style={{ fontSize: 14, color: "var(--text-dim)", lineHeight: 1.6 }}>
          Закрой приложение полностью и открой снова.<br/>
          {detail && <span style={{ fontSize: 12, opacity: 0.5 }}>{detail}</span>}
        </div>
      </div>
    );
  }

  if (status === 404) {
    return (
      <div className="empty-state" style={{ padding: "40px 24px", textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>🏃</div>
        <div className="empty-title" style={{ marginBottom: 8 }}>Сначала зарегистрируйся</div>
        <div style={{ fontSize: 14, color: "var(--text-dim)", lineHeight: 1.6 }}>
          Напиши <b>/start</b> боту и пройди регистрацию.
        </div>
      </div>
    );
  }

  return (
    <div className="empty-state" style={{ padding: "40px 24px", textAlign: "center" }}>
      <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
      <div className="empty-title" style={{ marginBottom: 8 }}>Ошибка {status || ""}</div>
      <div style={{ fontSize: 14, color: "var(--text-dim)" }}>{detail || "Что-то пошло не так."}</div>
    </div>
  );
}
