"""Create a fresh three-chapter experiment and exercise the installed vector path.

Run this inside the installed PawApp container.  The script never reads or prints
the embedding credential; all vector calls go through the public PawApp API.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.creative_data_models import (
    EmbeddingGeneration,
    EmbeddingGenerationNovel,
    NovelEmbeddingConsent,
    SemanticChunk,
    SemanticEmbedding,
    SemanticSource,
)
from backend.database import get_engine
from backend.models import ChapterBrief, CharacterAlias, IntelligenceProposal, StoryFact
from backend.services import (
    commit_intelligence_items,
    complete_intelligence_proposal,
    start_intelligence_proposal,
)


BASE = "http://127.0.0.1:8088/api/ai-novel-world-2026"
SCOPES = [
    "formal_manuscript",
    "formal_planning",
    "author_secrets",
    "bound_private_assets",
]
SYNTHETIC_PROVIDER = "local-e2e"
SYNTHETIC_MODEL = "ledger-fixture-v1"


def call(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    *,
    expected: tuple[int, ...] = (200, 201, 202),
) -> Any:
    url = BASE + path
    if query:
        url += "?" + urlencode({key: value for key, value in query.items() if value is not None})
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=180) as response:
            raw = response.read()
            if response.status not in expected:
                raise RuntimeError(f"unexpected HTTP {response.status}: {url}")
            return json.loads(raw) if raw else None
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {error.code}: {detail}") from error


def visible_length(text: str) -> int:
    return len("".join(text.split()))


def chapter(base: str, motif: str) -> str:
    """Deterministically bring authored test prose into the 2k-character band."""

    supplements = [
        f"{motif}的铜牌在风里轻轻碰墙，每一声都像给记忆加上新的页码。沈见星把所见、所闻和自己的推测分成三栏，不让任何一句话冒充事实。",
        "窗外的海雾沿着排水槽往上爬，码头吊臂只剩下模糊黑影。陆遥反复核对时钟、邮戳和值班簿，宁愿留下空白，也不把不确定的时间填成精确数字。",
        "他们约定，从此每封逆潮信都必须保留原件、拆封人、读取时间和当时知情者。这规矩看似繁琐，却让他们在奇迹面前仍能分清证据与愿望。",
        "记录纸的边角被潮气卷起，蓝色钢笔字渐渐发肿。沈见星换了一张纸，但没有把旧纸丢掉：被修正的记录也是历史的一部分。",
        "周策的脚步偶尔从楼上传来，在水泥顶棚上拖出缓慢回声。两人没有立即停下调查，只把未知风险写进新的警示栏。",
        "海面上有一束巡航灯缓缓扫过，照亮湿漉的邮袋，又很快移向更远的防波堤。光线每次返回，房间里的物件都仍在原位，只有人的判断在改变。",
        "为了避免误伤未来，他们把能做的事缩小到当下：确认一枚邮戳，保护一名收信人，找到一条真实可走的路。任何更宏大的结论都留待证据补齐。",
        "旧邮局的墙钟比港务台慢三十七秒。陆遥把这个差值写在页脚，因为小误差在普通日子里可以忽略，在时间倒流的夜晚却可能决定一封信属于哪一天。",
    ]
    text = base.strip()
    index = 0
    while visible_length(text) < 2000:
        text += "\n\n" + supplements[index % len(supplements)]
        index += 1
    if visible_length(text) > 2350:
        raise AssertionError("chapter padding exceeded the intended test band")
    return text


CHAPTERS = [
    chapter(
        """# 第一章 明日退信

2034年10月3日的零点刚过，逆潮邮局的投递口自己响了一声。沈见星正在整理已停用的航线邮袋，听见金属挡板回弹，便戴上手套走过去。地上躺着一封干燥的白信，可窗外正下着能把人衣领灌满的横雨。

信封没有寄件人，收件人写的却是“明日值班的沈见星”。右上角邮戳清楚印着“2034年10月4日”。她没有拆，先拍照，再把当日班表、门禁和监控时间并排写在记录纸上。邮局里只有她，门从十一点后没有开过。

港务钟表维修员陆遥十分钟后赶来。他用便携显微镜看了邮戳，又用镊子夹下一点蓝色封蜡。“油墨没干，”他说，“但纸纤维比室内湿度低得多。它不像在今晚的雨里走过。”

他们在镜头下拆信。信纸只有一句：“凌晨二点十七分，不要让第七码头的红色邮车进闸。”落款处本该是签名，却只有一道被水泡散的蓝线。

周策是邮局代管人，也是唯一有权调出旧码头记录的人。他在电话里听完经过，只说可能是恶作剧，并要求沈见星把信交到楼上保险柜。沈见星答应了，却先把信的特征与时间全部录入本地账本。

一点五十分，港区调度台回复：第七码头今夜没有进车计划。两人还是带着信赶到闸口。两点十六分，浓雾里真的亮起两盏红灯，一辆无牌邮车正沿废弃轨道滑向已落锁的潮闸。

沈见星拉下紧急断电杆，陆遥则用工具卡住机械锁。邮车在两人面前半米停下，车厢内没有司机，只堆着七个滴水的邮袋。当指针跳到二点十七分，所有邮袋上的日期同时从四日褪成三日。

沈见星把旧名写进停用栏，决定从下一份记录起使用母亲留给她的名字“沈照”。她没有撤销旧签名，因为那些信、照片和当夜的选择仍然属于同一个人。""",
        "逆潮邮局",
    ),
    chapter(
        """# 第二章 潮汐分拣室

10月4日早上，沈照和陆遥把七个邮袋移进地下分拣室。每个袋子都只容许一人拆封、一人记录，随后交换角色复核。他们在第三个袋子里找到了一张二十七年前的船难名单，末尾却多出了沈照今天才写下的新名。

周策带着两名保安下楼，要求立即封存邮袋。沈照向他展示了连续编号和全程录像，也承认自己不知道名字为何会出现在旧纸上。周策没有回答，只盯着名单角落的蓝蜡封，手指不自觉地握紧。

陆遥从旧机械图里找到一条被涂黑的运送轨道。轨道从邮局地下延伸到第七码头，中途经过一座已封闭的潮汐计算室。“如果邮车不是从路面进来，”他说，“它只能从这里出现。”

两人在潮位最低时进入计算室。墙上排着三十一只黑色齿轮，它们把港口每日的涨落换算成分拣时刻。中央齿轮多了一个本不应存在的逆向棘爪，每当大潮越过标线，它就把邮车的记录向前拨一日。

沈照与陆遥在分拣室确立互信，约定任何人都不能单独改动逆向棘爪。这个约定被写进账本，并由两人分别签名。

他们在齿轮背后找到一封未寄出的信，收件人是周策，落款却是他已去世的父亲。信中说，逆潮系统最初用于在台风前送回一日的灾难警报，但每送回一封信，就会有一份同日记录被潮水“取走”。

蓝色蜡封在信纸背面留下一枚七角印。陆遥认出这不是家族纹章，而是旧港区七道潮闸中最后一道的机械许可证。他们终于找到了通向第七码头的返回路线，但开门的钥匙仍在周策手里。""",
        "地下分拣室",
    ),
    chapter(
        """# 第三章 第七码头的回邮

10月5日的凌晨大潮前，周策主动来到邮局。他带来了蓝蜡封的铜模和一本缺了三页的旧值班簿。他承认，父亲死后自己曾两次启动逆潮系统，试图改写一场没能阻止的船难。第一次警报提前送达，第二次却让一整班救生员的值班记录消失。

沈照没有立即原谅他，也没有把他从调查中排除。她把周策的自述标成“待与原始记录交叉验证”，然后让他在每一页复印件上签名。周策照做了，并把铜模交给陆遥封存。

三人沿地下轨道前往第七码头。潮水在隧道铁门外不断拍打，铜模压进七角凹槽后，门后的机械转了七圈才让出一条只容一人通过的缝。这证实蓝蜡封实际是潮闸开门许可，而不是某个人的私人标记。

码头尽头停着那辆无牌邮车。车厢地板下藏着一台记录机，能把投入的纸张与潮位曲线绑定，在次日大潮时送回前一日。但记录机无法辨认信上的善意或恶意，它只按照纸张的时间标记工作。

沈照学会了逆潮投递规则：信可以向前送一日，但不会自动把未来变成已发生的事实；收信人的选择依然要留在新的记录中。她把这条规则口述给陆遥和周策，三人分别复述，确认没有把推测当成结论。

他们没有销毁记录机。周策提议再寄一封信回去，警告父亲不要启动第二次。沈照拒绝了：他们尚不知道那三页值班簿因何消失，更不知道新信会换走谁的记录。

最终，他们把记录机留在原位，却取下逆向棘爪，用三把不同的锁分别封存。邮局保留证据，港务台保管铜模，陆遥保管机械图。任何再启动都需要三方同意。

天亮时，沈照把第一封明日退信放进透明证物袋。邮戳还是四日，账本上的接收时间仍是三日。两个日期并排存在，没有谁被静默删除。""",
        "第七码头",
    ),
]


def catalog_key(proposal: IntelligenceProposal, catalog: str, entity_field: str, entity_id: str) -> str:
    rows = proposal.extraction_context_json[catalog]
    return next(key for key, value in rows.items() if value.get(entity_field) == entity_id)


def commit_fixture_facts(
    session: Any,
    document_id: str,
    revision_id: str,
    definitions: list[dict[str, Any]],
) -> list[str]:
    started = start_intelligence_proposal(
        session,
        UUID(document_id),
        revision_id=UUID(revision_id),
        execution_agent_id="ai-novel-writer",
        requested_provider_id=SYNTHETIC_PROVIDER,
        requested_model_id=SYNTHETIC_MODEL,
        generation_contract_version="ledger-joint-e2e/1",
    )
    proposal = session.get(IntelligenceProposal, UUID(started["id"]))
    assert proposal is not None
    for item in definitions:
        target = item.pop("_catalog", None)
        if target:
            item["entity_key"] = catalog_key(proposal, *target)
    completed = complete_intelligence_proposal(
        session,
        proposal.id,
        items=definitions,
        actual_provider_id=SYNTHETIC_PROVIDER,
        actual_model_id=SYNTHETIC_MODEL,
    )
    if len(completed["items"]) != len(definitions):
        raise AssertionError(f"fixture fact normalization dropped items: {completed['items']}")
    accepted = [UUID(item["id"]) for item in completed["items"]]
    result = commit_intelligence_items(session, proposal.id, accepted_item_ids=accepted)
    committed_ids = [
        item["committed_story_fact_id"]
        for item in result["items"]
        if item.get("committed_story_fact_id")
    ]
    if len(committed_ids) != len(accepted):
        raise AssertionError("accepted fixture facts were not all committed")
    return committed_ids


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    title = f"逆潮邮局（账本向量联合复验·{stamp}）"
    report: dict[str, Any] = {"title": title, "chapter_visible_lengths": []}

    config_before = call("GET", "/embedding-config")
    assert config_before["api_key_configured"] is True
    assert config_before["requested_dimension"] == 2048
    assert config_before["candidate_generation"]["dimension"] == 2048

    novel = call(
        "POST",
        "/novels",
        {
            "title": title,
            "description": "全新独立的三章实验小说，联合验证人物改名、章纲稳定引用、故事时间与年龄、StoryFact 投影、私有素材固定版本和 2048 维语义索引。",
        },
    )
    novel_id = novel["id"]
    report["novel_id"] = novel_id
    timeline = call("GET", f"/novels/{novel_id}/timelines")["items"][0]
    timeline_id = timeline["id"]

    character_specs = [
        ("main", "沈见星", "逆潮邮局值班员，习惯将事实、证据和推测分开记录。"),
        ("supporting", "陆遥", "港务钟表与机械系统维修员。"),
        ("supporting", "周策", "邮局代管人，隐瞒过去启动逆潮系统的经历。"),
    ]
    characters: dict[str, dict[str, Any]] = {}
    for role_type, name, description in character_specs:
        characters[name] = call(
            "POST",
            f"/novels/{novel_id}/characters",
            {
                "role_type": role_type,
                "name": name,
                "description": description,
                "details": {"theme": "记录与选择"},
            },
        )

    instances = call("GET", f"/novels/{novel_id}/character-instances")
    by_character = {item["character_id"]: item for item in instances}
    profiles = {
        "沈见星": {
            "public_identity": "邮局值班员",
            "true_identity": "逆潮系统原始设计者的外孙女",
            "cover_identity": None,
            "birth_year": 2005,
            "birth_calendar_id": "gregorian",
            "birth_information": "2005年出生，月日未定",
            "occupation": "邮局值班员",
            "personality": "审慎、能容忍不确定性",
            "goals": ["弄清明日退信的规则"],
            "flaws": ["过度承担责任"],
            "secrets": ["母亲留下另一个名字沈照"],
            "growth_direction": "从独自承担到建立可复核的同盟",
        },
        "陆遥": {
            "public_identity": "港务维修员",
            "birth_year": 2002,
            "birth_calendar_id": "gregorian",
            "occupation": "钟表与机械系统维修员",
            "personality": "精确、不轻易下结论",
            "goals": ["证明逆潮系统的机械边界"],
            "flaws": ["不擅长表达情绪"],
            "secrets": [],
            "growth_direction": "从旁观者变为共同负责的记录者",
        },
        "周策": {
            "public_identity": "邮局代管人",
            "true_identity": "逆潮系统前操作者",
            "birth_year": 1989,
            "birth_calendar_id": "gregorian",
            "occupation": "邮局代管人",
            "personality": "克制、因内疚而隐瞒",
            "goals": ["阻止系统再次失控"],
            "flaws": ["倾向以封锁信息代替协作"],
            "secrets": ["曾两次启动逆潮系统"],
            "growth_direction": "从隐瞒转向接受公开审查",
        },
    }
    for name, profile in profiles.items():
        current_novel = call("GET", f"/novels/{novel_id}")
        instance = by_character[characters[name]["id"]]
        call(
            "PUT",
            f"/novels/{novel_id}/character-instances/{instance['id']}/profile",
            {
                "expected_story_ledger_version": current_novel["story_ledger_version"],
                "expected_instance_version": instance["version"],
                "operation_key": f"joint-e2e-profile-{name.encode().hex()[:16]}",
                "source_kind": "manual",
                "profile": {"schema_version": "character-instance-profile/1", **profile},
            },
        )
        by_character[characters[name]["id"]] = call(
            "GET", f"/novels/{novel_id}/character-instances", query={"character_id": characters[name]["id"]}
        )[0]

    outline = call(
        "PATCH",
        f"/novels/{novel_id}/outline",
        {
            "expected_head_version": 0,
            "idempotency_key": f"joint-e2e-outline-{stamp}",
            "source_kind": "manual",
            "target_chapter_count": 3,
            "background_text": "2034年的海港城，旧邮局与潮闸机械系统共用一套时刻记录。",
            "plot_text": "一封来自明日的退信引出逆潮投递系统，三人在保留证据的前提下阻止系统再次被滥用。",
            "highlight_text": "时间异常不自动改写权威账本，人的选择以新事件留痕。",
            "character_revision_refs": [],
            "change_set": {"joint_e2e": True},
        },
    )
    setting = call(
        "PATCH",
        f"/novels/{novel_id}/story-settings",
        {
            "expected_head_version": 0,
            "idempotency_key": f"joint-e2e-setting-{stamp}",
            "source_kind": "manual",
            "schema_id": "joint-e2e-world",
            "schema_version": 1,
            "settings": {
                "calendar_id": "gregorian",
                "current_story_year": 2034,
                "rule": "信件可随大潮向前投递一日，但不自动导入事实。",
                "secret": "每次投递会使同日的一份记录丢失。",
            },
            "change_set": {"joint_e2e": True},
        },
    )
    outline_head_version = outline["head_version"]

    relationship = call(
        "POST",
        f"/novels/{novel_id}/relationships",
        {
            "source_character_id": characters["沈见星"]["id"],
            "target_character_id": characters["陆遥"]["id"],
            "timeline_id": timeline_id,
            "source_character_instance_id": by_character[characters["沈见星"]["id"]]["id"],
            "target_character_instance_id": by_character[characters["陆遥"]["id"]]["id"],
            "label": "调查搭档",
            "relation_type": "协作",
            "directionality": "undirected",
            "relation_kind": "ally",
            "description": "作者规划的调查合作关系根。",
        },
    )
    storyline = call(
        "POST",
        f"/novels/{novel_id}/storylines",
        {"storyline_type": "main", "title": "明日退信", "description": "追查逆潮投递系统并建立三方制衡。"},
    )
    foreshadow = call(
        "POST",
        f"/novels/{novel_id}/foreshadows",
        {"title": "蓝色蜡封", "content": "信件上的七角蓝蜡封用途不明。", "latest_progress": "待查"},
    )

    asset = call(
        "POST",
        "/private-assets",
        {
            "asset_type": "plot",
            "title": f"逆潮系统私密规则·{stamp}",
            "content": "私密口令：七角蓝蜡封对应第七潮闸；不得将这条规则表述为人物已知事实。",
        },
    )
    bound_version_id = asset["current_version_id"]
    call(
        "PUT",
        f"/novels/{novel_id}/asset-bindings",
        {
            "expected_binding_versions": {},
            "selections": [
                {"asset_id": asset["id"], "asset_version_id": bound_version_id, "usage_policy": "required", "position": 0}
            ],
            "operation_key": f"joint-e2e-bind-{stamp}",
        },
    )
    updated_asset = call(
        "PUT",
        f"/private-assets/{asset['id']}",
        {
            "expected_version": asset["version"],
            "title": asset["title"],
            "content": asset["content"] + "\n新版增补：第七潮闸的锁需要三方共同开启。",
        },
    )
    binding_after_update = call("GET", f"/novels/{novel_id}/asset-bindings")[0]
    assert binding_after_update["asset_version_id"] == bound_version_id
    assert binding_after_update["update_available"] is True
    assert updated_asset["current_version_id"] != bound_version_id

    # Novel creation intentionally provisions one blank first chapter and its
    # default volume. Reuse both so the fixture remains an exact three-chapter
    # novel instead of accumulating a redundant empty chapter/volume.
    initial_tree = call("GET", f"/novels/{novel_id}/tree")
    assert len(initial_tree) == 1 and len(initial_tree[0]["documents"]) == 1
    initial_volume = call(
        "PUT",
        f"/novels/{novel_id}/volumes/{initial_tree[0]['id']}",
        {"expected_version": initial_tree[0]["version"], "title": "第一卷 逆潮记录"},
    )
    initial_document = initial_tree[0]["documents"][0]
    assert initial_document["content_markdown"] == ""
    documents: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    for index, text in enumerate(CHAPTERS, start=1):
        length = visible_length(text)
        report["chapter_visible_lengths"].append(length)
        assert 1950 <= length <= 2350
        chapter_title = ["明日退信", "潮汐分拣室", "第七码头的回邮"][index - 1]
        if index == 1:
            document = call(
                "PUT",
                f"/novels/{novel_id}/documents/{initial_document['id']}",
                {"expected_version": initial_document["version"], "title": chapter_title},
            )
        else:
            document = call(
                "POST",
                f"/novels/{novel_id}/documents",
                {
                    "title": chapter_title,
                    "kind": "chapter",
                    "volume_id": initial_volume["id"],
                },
            )
        required_name = "沈见星" if index == 1 else "沈照"
        brief = call(
            "PUT",
            f"/documents/{document['id']}/chapter-brief",
            {
                "expected_version": 0,
                "target_word_count": 2000,
                "expectation_text": "保留事实、证据、推测的边界。",
                "outline_text": f"完成第{index}章的调查节点。",
                "forbidden_text": "禁止让时间异常静默改写旧记录。",
                "role_constraints": {"required": [required_name]},
            },
        )
        saved = call(
            "PATCH",
            f"/documents/{document['id']}/draft",
            {"expected_draft_version": document["draft_version"], "content_markdown": text},
        )
        checkpoint = call(
            "POST",
            f"/documents/{document['id']}/checkpoints",
            {"expected_draft_version": saved["draft_version"]},
        )
        revision = checkpoint["revision"]
        call(
            "PUT",
            f"/novels/{novel_id}/documents/{document['id']}/revisions/{revision['id']}/timeline-mapping",
            {
                "expected_head_version": 0,
                "operation_key": f"joint-e2e-map-{index}-{stamp}",
                "segments": [
                    {
                        "timeline_id": timeline_id,
                        "source_start": 0,
                        "source_end": len(revision["content_text"]),
                        "story_sequence": index * 100,
                        "story_time": {
                            "schema_version": "story-time/1",
                            "label": f"2034年10月{index + 2}日",
                            "calendar_id": "gregorian",
                            "lower_bound": 2034,
                            "upper_bound": 2034,
                            "precision": "exact",
                        },
                    }
                ],
            },
        )
        documents.append({**document, "brief": brief})
        revisions.append(revision)

        if index == 1:
            old_root_id = characters["沈见星"]["id"]
            renamed = call(
                "PUT",
                f"/novels/{novel_id}/characters/{old_root_id}",
                {
                    "expected_version": characters["沈见星"]["version"],
                    "role_type": "main",
                    "name": "沈照",
                    "description": characters["沈见星"]["description"],
                    "details_patch": {"theme": "记录与选择", "rename_reason": "使用母亲留下的名字"},
                },
            )
            assert renamed["id"] == old_root_id
            characters["沈照"] = renamed

    Session = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with Session() as session:
        created_facts: list[str] = []
        created_facts += commit_fixture_facts(
            session,
            documents[0]["id"],
            revisions[0]["id"],
            [
                {
                    "fact_type": "character_state",
                    "_catalog": ("character_catalog", "character_id", characters["沈照"]["id"]),
                    "dimension": "official_name",
                    "event_kind": "renamed",
                    "subject": "沈见星",
                    "predicate": "改用名字",
                    "object": "沈照",
                    "source_text": "沈见星把旧名写进停用栏",
                    "reasoning_summary": "正文明确记录改名行为",
                    "confidence": 99,
                    "visibility": "all",
                    "details": {},
                }
            ],
        )
        created_facts += commit_fixture_facts(
            session,
            documents[1]["id"],
            revisions[1]["id"],
            [
                {
                    "fact_type": "relationship_state",
                    "_catalog": ("relationship_catalog", "relationship_id", relationship["id"]),
                    "dimension": "trust",
                    "event_kind": "deepened",
                    "subject": "沈照与陆遥",
                    "predicate": "建立",
                    "object": "互信",
                    "source_text": "沈照与陆遥在分拣室确立互信",
                    "reasoning_summary": "关系状态在故事内发生变化",
                    "confidence": 99,
                    "visibility": "reader",
                    "details": {},
                },
                {
                    "fact_type": "storyline_event",
                    "_catalog": ("storyline_catalog", "storyline_id", storyline["id"]),
                    "dimension": "investigation_progress",
                    "event_kind": "route_found",
                    "subject": "明日退信主线",
                    "predicate": "找到",
                    "object": "第七码头返回路线",
                    "source_text": "他们终于找到了通向第七码头的返回路线",
                    "reasoning_summary": "主线进展有明确证据",
                    "confidence": 98,
                    "visibility": "reader",
                    "details": {"event": "route_found", "status": "active", "progress": 70},
                },
            ],
        )
        created_facts += commit_fixture_facts(
            session,
            documents[2]["id"],
            revisions[2]["id"],
            [
                {
                    "fact_type": "foreshadow_event",
                    "_catalog": ("foreshadow_catalog", "foreshadow_id", foreshadow["id"]),
                    "dimension": "blue_wax_seal",
                    "event_kind": "resolve",
                    "subject": "蓝色蜡封",
                    "predicate": "真实用途",
                    "object": "潮闸开门许可",
                    "source_text": "蓝蜡封实际是潮闸开门许可",
                    "reasoning_summary": "伏笔在正文中明确揭晓",
                    "confidence": 99,
                    "visibility": "reader",
                    "details": {"event": "resolve", "note": "七角蜡封对应第七潮闸"},
                },
                {
                    "fact_type": "knowledge_event",
                    "_catalog": ("character_catalog", "character_id", characters["沈照"]["id"]),
                    "dimension": "reverse_tide_rule",
                    "event_kind": "learn",
                    "subject": "沈照",
                    "predicate": "学会",
                    "object": "逆潮投递规则",
                    "source_text": "沈照学会了逆潮投递规则",
                    "reasoning_summary": "人物知识边界在第三章改变",
                    "confidence": 99,
                    "visibility": "reader",
                    "details": {"operation": "learn", "knowledge_key": "reverse_tide_rule"},
                },
            ],
        )
        report["created_story_fact_ids"] = created_facts

        aliases = tuple(
            session.scalars(
                select(CharacterAlias).where(CharacterAlias.character_id == UUID(characters["沈照"]["id"]))
            )
        )
        alias_values = {(item.alias, item.alias_kind, item.lifecycle_state) for item in aliases}
        assert ("沈见星", "former_name", "active") in alias_values
        assert ("沈照", "official_name", "active") in alias_values
        report["aliases"] = sorted([list(value) for value in alias_values])

    # Chapter-one brief must keep the same root and instance after the display-name change.
    with Session() as session:
        brief_one = session.scalar(
            select(ChapterBrief).where(ChapterBrief.document_id == UUID(documents[0]["id"]))
        )
        assert brief_one is not None
        stable_ref = brief_one.role_constraints["_v3"]["required_characters"][0]
    assert stable_ref["character_id"] == characters["沈照"]["id"]
    assert stable_ref["character_instance_id"] == by_character[characters["沈见星"]["id"]]["id"]
    report["stable_chapter_ref"] = stable_ref

    context = call("GET", f"/novels/{novel_id}/context", query={"document_id": documents[2]["id"], "max_chars": 30000})
    context_text = json.dumps(context, ensure_ascii=False)
    assert '"lower_bound": 2034' in context_text
    assert '"upper_bound": 2034' in context_text
    assert '"minimum_age": 28' in context_text and '"maximum_age": 29' in context_text
    report["context_has_story_year_2034"] = True
    report["context_has_shenzhao_age_range_28_29"] = True

    facts_before_reads = len(call("GET", f"/novels/{novel_id}/story-facts"))
    projected_relationships = call("GET", f"/novels/{novel_id}/relationships", query={"timeline_id": timeline_id, "narrative_cutoff": 300})
    projected_storylines = call("GET", f"/novels/{novel_id}/storylines", query={"timeline_id": timeline_id, "narrative_cutoff": 300})
    projected_foreshadows = call("GET", f"/novels/{novel_id}/foreshadows", query={"timeline_id": timeline_id, "narrative_cutoff": 300})
    call("GET", f"/novels/{novel_id}/story-state", query={"timeline_id": timeline_id, "narrative_cutoff": 300})
    facts_after_reads = len(call("GET", f"/novels/{novel_id}/story-facts"))
    assert facts_before_reads == facts_after_reads == 5
    relationship_view = next(item for item in projected_relationships if item["id"] == relationship["id"])
    storyline_view = next(item for item in projected_storylines if item["id"] == storyline["id"])
    foreshadow_view = next(item for item in projected_foreshadows if item["id"] == foreshadow["id"])
    assert relationship_view["latest_state"] == "互信"
    assert storyline_view["status"] == "active" and storyline_view["progress"] == 70
    assert foreshadow_view["status"] == "resolved" and foreshadow_view["progress"] == 100
    report["projection"] = {
        "relationship_latest_state": relationship_view["latest_state"],
        "storyline_status": storyline_view["status"],
        "storyline_progress": storyline_view["progress"],
        "foreshadow_status": foreshadow_view["status"],
        "foreshadow_progress": foreshadow_view["progress"],
        "read_path_story_fact_delta": facts_after_reads - facts_before_reads,
    }
    assert call("GET", f"/novels/{novel_id}/outline")["head_version"] == outline_head_version

    # Only the fresh novel receives consent. This is the first point at which its
    # formal content may be sent to the configured embedding service.
    consent = call(
        "PUT",
        f"/novels/{novel_id}/embedding-consent",
        {
            "action": "grant",
            "expected_version": 0,
            "notice_version": "novel-embedding-consent/1",
            "acknowledged_scopes": SCOPES,
        },
    )
    assert consent["state"] == "granted"
    call("POST", f"/novels/{novel_id}/semantic-index/rebuild", {})

    deadline = time.monotonic() + 300
    status = call("GET", f"/novels/{novel_id}/semantic-index/status")
    while status["state"] not in {"update_pending", "current", "partial_failure"} and time.monotonic() < deadline:
        time.sleep(2)
        status = call("GET", f"/novels/{novel_id}/semantic-index/status")
    if status["state"] == "partial_failure":
        raise AssertionError(f"semantic build failed: {status}")

    # Candidate state is authoritative; status remains update_pending until activation.
    config_ready = call("GET", "/embedding-config")
    while config_ready["candidate_generation"]["state"] != "ready" and time.monotonic() < deadline:
        time.sleep(2)
        config_ready = call("GET", "/embedding-config")
    assert config_ready["candidate_generation"]["state"] == "ready", config_ready
    evaluated = call(
        "POST",
        "/embedding-config/candidate/evaluate",
        {"expected_version": config_ready["version"]},
    )
    assert evaluated["candidate_generation"]["evaluation_state"] == "passed", evaluated
    activated = call(
        "POST",
        "/embedding-config/candidate/activate",
        {"expected_version": evaluated["version"]},
    )
    assert activated["state"] == "active" and activated["dimension"] == 2048

    semantic = call(
        "POST",
        f"/novels/{novel_id}/semantic-search",
        {
            "schema_version": "semantic-search/1",
            "query": "七角蓝蜡封对应哪道潮闸",
            "corpora": ["manuscript", "planning", "private_asset"],
            "top_k": 5,
            "timeline_id": timeline_id,
            "narrative_sequence": 300,
            "perspective": {"kind": "author", "character_instance_id": None},
        },
    )
    assert semantic["hits"]
    assert all(hit["source_id"] for hit in semantic["hits"])
    report["semantic_search"] = {
        "hit_count": len(semantic["hits"]),
        "channels": sorted({channel for hit in semantic["hits"] for channel in hit["channels"]}),
        "top_source_type": semantic["hits"][0]["source_type"],
        "top_snippet": semantic["hits"][0]["snippet"][:160],
    }

    with Session() as session:
        generation = session.get(EmbeddingGeneration, UUID(activated["id"]))
        assert generation is not None
        build = session.scalar(
            select(EmbeddingGenerationNovel).where(
                EmbeddingGenerationNovel.generation_id == generation.id,
                EmbeddingGenerationNovel.novel_id == UUID(novel_id),
            )
        )
        assert build is not None and build.state == "ready"
        dimensions = set(
            session.scalars(
                select(SemanticEmbedding.dimension)
                .join(SemanticChunk, SemanticChunk.id == SemanticEmbedding.chunk_id)
                .join(SemanticSource, SemanticSource.id == SemanticChunk.source_id)
                .where(
                    SemanticSource.generation_id == generation.id,
                    SemanticSource.novel_id == UUID(novel_id),
                )
            )
        )
        assert dimensions == {2048}
        authorized_ids = set(
            session.scalars(
                select(NovelEmbeddingConsent.novel_id).where(NovelEmbeddingConsent.revoked_at.is_(None))
            )
        )
        assert authorized_ids == {UUID(novel_id)}
        foreign_sources = int(
            session.scalar(
                select(func.count()).select_from(SemanticSource).where(
                    SemanticSource.generation_id == generation.id,
                    SemanticSource.novel_id != UUID(novel_id),
                )
            )
            or 0
        )
        assert foreign_sources == 0
        report["vector_index"] = {
            "generation_id": str(generation.id),
            "dimension_set": sorted(dimensions),
            "source_count": build.source_count,
            "chunk_count": build.chunk_count,
            "embedded_count": build.embedded_count,
            "authorized_novel_ids": sorted(str(value) for value in authorized_ids),
            "foreign_source_count": foreign_sources,
            "evaluation_state": generation.evaluation_state,
        }

    final_status = call("GET", f"/novels/{novel_id}/semantic-index/status")
    assert final_status["state"] == "current"
    assert final_status["active_dimension"] == 2048
    report["semantic_index_status"] = final_status
    report["setting_revision_id"] = setting["current_revision_id"]
    report["bound_private_asset_version_id"] = bound_version_id
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"JOINT_E2E_FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        raise
