import { describe, expect, it } from "vitest";
import { DEFAULT_MAX_UPLOAD_BYTES, DOCUMENT_STATES, SECURITY_CLASSIFICATIONS } from "./index";

describe("domain constants (PRD 7.1, 8.2, STO-001)", () => {
  it("defines four classifications", () => {
    expect(SECURITY_CLASSIFICATIONS).toHaveLength(4);
  });
  it("defines the six workflow states", () => {
    expect(DOCUMENT_STATES).toContain("under_review");
    expect(DOCUMENT_STATES).toHaveLength(6);
  });
  it("defaults max upload to 100 MB", () => {
    expect(DEFAULT_MAX_UPLOAD_BYTES).toBe(104857600);
  });
});
