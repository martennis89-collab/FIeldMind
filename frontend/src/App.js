import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, ProtectedRoute } from "@/lib/auth";
import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Doctors from "@/pages/Doctors";
import DoctorProfile from "@/pages/DoctorProfile";
import LogVisit from "@/pages/LogVisit";
import Tasks from "@/pages/Tasks";
import Search from "@/pages/Search";
import Reports from "@/pages/Reports";
import Admin from "@/pages/Admin";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster position="top-right" richColors />
        <Routes>
          <Route path="/login" element={<Login />} />

          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout><Dashboard /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/doctors"
            element={
              <ProtectedRoute>
                <Layout><Doctors /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/doctors/:id"
            element={
              <ProtectedRoute>
                <Layout><DoctorProfile /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/log-visit"
            element={
              <ProtectedRoute>
                <Layout><LogVisit /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/tasks"
            element={
              <ProtectedRoute>
                <Layout><Tasks /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/search"
            element={
              <ProtectedRoute>
                <Layout><Search /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/reports"
            element={
              <ProtectedRoute>
                <Layout><Reports /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <ProtectedRoute roles={["Admin"]}>
                <Layout><Admin /></Layout>
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
