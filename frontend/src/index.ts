import {
  APP_ID,
  APP_PATH,
  APP_ROUTE_ID,
  CORE_CHAT_ROUTE_ID,
} from "./contracts";
import { NovelLibraryPage, NovelWorkbench } from "./workbench-v2";
import { activeWorkbenchRoute } from "./workbench-route";
import { ensureNovelStyles } from "./styles";


const React = window.QwenPaw.host.React;


ensureNovelStyles();


function isNovelWorkbenchChat(): boolean {
  return activeWorkbenchRoute() !== null;
}


function wrapNativeChat(Inner: any) {
  return function NativeChatWithNovelWorkbench() {
    if (!isNovelWorkbenchChat()) {
      return React.createElement(Inner);
    }

    return React.createElement(
      "div",
      {
        "data-ai-novel-workbench": "active",
        className: "anw-workbench-frame",
      },
      React.createElement(
        "section",
        { className: "anw-workbench-main" },
        React.createElement(NovelWorkbench),
      ),
    );
  };
}


window.QwenPaw.route.add(APP_ID, {
  id: APP_ROUTE_ID,
  path: APP_PATH,
  component: NovelLibraryPage,
});

window.QwenPaw.route.wrap(APP_ID, CORE_CHAT_ROUTE_ID, wrapNativeChat);
