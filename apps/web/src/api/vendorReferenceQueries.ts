import { useQuery } from "@tanstack/react-query";

import {
  fetchVendorReferenceIndexStatus,
  searchVendorReferenceIndex,
} from "./vendorReferenceClient";

const referenceIndexKey = ["vendor-reference-index"] as const;
const staleTime = 30_000;

export function useVendorReferenceIndexStatus() {
  return useQuery({
    queryKey: [...referenceIndexKey, "status"],
    queryFn: fetchVendorReferenceIndexStatus,
    staleTime,
  });
}

export function useVendorReferenceSearch(query: string | null) {
  return useQuery({
    queryKey: [...referenceIndexKey, "search", query],
    enabled: query !== null,
    queryFn: () => {
      if (query === null) {
        throw new Error("A merchant reference search query is required.");
      }
      return searchVendorReferenceIndex(query);
    },
    staleTime,
  });
}
