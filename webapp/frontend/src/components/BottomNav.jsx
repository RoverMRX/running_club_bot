import { NavLink, useLocation } from "react-router-dom";
import "./BottomNav.css";

const icons = {
  profile: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
    </svg>
  ),
  challenges: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/>
    </svg>
  ),
  events: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>
    </svg>
  ),
  reports: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 20H6a2 2 0 01-2-2V6a2 2 0 012-2h7l5 5v9a2 2 0 01-2 2z"/><path d="M14 4v5h5M9 13h6M9 17h4"/>
    </svg>
  ),
  tournaments: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9H4a2 2 0 000 4h2"/><path d="M18 9h2a2 2 0 010 4h-2"/><path d="M6 9V5h12v4"/><path d="M6 13c0 3.3 2.7 6 6 6s6-2.7 6-6"/><path d="M12 19v2M9 21h6"/>
    </svg>
  ),
};

const NAV_ITEMS = [
  { to: "/profile",     icon: icons.profile,     label: "Профиль"   },
  { to: "/challenges",  icon: icons.challenges,  label: "Челленджи" },
  { to: "/events",      icon: icons.events,      label: "События"   },
  { to: "/reports",     icon: icons.reports,     label: "Отчёты"    },
  { to: "/tournaments", icon: icons.tournaments, label: "Турниры"   },
];

export default function BottomNav() {
  const { pathname } = useLocation();

  return (
    <nav className="bottom-nav">
      {NAV_ITEMS.map(({ to, icon, label }) => {
        // Профиль подсвечиваем и на /, и на /profile
        const isActive =
          to === "/profile"
            ? pathname === "/" || pathname === "/profile"
            : pathname.startsWith(to);
        return (
          <NavLink
            key={to}
            to={to}
            className={"nav-item" + (isActive ? " active" : "")}
          >
            <span className="nav-icon">{icon}</span>
            <span className="nav-label">{label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
