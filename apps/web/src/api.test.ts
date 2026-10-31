import { describe, expect, it } from "vitest";
import { ApiError, errorText } from "./api";

describe("errorText", () => {
  it("shows plain messages", () => {
    expect(errorText({ detail: "Permission denied" })).toBe("Permission denied");
  });
  it("shows field errors from the API", () => {
    expect(errorText({ detail: { fields: { ref: "is required", vendor: "too long" } } })).toBe("ref: is required; vendor: too long");
  });
  it("prefers a message over a code", () => {
    expect(errorText({ detail: { code: "stale", message: "Someone added a newer version" } })).toBe("Someone added a newer version");
  });
  it("lists the problems found in an uploaded design", () => {
    expect(errorText({ detail: { errors: ["theme.colors.primary: must match pattern", "name: invalid"] } })).toBe("theme.colors.primary: must match pattern; name: invalid");
  });
  it("lists validation problems", () => {
    expect(errorText({ detail: [{ msg: "field required" }] })).toBe("field required");
  });
  it("falls back for unknown shapes", () => {
    expect(errorText(undefined)).toBe("Something went wrong");
    expect(new ApiError(404, "document not found").message).toBe("document not found");
  });
});
