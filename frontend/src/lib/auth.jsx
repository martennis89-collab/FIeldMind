import React, { createContext, useContext, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import api from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const raw = localStorage.getItem("fip_user");
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(false);

  // First time this account is seen (or timezone was never set): silently
  // adopt the browser's detected zone so "today"/"tomorrow" in voice notes
  // resolve against the user's own calendar day, wherever they are — no
  // setup required. They can still override it later in Account settings.
  const maybeAutoDetectTimezone = async (userData) => {
    if (userData?.timezone) return userData;
    try {
      const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (!detected) return userData;
      const { data: updated } = await api.put("/auth/timezone", { timezone: detected });
      setUser(updated);
      localStorage.setItem("fip_user", JSON.stringify(updated));
      return updated;
    } catch {
      return userData; // non-critical — falls back to UTC server-side
    }
  };

  const refresh = async () => {
    if (!localStorage.getItem("fip_token")) return;
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
      localStorage.setItem("fip_user", JSON.stringify(data));
      await maybeAutoDetectTimezone(data);
    } catch {
      logout();
    }
  };

  const login = async (email, password) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      localStorage.setItem("fip_token", data.token);
      localStorage.setItem("fip_user", JSON.stringify(data.user));
      setUser(data.user);
      const finalUser = await maybeAutoDetectTimezone(data.user);
      return finalUser;
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* ignore */
    }
    localStorage.removeItem("fip_token");
    localStorage.removeItem("fip_user");
    setUser(null);
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, logout, loading, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

export function ProtectedRoute({ children, roles }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return children;
}
