import { describe, expect, it } from "vitest";
import { authorizeUrl, emailFromIdToken, readSsoReturn } from "./sso";

const stored = JSON.stringify({ provider: "google", state: "s1", nonce: "n1" });

describe("sso helpers", () => {
  it("asks the provider for an ID token and sends back to this app", () => {
    const u = new URL(authorizeUrl("microsoft", "cid", "https://dms.example", "s", "n"));
    expect(u.hostname).toBe("login.microsoftonline.com");
    expect(u.searchParams.get("response_type")).toBe("id_token");
    expect(u.searchParams.get("redirect_uri")).toBe("https://dms.example/sso-callback");
    expect(u.searchParams.get("response_mode")).toBe("fragment");
  });
  it("accepts only an answer to a request this browser made", () => {
    expect(readSsoReturn("#id_token=abc&state=s1", stored)).toEqual({ provider: "google", idToken: "abc", nonce: "n1" });
    expect(readSsoReturn("#id_token=abc&state=other", stored)).toBeNull();
    expect(readSsoReturn("#id_token=abc&state=s1", null)).toBeNull();
    expect(readSsoReturn("#state=s1", stored)).toBeNull();
  });
  it("reads the email for display", () => {
    const payload = btoa(JSON.stringify({ email: "a@b.in" })).replace(/=/g, "");
    expect(emailFromIdToken(`h.${payload}.s`)).toBe("a@b.in");
    expect(emailFromIdToken("garbage")).toBe("");
  });
});
