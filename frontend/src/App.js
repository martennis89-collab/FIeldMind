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
import Intervention from "@/pages/Intervention";
import MarketIntelligence from "@/pages/MarketIntelligence";
import TeamPerformance from "@/pages/TeamPerformance";
import Itero from "@/pages/Itero";
import Invisalign from "@/pages/Invisalign";
import Admin from "@/pages/Admin";
import Expenses from "@/pages/Expenses";
import LogExpense from "@/pages/LogExpense";
import ImportDoctors from "@/pages/ImportDoctors";
import AddDoctor from "@/pages/AddDoctor";
import Meetings from "@/pages/Meetings";
import BookMeeting from "@/pages/BookMeeting";
import IteroPipeline from "@/pages/IteroPipeline";
import IteroDemos from "@/pages/IteroDemos";
import Account from "@/pages/Account";
import Reimbursement from "@/pages/Reimbursement";
import CalendarPage from "@/pages/Calendar";

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
            path="/meetings"
            element={
              <ProtectedRoute>
                <Layout><Meetings /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/meetings/book"
            element={
              <ProtectedRoute roles={["TM", "SeniorTM"]}>
                <Layout><BookMeeting /></Layout>
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
            path="/reimbursement"
            element={
              <ProtectedRoute roles={["TM", "SeniorTM", "Admin", "Owner"]}>
                <Layout><Reimbursement /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/calendar"
            element={
              <ProtectedRoute>
                <Layout><CalendarPage /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/intervention"
            element={
              <ProtectedRoute roles={["Manager", "SeniorTM", "Admin", "Owner"]}>
                <Layout><Intervention /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/market-intelligence"
            element={
              <ProtectedRoute roles={["Manager", "SeniorTM", "Admin", "Owner"]}>
                <Layout><MarketIntelligence /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/team-performance"
            element={
              <ProtectedRoute roles={["Manager", "SeniorTM", "Admin", "Owner"]}>
                <Layout><TeamPerformance /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/itero"
            element={
              <ProtectedRoute>
                <Layout><Itero /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/itero/pipeline"
            element={
              <ProtectedRoute>
                <Layout><IteroPipeline /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/itero/demos"
            element={
              <ProtectedRoute>
                <Layout><IteroDemos /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/invisalign"
            element={
              <ProtectedRoute>
                <Layout><Invisalign /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <ProtectedRoute roles={["Admin", "Owner"]}>
                <Layout><Admin /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/expenses"
            element={
              <ProtectedRoute>
                <Layout><Expenses /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/expenses/log"
            element={
              <ProtectedRoute roles={["TM", "SeniorTM"]}>
                <Layout><LogExpense /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/doctors/import"
            element={
              <ProtectedRoute roles={["TM", "SeniorTM", "Admin"]}>
                <Layout><ImportDoctors /></Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/doctors/add"
            element={
              <ProtectedRoute roles={["TM", "SeniorTM", "Admin"]}>
                <Layout><AddDoctor /></Layout>
              </ProtectedRoute>
            }
          />

          <Route
            path="/account"
            element={
              <ProtectedRoute>
                <Layout><Account /></Layout>
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
