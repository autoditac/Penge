import { getJson } from "./client";
import { vendorReferenceIndexStatusSchema, vendorReferenceSearchSchema } from "./schemas";
import type { VendorReferenceIndexStatusResponse, VendorReferenceSearchResponse } from "./schemas";

export function fetchVendorReferenceIndexStatus(): Promise<VendorReferenceIndexStatusResponse> {
  return getJson("/vendors/reference-index/status", {}, vendorReferenceIndexStatusSchema);
}

export function searchVendorReferenceIndex(
  query: string,
  limit = 20,
): Promise<VendorReferenceSearchResponse> {
  return getJson(
    "/vendors/reference-index/search",
    { q: query, limit },
    vendorReferenceSearchSchema,
  );
}
