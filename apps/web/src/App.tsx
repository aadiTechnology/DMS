import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, getSession, signedOut } from "./api";
import Layout from "./Layout";
import Account from "./pages/Account";
import Approvals from "./pages/Approvals";
import DocumentDetail from "./pages/DocumentDetail";
import Documents from "./pages/Documents";
import Login from "./pages/Login";
import Organization from "./pages/Organization";
import Shared from "./pages/Shared";
import Upload from "./pages/Upload";

const PermissionContext = createContext<Set<string>>(new Set());
export const usePermissions = () => useContext(PermissionContext);
export const useCan = (code: string) => usePermissions().has(code);

function Authenticated() {
  const { data, isLoading } = useQuery({
    queryKey: ["permissions"],
    queryFn: () => api<{ permissions: string[] }>("/me/permissions"),
  });
  if (isLoading) return null;
  return (
    <PermissionContext.Provider value={new Set(data?.permissions ?? [])}>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/documents" replace />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:id" element={<DocumentDetail />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/shared" element={<Shared />} />
          <Route path="/organization" element={<Organization />} />
          <Route path="/account" element={<Account />} />
          <Route path="*" element={<Navigate to="/documents" replace />} />
        </Routes>
      </Layout>
    </PermissionContext.Provider>
  );
}

export default function App() {
  const [signedIn, setSignedIn] = useState(() => getSession() !== null);
  useEffect(() => {
    const out = () => setSignedIn(false);
    signedOut.addEventListener("out", out);
    return () => signedOut.removeEventListener("out", out);
  }, []);
  if (!signedIn) return <Login onSignedIn={() => setSignedIn(true)} />;
  return <Authenticated />;
}
