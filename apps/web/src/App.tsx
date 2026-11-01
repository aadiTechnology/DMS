import {
  SYSTEM_TEMPLATE, TemplateProvider, readCachedTemplate, resolveAppearance, writeCachedTemplate, type EffectiveAnswer,
} from "@aaditech/ui-engine";
import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { APPEARANCE_KEY, PreviewBanner, PreviewContext, type Preview } from "./appearance";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, getSession, signedOut } from "./api";
import Layout from "./Layout";
import Account from "./pages/Account";
import Appearance from "./pages/Appearance";
import DesignCatalogue from "./pages/DesignCatalogue";
import Approvals from "./pages/Approvals";
import Categories from "./pages/Categories";
import DocumentDetail from "./pages/DocumentDetail";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import Login from "./pages/Login";
import { AcceptInvite, Register, ResetPassword, SsoCallback } from "./pages/PublicPages";
import Activity from "./pages/Activity";
import Organization from "./pages/Organization";
import People from "./pages/People";
import Retention from "./pages/Retention";
import Shared from "./pages/Shared";
import Upload from "./pages/Upload";

const PermissionContext = createContext<Set<string>>(new Set());
export const usePermissions = () => useContext(PermissionContext);
export const useCan = (code: string) => usePermissions().has(code);

const storage = typeof localStorage === "undefined" ? undefined : localStorage;

function Authenticated() {
  const email = getSession()?.email ?? "";
  const permissions = useQuery({ queryKey: ["permissions"], queryFn: () => api<{ permissions: string[] }>("/me/permissions") });
  const preference = useQuery({
    queryKey: APPEARANCE_KEY,
    queryFn: () => api<{ effective: EffectiveAnswer }>("/me/ui-preferences"),
  });
  const [preview, setPreview] = useState<Preview | null>(null);
  const previewState = useMemo(
    () => ({
      preview,
      start: (id: string, template: unknown) => {
        setPreview({ id, template: template as Preview["template"] });
        return null;
      },
      stop: () => setPreview(null),
    }),
    [preview],
  );
  const cached = useMemo(() => readCachedTemplate(storage, email), [email]);
  const appearance = preference.data
    ? resolveAppearance(preference.data.effective, cached)
    : { template: cached ?? SYSTEM_TEMPLATE, source: cached ? ("cache" as const) : ("fallback" as const) };

  useEffect(() => {
    if (preference.data && appearance.source !== "cache" && appearance.source !== "fallback") {
      writeCachedTemplate(storage, email, appearance.template);
    }
  }, [preference.data, appearance.source, appearance.template, email]);

  return (
    <PreviewContext.Provider value={previewState}>
    <TemplateProvider template={preview?.template ?? appearance.template}>
      <PreviewBanner />
      {permissions.isLoading ? null : (
        <PermissionContext.Provider value={new Set(permissions.data?.permissions ?? [])}>
          <Layout>
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/documents" element={<Documents />} />
              <Route path="/documents/:id" element={<DocumentDetail />} />
              <Route path="/upload" element={<Upload />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/shared" element={<Shared />} />
              <Route path="/organization" element={<Organization />} />
              <Route path="/categories" element={<Categories />} />
              <Route path="/people" element={<People />} />
              <Route path="/activity" element={<Activity />} />
              <Route path="/retention" element={<Retention />} />
              <Route path="/appearance" element={<Appearance />} />
              <Route path="/platform/designs" element={<DesignCatalogue />} />
              <Route path="/account" element={<Account />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </Layout>
        </PermissionContext.Provider>
      )}
    </TemplateProvider>
    </PreviewContext.Provider>
  );
}

export default function App() {
  const [signedIn, setSignedIn] = useState(() => getSession() !== null);
  useEffect(() => {
    const out = () => setSignedIn(false);
    signedOut.addEventListener("out", out);
    return () => signedOut.removeEventListener("out", out);
  }, []);
  // These pages work without a session (and for someone signed in as a different person).
  const publicPage = ["/accept-invite", "/reset-password", "/register", "/sso-callback"].includes(useLocation().pathname);
  if (!signedIn || publicPage) {
    return (
      <TemplateProvider template={SYSTEM_TEMPLATE}>
        <Routes>
          <Route path="/accept-invite" element={<AcceptInvite />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/register" element={<Register />} />
          <Route path="/sso-callback" element={<SsoCallback onSignedIn={() => setSignedIn(true)} />} />
          <Route path="*" element={<Login onSignedIn={() => setSignedIn(true)} />} />
        </Routes>
      </TemplateProvider>
    );
  }
  return <Authenticated />;
}
