import {
  CHAT_PATH,
  CREATIVE_CENTER_CHAT_PATH,
} from "./contracts";
import { rememberCreativeCenterRoute } from "./workbench-route";


export function creativeCenterEntryTarget(search: string): string {
  const source = new URLSearchParams(search);
  const target = new URLSearchParams(CREATIVE_CENTER_CHAT_PATH.split("?")[1]);
  if (source.get("view") === "private-library") {
    target.set("view", "private-library");
  }
  return `${CHAT_PATH}?${target.toString()}`;
}


export function CreativeCenterEntry() {
  const host = window.QwenPaw.host;
  const React = host.React;
  const h = React.createElement;
  const { Spin } = host.antd;

  React.useEffect(() => {
    rememberCreativeCenterRoute();
    window.location.replace(creativeCenterEntryTarget(window.location.search));
  }, []);

  return h(
    "main",
    { className: "anw-app anw-empty-state", "aria-live": "polite" },
    h(Spin),
    h("strong", null, "正在打开创作中心…"),
  );
}
