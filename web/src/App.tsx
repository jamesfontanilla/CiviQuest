import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { Login } from "./pages/auth/Login";
import { Signup } from "./pages/auth/Signup";
import { ForgotPassword } from "./pages/auth/ForgotPassword";
import { OTPVerification } from "./pages/auth/OTPVerification";
import { Home } from "./pages/Home";
import { ModuleList } from "./pages/content/ModuleList";
import { TopicList } from "./pages/content/TopicList";
import { SubtopicList } from "./pages/content/SubtopicList";
import { LessonReader } from "./pages/content/LessonReader";
import { QuizPlayer } from "./pages/quiz/QuizPlayer";
import { MockExamPlayer } from "./pages/mock-exam/MockExamPlayer";
import { Leaderboard } from "./pages/Leaderboard";
import { Mastery } from "./pages/Mastery";
import { Goals } from "./pages/Goals";
import { Tournaments } from "./pages/Tournaments";
import { Profile } from "./pages/Profile";
import { Analytics } from "./pages/Analytics";
import { AdminDashboard } from "./pages/AdminDashboard";
import { GlassNavbar } from "./components/GlassNavbar";
import { AmbientBackground } from "./components/AmbientBackground";
import { AuthGuard } from "./components/AuthGuard";
import { ToastProvider } from "./context/ToastContext";
import { Tutor } from "./pages/Tutor";
import { StudyPlan } from "./pages/StudyPlan";
import { Readiness } from "./pages/Readiness";
import { Focus } from "./pages/Focus";

function AppContent() {
  const location = useLocation();

  return (
    <>
      <AmbientBackground />
      <GlassNavbar />
      <AnimatePresence mode="wait">
        <Routes location={location} key={location.pathname}>
          {/* Public auth routes */}
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/verify-otp" element={<OTPVerification />} />

          {/* Protected routes */}
          <Route
            path="/modules"
            element={
              <AuthGuard>
                <ModuleList />
              </AuthGuard>
            }
          />
          <Route
            path="/modules/:moduleId/topics"
            element={
              <AuthGuard>
                <TopicList />
              </AuthGuard>
            }
          />
          <Route
            path="/topics/:topicId/subtopics"
            element={
              <AuthGuard>
                <SubtopicList />
              </AuthGuard>
            }
          />
          <Route
            path="/subtopics/:subtopicId/lesson"
            element={
              <AuthGuard>
                <LessonReader />
              </AuthGuard>
            }
          />
          <Route
            path="/quiz/:scope/:scopeId"
            element={
              <AuthGuard>
                <QuizPlayer />
              </AuthGuard>
            }
          />
          <Route
            path="/mock-exam"
            element={
              <AuthGuard>
                <MockExamPlayer />
              </AuthGuard>
            }
          />
          <Route
            path="/leaderboard"
            element={
              <AuthGuard>
                <Leaderboard />
              </AuthGuard>
            }
          />
          <Route
            path="/mastery"
            element={
              <AuthGuard>
                <Mastery />
              </AuthGuard>
            }
          />
          <Route
            path="/analytics"
            element={
              <AuthGuard>
                <Analytics />
              </AuthGuard>
            }
          />
          <Route
            path="/goals"
            element={
              <AuthGuard>
                <Goals />
              </AuthGuard>
            }
          />
          <Route
            path="/tournaments"
            element={
              <AuthGuard>
                <Tournaments />
              </AuthGuard>
            }
          />
          <Route
            path="/profile"
            element={
              <AuthGuard>
                <Profile />
              </AuthGuard>
            }
          />
          <Route
            path="/admin"
            element={
              <AuthGuard>
                <AdminDashboard />
              </AuthGuard>
            }
          />
          <Route
            path="/tutor"
            element={
              <AuthGuard>
                <Tutor />
              </AuthGuard>
            }
          />
          <Route
            path="/study-plan"
            element={
              <AuthGuard>
                <StudyPlan />
              </AuthGuard>
            }
          />
          <Route
            path="/readiness"
            element={
              <AuthGuard>
                <Readiness />
              </AuthGuard>
            }
          />
          <Route
            path="/focus"
            element={
              <AuthGuard>
                <Focus />
              </AuthGuard>
            }
          />

          {/* Homepage */}
          <Route path="/" element={<Home />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AnimatePresence>
    </>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AppContent />
      </ToastProvider>
    </BrowserRouter>
  );
}
