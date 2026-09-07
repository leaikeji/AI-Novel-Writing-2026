/** Visual fixture uses the actual host React and actual client/status modules. */
import { ChapterMethodClient, writingPageTabId } from "../../../../frontend/src/writing-skills/chapter";
import { createWritingMethodStatusNotice } from "../../../../frontend/src/writing-skills/status";
const React = window.QwenPaw.host.React;
const h = React.createElement;
const Notice = createWritingMethodStatusNotice(React);
const DOC = "11111111-1111-4111-8111-111111111111";
const NOVEL = "22222222-2222-4222-8222-222222222222";
const JOB = "33333333-3333-4333-8333-333333333333";
function Fixture() {
  const [snapshot, setSnapshot] = React.useState(null);
  const [counts, setCounts] = React.useState({ post: 0, get: 0 });
  const [message, setMessage] = React.useState("");
  const client = React.useRef(null);
  const mode = React.useRef("success");
  React.useEffect(() => {
    const tabId = writingPageTabId();
    const remoteKey = `s58-fake-remote:${tabId}`;
    const instance = new ChapterMethodClient({ ownerKey: DOC, workspaceKey: NOVEL, tabId,
      scopeKind: "novel", scopeId: NOVEL, documentId: DOC, agentId: "ai-novel-writer" }, setSnapshot,
      async (_path, init) => {
        if (init?.method === "POST") {
          setCounts((old) => ({ ...old, post: old.post + 1 }));
          const actionId = JSON.parse(String(init.body)).writing_action.action_id;
          const output = { id: JOB, document_id: DOC, state: "ready", candidate: { id: JOB }, writing_method: {
            schema_version: "writing-method-status/1", action_id: actionId, dispatch_id: JOB,
            state: "dispatched", method_input_hash: "a".repeat(64), job_ref: `chapter:${JOB}`,
            selected_ids: ["fixture-third", "suspense-writing"], omitted_ids: [],
            auxiliary_calls: 0, semantic_enabled: false } };
          sessionStorage.setItem(remoteKey, JSON.stringify(output));
          if (mode.current === "lost") throw new Error("模拟响应丢失，没有真实模型调用");
          return output;
        }
        setCounts((old) => ({ ...old, get: old.get + 1 }));
        return JSON.parse(sessionStorage.getItem(remoteKey) || "null");
      }, sessionStorage);
    client.current = instance;
    if (instance.getSnapshot().action) void instance.recover().catch(error => setMessage(error.message));
    return () => instance.dispose();
  }, []);
  const start = async (value) => {
    mode.current = value;
    setMessage("");
    try { await client.current.start({ expected_brief_version: 1, force_new: true, asset_ids: [] }); }
    catch (error) { setMessage(error.message); }
  };
  return h("main", { style: { padding: "20px", margin: "0 auto", maxWidth: "720px", minWidth: 0,
    boxSizing: "border-box", color: "#202533", background: "#fff", fontFamily: "system-ui", lineHeight: 1.6 } },
    h("h1", { style: { fontSize: "22px" } }, "写作方法状态 · 隔离视觉测试"),
    h("p", {}, "假响应，不调用模型、不访问小说；使用真实宿主 React 和项目状态组件。"),
    h("div", { style: { display: "flex", flexWrap: "wrap", gap: "10px", marginBottom: "20px" } },
      h("button", { onClick: () => start("success") }, "模拟新生成"),
      h("button", { onClick: () => start("lost") }, "模拟丢失响应"),
      h("button", { onClick: async () => {
        try { await client.current.recover(); setMessage("仅GET查询，没有重复生成"); }
        catch (error) { setMessage(error.message); }
      } }, "查询原任务")),
    h("p", { "data-testid": "counts" }, `模拟POST：${counts.post}；只读GET：${counts.get}`),
    h("p", { role: "status" }, message),
    snapshot ? h(Notice, { snapshot, displayNames: { "fixture-third": "第三分类测试：非常长的自动发现方法名称用于窄屏折行验证", "suspense-writing": "悬疑" } }) : null);
}
window.QwenPaw.route.add("s58-method-ui", { id: "s58-method-ui-page", path: "/apps/s58-method-ui", component: Fixture });
