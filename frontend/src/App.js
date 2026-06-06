import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import "@/App.css";
import "@/mobile-fixes.css";
import BookingPage from "@/pages/BookingPage";
import ConfirmationPage from "@/pages/ConfirmationPage";
import CustomerPortal from "@/pages/CustomerPortal";
import AdminLogin from "@/pages/AdminLogin";
import AdminShell from "@/components/AdminShell";
import AdminAppointments from "@/pages/AdminAppointments";
import AdminCalendar from "@/pages/AdminCalendar";
import AdminAvailability from "@/pages/AdminAvailability";
import AdminBusiness from "@/pages/AdminBusiness";
import AdminTemplates from "@/pages/AdminTemplates";
import AdminUsers from "@/pages/AdminUsers";
import { DEFAULT_SLUG } from "@/lib/api";

function App() {
  return (
    <div className="App dark min-h-screen bg-background text-foreground">
      <Toaster richColors position="top-right" />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to={`/book/${DEFAULT_SLUG}`} replace />} />
          <Route path="/book/:slug" element={<BookingPage />} />
          <Route path="/book/:slug/confirm/:code" element={<ConfirmationPage />} />
          <Route path="/portal/:token" element={<CustomerPortal />} />
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/admin" element={<AdminShell />}>
            <Route index element={<Navigate to="/admin/appointments" replace />} />
            <Route path="appointments" element={<AdminAppointments />} />
            <Route path="calendar" element={<AdminCalendar />} />
            <Route path="availability" element={<AdminAvailability />} />
            <Route path="business" element={<AdminBusiness />} />
            <Route path="templates" element={<AdminTemplates />} />
            <Route path="users" element={<AdminUsers />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
