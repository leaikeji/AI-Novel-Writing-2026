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
const { CloseOutlined, RobotOutlined } = window.QwenPaw.host.antdIcons;


ensureNovelStyles();


function isNovelWorkbenchChat(): boolean {
  return activeWorkbenchRoute() !== null;
}


function wrapNativeChat(Inner: any) {
  return function NativeChatWithNovelWorkbench() {
    const [chatOpen, setChatOpen] = React.useState(false);
    if (!isNovelWorkbenchChat()) {
      return React.createElement(Inner);
    }

    return React.createElement(
      "div",
      {
        "data-ai-novel-workbench": "active",
        className: `anw-workbench-frame ${chatOpen ? "has-chat" : ""}`,
      },
      React.createElement(
        "section",
        { className: "anw-workbench-main" },
        React.createElement(NovelWorkbench),
      ),
      chatOpen
        ? React.createElement(
            "section",
            { "aria-label": "QwenPaw 原生 AI 助手", className: "anw-native-chat" },
            React.createElement(Inner),
          )
        : null,
      React.createElement(
        "button",
        {
          type: "button",
          className: "anw-chat-toggle",
          onClick: () => setChatOpen((value: boolean) => !value),
          "aria-label": chatOpen ? "关闭 AI 助手" : "打开 AI 助手",
        },
        React.createElement(chatOpen ? CloseOutlined : RobotOutlined),
        " ",
        chatOpen ? "关闭助手" : "AI 助手",
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
