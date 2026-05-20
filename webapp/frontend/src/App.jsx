import { Routes, Route, Navigate } from "react-router-dom";
import BottomNav from "./components/BottomNav";
import Profile from "./pages/Profile";
import Challenges from "./pages/Challenges";
import Events from "./pages/Events";
import Reports from "./pages/Reports";
import Tournaments from "./pages/Tournaments";
import "./App.css";

export default function App() {
  return (
    <div className="app">
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/profile" replace />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/challenges" element={<Challenges />} />
          <Route path="/events" element={<Events />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/tournaments" element={<Tournaments />} />
        </Routes>
      </main>
      <BottomNav />
    </div>
  );
}