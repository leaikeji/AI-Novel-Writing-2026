"""Seed a freshly migrated database with synthetic novel-workflow fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.creative_authority.service import save_outline, save_settings
from backend.creative_services import create_novel_character
from backend.database import get_engine
from backend.models import Novel
from backend.private_library.contracts import UsagePolicy, VersionSelection
from backend.private_library.service import create_asset, replace_novel_bindings
from backend.services import create_checkpoint, create_novel, save_draft
from backend.story_state.persistence import fork_timeline, list_timeline_payloads


CONFIRMATION = "SEED-CREATIVE-DATA-V2"


def _chapter_id(novel: dict[str, object]) -> UUID:
    tree = novel["tree"]
    if not isinstance(tree, list) or not tree:
        raise RuntimeError("seeded novel did not create its default volume")
    documents = tree[0]["documents"]
    if not isinstance(documents, list) or not documents:
        raise RuntimeError("seeded novel did not create its default chapter")
    return UUID(str(documents[0]["id"]))


def _formalize_planning(
    session: Session,
    novel_id: UUID,
    *,
    target_chapters: int,
    background: str,
    plot: str,
    highlight: str,
    settings: dict[str, object],
) -> None:
    save_outline(
        session,
        novel_id,
        expected_head_version=0,
        idempotency_key=f"synthetic-outline:{novel_id}:v1",
        source_kind="synthetic_seed",
        target_chapter_count=target_chapters,
        background_text=background,
        plot_text=plot,
        highlight_text=highlight,
        character_revision_refs=[],
        change_set={"fixture": "creative-data-v2"},
    )
    save_settings(
        session,
        novel_id,
        expected_head_version=0,
        idempotency_key=f"synthetic-settings:{novel_id}:v1",
        source_kind="synthetic_seed",
        schema_id="novel-settings/1",
        schema_version=1,
        settings=settings,
        change_set={"fixture": "creative-data-v2"},
    )
    session.commit()


def _write_chapter(session: Session, document_id: UUID, content: str) -> None:
    draft = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown=content,
    )
    create_checkpoint(
        session,
        document_id,
        expected_draft_version=int(draft["draft_version"]),
    )


def seed(session: Session) -> dict[str, object]:
    if int(session.scalar(select(func.count()).select_from(Novel)) or 0) != 0:
        raise RuntimeError("refusing to seed a database that already contains novels")

    single = create_novel(
        session,
        "潮汐邮局（单线实验）",
        "全合成单时间线样本，用于建书、章纲、人物和语义授权零调用回归。",
    )
    single_id = UUID(str(single["id"]))
    create_novel_character(
        session,
        single_id,
        role_type="main",
        name="沈遥",
        description="在海雾港经营夜间邮局的年轻邮差。",
        details={
            "public_identity": "潮汐邮局邮差",
            "true_identity": "失踪航标员的女儿",
            "birth": {"calendar": "架空历", "year": 42, "precision": "year"},
            "goal": "找回被退回十三年的无主信",
            "secret": "她能辨认父亲留下的航标编码",
        },
    )
    create_novel_character(
        session,
        single_id,
        role_type="supporting",
        name="陆栖",
        description="负责维护港口旧钟塔的修理师。",
        details={
            "public_identity": "钟塔修理师",
            "goal": "阻止错误潮汐表再次启用",
        },
    )
    _formalize_planning(
        session,
        single_id,
        target_chapters=24,
        background="架空海港每逢大潮会暂时切断陆路，夜间邮局负责转交延迟多年的信件。",
        plot="沈遥收到一封写给失踪父亲的退信，由此追查旧航标事故与被篡改的潮汐表。",
        highlight="用一封封迟到的信推进真相，同时保持人物知识与读者揭示分离。",
        settings={
            "world": "架空近现代海港",
            "calendar": "架空历",
            "rules": ["潮汐表由钟塔与港务站双重校验", "无主信不得在未经登记时拆封"],
        },
    )
    _write_chapter(
        session,
        _chapter_id(single),
        "# 第一章 退潮后的信\n\n退潮铃响过第三遍，沈遥才在门缝里发现那只没有邮戳的蓝色信封。",
    )

    multi = create_novel(
        session,
        "镜港回环（多线实验）",
        "全合成多时间线样本，用于分支、人物实例、循环与显式汇合回归。",
    )
    multi_id = UUID(str(multi["id"]))
    create_novel_character(
        session,
        multi_id,
        role_type="main",
        name="顾弦",
        description="研究镜港时间异常的测绘员。",
        details={
            "public_identity": "测绘员",
            "cover_identity": "渡船检票员",
            "true_identity": "第一次回环的唯一幸存者",
            "birth": {"calendar": "公历", "year": 2001, "precision": "year"},
            "growth_direction": "从独自修正历史转为承认不同世界线的选择权",
        },
    )
    _formalize_planning(
        session,
        multi_id,
        target_chapters=36,
        background="镜港每十二年出现一次无法被普通航海图记录的回流带。",
        plot="顾弦在两条互不自动传播事实的时间线中追查同一场沉船事故。",
        highlight="穿越者与本线对应人物可以同时存在，冲突必须由目标线事实显式解决。",
        settings={
            "world": "近未来岛港",
            "time_rule": "循环建立新分支，不改写原历史",
            "knowledge_rule": "人物知识只能由其可见事件推进",
        },
    )
    timelines = list_timeline_payloads(session, multi_id)
    main = next(item for item in timelines if item["is_primary"])
    current = session.get(Novel, multi_id)
    if current is None:
        raise RuntimeError("multi-line seed novel disappeared")
    fork_timeline(
        session,
        multi_id,
        UUID(str(main["id"])),
        expected_story_ledger_version=int(current.story_ledger_version),
        expected_source_timeline_version=int(main["version"]),
        timeline_key="second-pass",
        name="第二次回环",
        fork_story_sequence=100,
        fork_anchor={"kind": "loop_anchor", "label": "沉船前夜"},
    )
    session.commit()
    _write_chapter(
        session,
        _chapter_id(multi),
        "# 第一章 两个顾弦\n\n渡船靠岸时，顾弦隔着雨幕看见另一个自己站在检票棚下。",
    )

    asset = create_asset(
        session,
        asset_type="plot",
        title="合成素材：海港信号规则",
        content="蓝灯表示航道开放，双白灯表示潮汐表等待人工复核。",
        operation_key="synthetic-private-asset:v1",
        tags=["合成", "海港"],
        metadata={"fixture": "creative-data-v2"},
        source={"kind": "project_synthetic"},
        rights={"basis": "project_synthetic", "cloud_allowed": False},
    )
    session.commit()
    replace_novel_bindings(
        session,
        single_id,
        expected_binding_versions={},
        selections=[
            VersionSelection(
                asset_id=asset.asset.id,
                asset_version_id=asset.asset_version.id,
                usage_policy=UsagePolicy.CONTEXT_ONLY,
                position=1000,
            )
        ],
        operation_key="synthetic-single-binding:v1",
    )
    session.commit()

    return {
        "schema_version": "creative-data-v2-seed-result/1.0",
        "novels": [
            {"id": str(single_id), "title": str(single["title"]), "mode": "single"},
            {"id": str(multi_id), "title": str(multi["title"]), "mode": "multi"},
        ],
        "private_asset_count": 1,
        "embedding_consent_count": 0,
        "cloud_requests": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRMATION:
        raise SystemExit(f"--confirm must equal {CONFIRMATION}")
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        result = seed(session)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
