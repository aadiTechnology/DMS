import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export interface Category {
  id: string;
  name: string;
  path: string;
  depth: number;
  default_classification: string;
  status: string;
}

export interface OrgItem {
  id: string;
  name: string;
  code?: string | null;
  status: string;
  manager_membership_id?: string | null;
  parent_id?: string | null;
}

export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => api<Category[]>("/categories", { params: { status: "active" } }),
    staleTime: 60_000,
  });
}

export function useOrg(kind: "departments" | "branches" | "projects" | "designations") {
  return useQuery({ queryKey: ["org", kind], queryFn: () => api<OrgItem[]>(`/org/${kind}`), staleTime: 60_000 });
}

export function categoryName(categories: Category[] | undefined, id: string) {
  return categories?.find((c) => c.id === id)?.path ?? "";
}
