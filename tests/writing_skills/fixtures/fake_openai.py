"""Loopback-only, bounded OpenAI transport fixture. No model or external IO."""
import hashlib
import json
import argparse
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECEIPTS = []
MARKER = "S58_PAWAPP_METHOD_BYTES"
REPLY_TEXT = "S58_PROBE_OK"
EXPECTED_BLOCKS = {}
SEMANTIC_THEN_CHAPTER = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/stats":
            self.send_error(404)
            return
        payload = json.dumps(RECEIPTS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if self.path != "/v1/chat/completions" or not 0 < size < 500000 or len(RECEIPTS) >= 12:
            self.send_error(400)
            return
        request = json.loads(self.rfile.read(size))
        messages = request.get("messages", [])
        serialized = json.dumps(messages, ensure_ascii=False)
        text_parts = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                text_parts.extend(part["text"] for part in content
                                  if isinstance(part, dict) and isinstance(part.get("text"), str))
        transmitted_text = "\n".join(text_parts)
        reply_text = REPLY_TEXT
        if SEMANTIC_THEN_CHAPTER:
            route_parts = [
                part for part in text_parts
                if "路由数据：" in part and "writing_skill_routing" in part
            ]
            if route_parts:
                route = json.loads(route_parts[-1].split("路由数据：", 1)[1])
                source_key = route["sources"][0]["key"]
                reply_text = json.dumps({
                    "schema_version": "semantic-route-response/1",
                    "decisions": [{
                        "skill_id": item["skill_id"],
                        "decision": "reject",
                        "evidence_refs": [source_key],
                    } for item in route["candidates"]],
                }, ensure_ascii=False)
        RECEIPTS.append({
            "ordinal": len(RECEIPTS) + 1, "model": request.get("model"),
            "method_marker_count": serialized.count(MARKER),
            "primary_heading_count": serialized.count("# 小说正文写作"),
            "primary_heading_counts": {
                "novel-direction": serialized.count("# 小说方向与读者承诺"),
                "story-foundation": serialized.count("# 故事设定总表与总体架构"),
                "character-craft": serialized.count("# 人物塑造与人物弧线"),
                "chapter-outline": serialized.count("# 章节大纲与场景链"),
                "style-review": serialized.count("# 分层审稿与文风修订"),
                "prose-writing": serialized.count("# 小说正文写作"),
            },
            "method_roles": [m.get("role") for m in messages if MARKER in json.dumps(m, ensure_ascii=False)],
            "tools": [t.get("function", {}).get("name") for t in request.get("tools") or []],
            "tool_choice": request.get("tool_choice"),
            "input_hash": hashlib.sha256(serialized.encode()).hexdigest(),
            "approved_block_matches": {name: {"sha256": hashlib.sha256(raw.encode()).hexdigest(),
                                               "count": transmitted_text.count(raw)}
                                       for name, raw in EXPECTED_BLOCKS.items() if raw in transmitted_text},
        })
        base = {"id": "s58-fake-completion", "created": 1, "model": "s58-fake-model"}
        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply_text}, "finish_reason": None}]},
                {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            ]
            for chunk in chunks:
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
        else:
            payload = json.dumps({**base, "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": reply_text}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", action="store_true")
    parser.add_argument("--semantic-then-chapter", action="store_true")
    parser.add_argument("--creative-template", action="store_true")
    parser.add_argument("--creative-naming", action="store_true")
    parser.add_argument("--creative-outline-background", action="store_true")
    parser.add_argument("--creative-outline-characters", action="store_true")
    parser.add_argument("--creative-outline-plot", action="store_true")
    parser.add_argument("--creative-outline-highlight", action="store_true")
    parser.add_argument("--creative-chapter-storyline", action="store_true")
    parser.add_argument("--creative-chapter-outline", action="store_true")
    parser.add_argument("--creative-review", action="store_true")
    parser.add_argument("--creative-selection", action="store_true")
    parser.add_argument("--creative-character-profile", action="store_true")
    parser.add_argument("--storyline-id")
    parser.add_argument("--profile-character-id")
    parser.add_argument("--profile-character-version", type=int)
    parser.add_argument("--profile-source-quote")
    parser.add_argument("--methods-root", type=Path)
    options = parser.parse_args()
    SEMANTIC_THEN_CHAPTER = options.semantic_then_chapter
    if options.chapter:
        REPLY_TEXT = "测" * 1000
    if options.creative_template:
        REPLY_TEXT = json.dumps({
            "genre": "悬疑",
            "template_key": "s58-suspense-template",
            "template_name": "封闭小镇旧案",
            "template_data": {
                "protagonist_identity": "停职刑警",
                "background_setting": "封闭小镇",
                "core_conflict": "死者留下新证词",
                "emotional_mainline": "师徒信任裂痕",
                "style_features": "冷峻克制悬疑",
            },
        }, ensure_ascii=False)
    if options.creative_naming:
        REPLY_TEXT = json.dumps({"titles": [
            "雾宅来信", "消失的门牌", "回声名单", "夜访旧楼",
            "无人签收", "暗门之后", "第七码头", "倒置房间",
        ]}, ensure_ascii=False)
    if options.creative_outline_background:
        REPLY_TEXT = json.dumps({
            "background_text": (
                "连日暴雨切断了封闭小镇与外界的交通，停职刑警林澈在旧档案馆收到一封由死者寄出的新证词。"
                "警局内部对十年前失踪案保持异常沉默，而逐渐上涨的河水正在逼近埋藏原始卷宗的地下库房。"
            ),
        }, ensure_ascii=False)
    if options.creative_outline_characters:
        REPLY_TEXT = json.dumps({"characters": [
            {
                "name": "林澈",
                "role_type": "main",
                "gender": "女",
                "age_at_story_start_note": "三十二岁",
                "identity_summary": "因旧案失误被停职的刑警",
                "personality_summary": "习惯独自承担风险，却会在证据动摇时强迫自己复核判断",
                "core_goal": "在洪水淹没档案馆前查清失踪案并恢复行动资格",
                "bio": "十年前作为见习警员参与旧案，因关键证词遗失一直背负责任。",
            },
            {
                "name": "周栩",
                "role_type": "supporting",
                "gender": "男",
                "age_at_story_start_note": "二十九岁",
                "identity_summary": "管理旧档案的镇史馆员",
                "personality_summary": "表面谨慎回避冲突，遇到档案被篡改时却会坚持留下可复核记录",
                "core_goal": "找回被替换的原始卷宗并保护家人",
                "bio": "熟悉小镇档案流转，在死者来信出现后成为林澈唯一的内部向导。",
            },
            {
                "name": "孟青山",
                "role_type": "supporting",
                "gender": "男",
                "age_at_story_start_note": "五十余岁",
                "identity_summary": "负责旧案的现任分局负责人",
                "personality_summary": "重视秩序与机构信誉，面对旧部时会在保护和控制之间摇摆",
                "core_goal": "在上级调查前维持警局运转并阻止旧案失控",
                "bio": "掌握停职决定与旧案封存程序，对十年前的证据缺口始终保持沉默。",
            },
            {
                "name": "许遥",
                "role_type": "supporting",
                "gender": "女",
                "age_at_story_start_note": "二十六岁",
                "identity_summary": "失踪者家属与社区诊所医生",
                "personality_summary": "愿意帮助任何求助者，但会把无法确认的怀疑藏到最后一刻",
                "core_goal": "确认姐姐失踪真相并让仍在镇上的证人安全离开",
                "bio": "保存着姐姐失踪前的就诊记录，也是死者来信最先点名的人。",
            },
        ]}, ensure_ascii=False)
    if options.creative_outline_plot:
        phases = [
            "开局阶段，暴雨封路，停职刑警林澈收到死者寄出的新证词。她没有立即宣布结论，而是与档案员周栩核对邮戳、纸张和卷宗借阅记录，发现来信使用的是十年前警局内部才有的编号。警局负责人孟青山要求她停止调查，许遥却拿出姐姐失踪前的就诊记录，证明旧案时间线存在一段被人为抹去的夜班空白。",
            "第一轮升级中，林澈按编号追查原始卷宗，地下库房却因河水倒灌即将封闭。她和周栩抢救档案时发现多份证词被同一种复印件替换，原件去向指向早已死亡的保管员。一次看似可靠的目击证词经路线核查后被推翻，使林澈意识到有人利用她对旧案的愧疚引导调查。许遥承认自己隐瞒了一名仍然活着的证人，因为警局内部有人持续监视家属。",
            "中段转折里，四人围绕证人安全、证据资格和行动权限发生冲突。林澈设计公开的假转移计划迫使监视者暴露通讯链，却也让孟青山失去继续保护她的空间。新取得的值班录音表明，死亡保管员只是替人签收，真正能改写卷宗的人来自当年的联合调查组。与此同时，河堤出现人为破坏，档案馆和诊所被迫二选一救援，案件从追查旧真相转为阻止新的灭证行动。",
            "第二轮升级中，林澈选择先救诊所人员，让部分纸质原件被水淹毁，但周栩此前建立的校验目录保住了证据链。孟青山终于交代，他十年前接受过上级指令封存一名关键嫌疑人的记录，却不知道失踪者被秘密安置。这个解释减轻了他的直接嫌疑，却暴露出更大的组织性掩盖。死者来信的墨迹检验显示内容近期书写，署名者并非死者本人，而是熟悉其笔迹和案件编号的幸存证人。",
            "高潮阶段，幸存证人约林澈在废弃泵站交换完整名单，幕后者同时打开泄洪闸制造事故。林澈依据前期核查过的水位、通行路线和通讯盲区安排许遥转移证人，自己与孟青山在泵站固定电子日志。周栩用档案校验目录证明被删记录曾真实存在。幕后者试图把所有责任推给死亡保管员，但新旧时间戳、值班录音和当场行动形成互相独立的证据，迫使其计划失败。",
            "收束阶段，失踪者名单得到公开，仍然活着的人进入保护程序，已经死亡者的去向也被逐一确认。孟青山因隐瞒和违规封存接受调查，林澈没有立即复职，而是以证人身份完成旧案复核。许遥与姐姐重新取得联系，却必须面对姐姐不愿回到小镇的选择。最后一封没有署名的来信指出联合调查组还有一份外地卷宗，为下一阶段留下可行动的新问题，而本阶段关于死者来信、失踪名单和档案篡改的核心承诺已经兑现。",
        ]
        REPLY_TEXT = json.dumps({"plot_text": "\n\n".join(phases)}, ensure_ascii=False)
    if options.creative_outline_highlight:
        REPLY_TEXT = json.dumps({
            "highlight_text": (
                "停职刑警在暴雨封镇之夜收到死者的新证词。她必须在档案馆被洪水吞没前，"
                "分清旧案中的沉默、伪证与保护，追出一份被改写十年的失踪名单。"
            ),
        }, ensure_ascii=False)
    if options.creative_chapter_storyline:
        if not options.storyline_id:
            parser.error("--creative-chapter-storyline requires --storyline-id")
        REPLY_TEXT = json.dumps({
            "storyline_ids": [options.storyline_id],
            "reason": "这条主线直接承接死者来信，并能在本章形成可核查的行动后果。",
        }, ensure_ascii=False)
    if options.creative_chapter_outline:
        REPLY_TEXT = json.dumps({
            "title": "死者来信",
            "outline_text": (
                "林澈先在档案馆核对死者来信的邮戳、纸张批次与内部编号，确认三项信息指向不同时间，"
                "因此没有把来信直接当成死者复活的证据。周栩试图调取借阅日志，却被孟青山以林澈仍在停职为由拒绝，"
                "三人的行动权限出现正面冲突。许遥随后带来姐姐失踪前的就诊记录，记录上的值班签名与来信笔迹相似，"
                "迫使林澈把调查目标从寄信者身份改为谁能同时接触诊所和警局档案。她让周栩公开一份假卷宗转移通知，"
                "自己守在地下库房观察谁会提前行动，代价是孟青山可能以违规调查彻底取消她的查阅资格。守候期间水位报警突然响起，"
                "林澈先救出受潮原件，再发现借阅日志显示那名死者当天刚签出卷宗；结尾处，监控画面里出现的取件人却穿着许遥的雨衣。"
            ),
        }, ensure_ascii=False)
    if options.creative_review:
        REPLY_TEXT = json.dumps({
            "passed": False,
            "summary": "正文证据链基本清楚，但有一处人物已知信息越界。",
            "issues": [{
                "severity": "P1",
                "type": "人物已知信息",
                "evidence": "周栩直接说出尚未向他公开的就诊记录内容。",
                "suggestion": "先让许遥展示记录，再由周栩据此判断签名。",
            }],
        }, ensure_ascii=False)
    if options.creative_selection:
        REPLY_TEXT = json.dumps({
            "replacement_text": "林澈停在档案架前，重新核对死者来信的邮戳。",
            "short_summary": "让动作与证据核查更具体。",
        }, ensure_ascii=False)
    if options.creative_character_profile:
        if not (
            options.profile_character_id
            and options.profile_character_version is not None
            and options.profile_source_quote
        ):
            parser.error(
                "--creative-character-profile requires --profile-character-id, "
                "--profile-character-version and --profile-source-quote"
            )
        REPLY_TEXT = json.dumps({
            "characters": [{
                "character_id": options.profile_character_id,
                "base_version": options.profile_character_version,
                "status": "candidate",
                "personality": "面对证据冲突会反复核对，并承担延误行动的风险",
                "basis": "designed",
                "confidence": 88,
                "evidence": [{
                    "source_type": "character",
                    "source_id": options.profile_character_id,
                    "quote": options.profile_source_quote,
                }],
                "warnings": [],
            }],
        }, ensure_ascii=False)
    if options.methods_root:
        root = options.methods_root.resolve(strict=True)
        if not str(root).startswith("/tmp/s58-") or root.name != "skills":
            raise RuntimeError("method inspection requires the disposable fixture skills directory")
        EXPECTED_BLOCKS = {str(path.relative_to(root)): path.read_text()
                           for path in root.glob("**/*.md") if path.is_file() and not path.is_symlink()}
    print("s58-fake-openai listening on container loopback:9123", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 9123), Handler).serve_forever()
