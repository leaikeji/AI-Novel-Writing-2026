import { describe, expect, it } from "vitest";

import {
  parseTtsCloudProfile,
  parseTtsCloudProfilesResource,
  parseTtsCloudProfileTestResponse,
  TtsCloudProfileContractError,
} from "./contracts";
import { cloudProfile, cloudProfiles, cloudTestResponse } from "./test-fixtures";


describe("TTS cloud profile wire contracts", () => {
  it("drops any accidental raw credential fields from responses", () => {
    const parsed = parseTtsCloudProfile({
      ...cloudProfile(),
      api_key: "secret-that-must-not-reach-the-ui",
      credential_ref: "vault/secret-record",
    });

    expect("api_key" in parsed).toBe(false);
    expect("credential_ref" in parsed).toBe(false);
    expect(JSON.stringify(parsed)).not.toContain("secret-that-must-not-reach-the-ui");
    expect(JSON.stringify(parsed)).not.toContain("vault/secret-record");
  });

  it("rejects a credential hint that is not masked", () => {
    expect(() => parseTtsCloudProfile(cloudProfile({
      api_key_masked: "sk-raw-secret",
    }))).toThrow(TtsCloudProfileContractError);
  });

  it("requires active_profile_id to identify the only active profile", () => {
    expect(() => parseTtsCloudProfilesResource(cloudProfiles({
      items: [cloudProfile({ lifecycle_state: "active" })],
      active_profile_id: null,
    }))).toThrow(TtsCloudProfileContractError);

    const active = cloudProfile({ lifecycle_state: "active" });
    expect(parseTtsCloudProfilesResource(cloudProfiles({
      items: [active],
      active_profile_id: active.id,
    })).active_profile_id).toBe(active.id);
  });

  it("validates test evidence without accepting non-audio content", () => {
    expect(parseTtsCloudProfileTestResponse(cloudTestResponse()).status).toBe("passed");
    expect(() => parseTtsCloudProfileTestResponse(cloudTestResponse({
      content_type: "text/html",
      audio_base64: "PGh0bWw+",
    }))).toThrow(TtsCloudProfileContractError);
  });
});
