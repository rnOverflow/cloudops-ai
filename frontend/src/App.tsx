import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import AIOps from "./pages/AIOps";
import Audit from "./pages/Audit";
import IncidentDetail from "./pages/IncidentDetail";
import Incidents from "./pages/Incidents";
import Infrastructure from "./pages/Infrastructure";
import Kubernetes from "./pages/Kubernetes";
import Login from "./pages/Login";
import Logs from "./pages/Logs";
import Metrics from "./pages/Metrics";
import Overview from "./pages/Overview";
import Runbooks from "./pages/Runbooks";
import ServiceDetail from "./pages/ServiceDetail";
import Services from "./pages/Services";
import SettingsPage from "./pages/Settings";
import Simulator from "./pages/Simulator";
import SLOPage from "./pages/SLO";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="services" element={<Services />} />
        <Route path="services/:name" element={<ServiceDetail />} />
        <Route path="incidents" element={<Incidents />} />
        <Route path="incidents/:key" element={<IncidentDetail />} />
        <Route path="ai" element={<AIOps />} />
        <Route path="simulator" element={<Simulator />} />
        <Route path="infrastructure" element={<Infrastructure />} />
        <Route path="kubernetes" element={<Kubernetes />} />
        <Route path="slo" element={<SLOPage />} />
        <Route path="logs" element={<Logs />} />
        <Route path="metrics" element={<Metrics />} />
        <Route path="runbooks" element={<Runbooks />} />
        <Route path="runbooks/:slug" element={<Runbooks />} />
        <Route path="audit" element={<Audit />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
