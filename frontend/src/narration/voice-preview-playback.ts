import { APP_ID } from "../contracts";
import type { MediaAssetLink, VoicePreviewResource } from "./contracts";


const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;


export interface VoicePreviewHost {
  fetch(input: string, init?: RequestInit): Promise<Response>;
}


export interface VoicePreviewObjectUrlApi {
  createObjectURL(blob: Blob): string;
  revokeObjectURL(url: string): void;
}


export interface VoicePreviewPlaybackReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(
    initial: T | (() => T),
  ): [T, (next: T | ((current: T) => T)) => void];
  useRef<T>(initial: T): { current: T };
  useEffect(
    effect: () => void | (() => void),
    dependencies: readonly unknown[],
  ): void;
}


export interface VoicePreviewPlaybackProps {
  readonly preview: VoicePreviewResource | null;
  readonly className?: string;
  readonly onPlayed?: () => void;
}


type PlaybackState =
  | { readonly phase: "idle"; readonly objectUrl: null; readonly message: string }
  | { readonly phase: "loading"; readonly objectUrl: null; readonly message: string }
  | { readonly phase: "ready"; readonly objectUrl: string; readonly message: string }
  | { readonly phase: "error"; readonly objectUrl: null; readonly message: string };


export class VoicePreviewPlaybackError extends Error {}


function previewMediaPath(preview: VoicePreviewResource): string {
  if (preview.status !== "ready" || preview.asset === null) {
    throw new VoicePreviewPlaybackError("试听尚未就绪，不能加载音频。");
  }
  const { asset_id: assetId, content_path: contentPath } = preview.asset;
  if (!CANONICAL_UUID.test(preview.preview_id)) {
    throw new VoicePreviewPlaybackError("试听任务标识无效。");
  }
  if (!CANONICAL_UUID.test(assetId)) {
    throw new VoicePreviewPlaybackError("试听音频标识无效。");
  }
  const expectedPath = `/media-assets/${assetId}/content`;
  if (
    contentPath !== expectedPath
    || contentPath.includes("?")
    || contentPath.includes("#")
    || !contentPath.startsWith("/media-assets/")
  ) {
    throw new VoicePreviewPlaybackError("试听音频路径未通过范围校验。");
  }
  return `/${APP_ID}${contentPath}`;
}


function assertMediaResponse(
  response: Response,
  asset: MediaAssetLink,
  blob: Blob,
): void {
  if (blob.size <= 0 || blob.size !== asset.byte_size) {
    throw new VoicePreviewPlaybackError("试听音频大小与服务端声明不一致。");
  }
  const responseType = response.headers.get("Content-Type")?.split(";", 1)[0].trim() ?? "";
  if (responseType !== asset.mime_type || blob.type !== asset.mime_type) {
    throw new VoicePreviewPlaybackError("试听音频类型与服务端声明不一致。");
  }
  const contentLength = response.headers.get("Content-Length") ?? "";
  if (contentLength !== String(asset.byte_size)) {
    throw new VoicePreviewPlaybackError("试听音频长度头与服务端声明不一致。");
  }
}


export async function fetchVoicePreviewObjectUrl(
  preview: VoicePreviewResource,
  options: {
    readonly host?: VoicePreviewHost;
    readonly objectUrls?: VoicePreviewObjectUrlApi;
    readonly signal?: AbortSignal;
  } = {},
): Promise<string> {
  const asset = preview.asset;
  const path = previewMediaPath(preview);
  if (asset === null) throw new VoicePreviewPlaybackError("试听音频不存在。");
  const host = options.host ?? window.QwenPaw.host;
  const objectUrls = options.objectUrls ?? URL;
  const response = await host.fetch(path, {
    method: "GET",
    headers: {
      Accept: asset.mime_type,
      "X-Narration-Voice-Preview-Id": preview.preview_id,
    },
    signal: options.signal,
  });
  if (!response.ok) {
    throw new VoicePreviewPlaybackError(`试听音频加载失败（HTTP ${response.status}）。`);
  }
  const blob = await response.blob();
  assertMediaResponse(response, asset, blob);
  return objectUrls.createObjectURL(blob);
}


/** Play one already-validated temporary preview and release its object URL. */
export async function playReadyVoicePreview(
  preview: VoicePreviewResource,
  signal: AbortSignal,
): Promise<void> {
  const objectUrl = await fetchVoicePreviewObjectUrl(preview, { signal });
  if (signal.aborted) {
    URL.revokeObjectURL(objectUrl);
    throw new DOMException("Aborted", "AbortError");
  }
  const audio = new Audio(objectUrl);
  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    signal.removeEventListener("abort", onAbort);
    audio.removeEventListener("ended", cleanup);
    audio.removeEventListener("error", cleanup);
    URL.revokeObjectURL(objectUrl);
  };
  const onAbort = () => {
    audio.pause();
    audio.removeAttribute("src");
    cleanup();
  };
  signal.addEventListener("abort", onAbort, { once: true });
  audio.addEventListener("ended", cleanup, { once: true });
  audio.addEventListener("error", cleanup, { once: true });
  try {
    await audio.play();
  } catch (error) {
    cleanup();
    throw error;
  }
}


function playbackErrorMessage(reason: unknown): string {
  if (reason instanceof VoicePreviewPlaybackError) return reason.message;
  if (
    reason !== null
    && typeof reason === "object"
    && "name" in reason
    && (reason as { readonly name?: unknown }).name === "AbortError"
  ) return "试听音频加载已取消。";
  return "试听音频加载失败，请重新生成试听。";
}


export function createVoicePreviewPlayback(
  React: VoicePreviewPlaybackReactRuntime,
  dependencies: {
    readonly host?: VoicePreviewHost;
    readonly objectUrls?: VoicePreviewObjectUrlApi;
  } = {},
): (props: VoicePreviewPlaybackProps) => unknown {
  const h = React.createElement;
  const objectUrls = dependencies.objectUrls ?? URL;

  return function VoicePreviewPlayback(props: VoicePreviewPlaybackProps): unknown {
    const [state, setState] = React.useState<PlaybackState>({
      phase: "idle",
      objectUrl: null,
      message: "生成试听后，可在这里播放临时音频。",
    });
    const objectUrlRef = React.useRef<string | null>(null);
    const generationRef = React.useRef(0);
    const preview = props.preview;
    const readyIdentity = preview?.status === "ready" && preview.asset !== null
      ? `${preview.preview_id}:${preview.asset.asset_id}:${preview.asset.checksum_sha256}`
      : "";

    React.useEffect(() => {
      const generation = ++generationRef.current;
      const controller = new AbortController();
      if (objectUrlRef.current !== null) {
        objectUrls.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
      if (readyIdentity === "" || preview === null) {
        setState({
          phase: "idle",
          objectUrl: null,
          message: "生成试听后，可在这里播放临时音频。",
        });
        return () => controller.abort();
      }
      setState({ phase: "loading", objectUrl: null, message: "正在安全加载试听音频…" });
      void fetchVoicePreviewObjectUrl(preview, {
        host: dependencies.host,
        objectUrls,
        signal: controller.signal,
      }).then((objectUrl) => {
        if (controller.signal.aborted || generation !== generationRef.current) {
          objectUrls.revokeObjectURL(objectUrl);
          return;
        }
        objectUrlRef.current = objectUrl;
        setState({
          phase: "ready",
          objectUrl,
          message: "试听音频已加载。播放不会自动确认质量或绑定声音。",
        });
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setState({ phase: "error", objectUrl: null, message: playbackErrorMessage(reason) });
      });
      return () => {
        controller.abort();
        if (objectUrlRef.current !== null) {
          objectUrls.revokeObjectURL(objectUrlRef.current);
          objectUrlRef.current = null;
        }
      };
    }, [readyIdentity]);

    return h(
      "section",
      {
        className: ["anw-narration-voice-preview-playback", props.className ?? ""]
          .filter(Boolean)
          .join(" "),
        "data-preview-playback-phase": state.phase,
        "aria-label": "音色试听播放器",
      },
      state.phase === "ready" && state.objectUrl !== null
        ? h("audio", {
          controls: true,
          preload: "metadata",
          src: state.objectUrl,
          "aria-label": "播放当前音色试听",
          onPlay: props.onPlayed,
        })
        : null,
      h(
        "p",
        {
          role: state.phase === "error" ? "alert" : "status",
          "aria-live": "polite",
        },
        state.message,
      ),
    );
  };
}
