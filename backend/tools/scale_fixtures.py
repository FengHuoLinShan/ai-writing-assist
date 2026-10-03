"""长篇规模夹具生成器（B7）：三档确定性合成语料。

档位（对齐 SF 三档口径）：
- low：约 10 万字
- mid：约 30 万字
- high：约 100 万字

以 tests/fixtures/synthetic_ten_chapters.txt 的真实叙事语料为基底循环
誊写，每章带确定性章节编号与轮次前缀，不引入任何随机性：同档位 +
同 seed 产出逐字节一致（见 test_scale_fixtures 确定性测试）。夹具只作
规模探针输入，不宣称覆盖真实长篇的内容多样性。

用法：
    python -m tools.scale_fixtures --tier low            # 打印摘要
    python -m tools.scale_fixtures --tier high --out DIR # 写出章节文件
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

BASE_CORPUS = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "synthetic_ten_chapters.txt"
)

TIERS: dict[str, int] = {
    # 档位 → 目标字数（汉字计）
    "low": 100_000,
    "mid": 300_000,
    "high": 1_000_000,
}


def _base_chapters() -> list[dict[str, str]]:
    from modules.imports.parsers import parse_txt

    chapters = parse_txt(BASE_CORPUS.read_bytes())
    if not chapters:
        raise RuntimeError("synthetic_ten_chapters.txt parsed to zero chapters")
    return [
        {
            "title": str(chapter.get("title") or ""),
            "content": str(chapter.get("content") or ""),
        }
        for chapter in chapters
    ]


def _chapter_chars(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


# 目标单章长度（汉字）：与真实长篇每章 3000–4000 字的量级对齐，
# 档位差异体现在章数而非畸形单章。
_TARGET_CHAPTER_CHARS = 3_500


def generate_corpus(
    tier: str,
    *,
    seed: int = 0,
    base: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """生成指定档位的确定性章节列表（seed 仅为 API 对称，不引入随机）。

    基底章约 100 字，按 _TARGET_CHAPTER_CHARS 打包成正常长度的章节；
    跨章循环拼接保证每档每章长度稳定，档位差异只体现在章数。
    """
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    chapters = list(base or _base_chapters())
    target_chars = TIERS[tier]
    output: list[dict[str, str]] = []
    written = 0
    source_index = 0
    cycle = 0
    while written < target_chars:
        number = len(output) + 1
        parts: list[str] = []
        part_chars = 0
        title = ""
        while part_chars < _TARGET_CHAPTER_CHARS:
            source = chapters[source_index % len(chapters)]
            stamp = (
                f"档{tier}·seed{seed}·轮{cycle + 1}"
                f"·源章{source_index % len(chapters) + 1}"
            )
            if not title:
                title = source["title"]
            parts.append(f"（{stamp}）{source['content']}")
            part_chars += _chapter_chars(source["content"])
            source_index += 1
            if source_index % len(chapters) == 0:
                cycle += 1
        content = "\n\n".join(parts)
        output.append(
            {"title": f"第{number}章 {title}", "content": content}
        )
        written += _chapter_chars(title) + _chapter_chars(content)
    return output


def corpus_sha256(
    tier: str, *, seed: int = 0, base: list[dict[str, str]] | None = None
) -> str:
    digest = hashlib.sha256()
    for chapter in generate_corpus(tier, seed=seed, base=base):
        digest.update(chapter["title"].encode("utf-8"))
        digest.update(b"\x00")
        digest.update(chapter["content"].encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def corpus_summary(
    tier: str, *, seed: int = 0, base: list[dict[str, str]] | None = None
) -> dict[str, object]:
    chapters = generate_corpus(tier, seed=seed, base=base)
    return {
        "tier": tier,
        "seed": seed,
        "chapters": len(chapters),
        "chars": sum(
            _chapter_chars(chapter["title"]) + _chapter_chars(chapter["content"])
            for chapter in chapters
        ),
        "sha256": corpus_sha256(tier, seed=seed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=sorted(TIERS), default="low")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="", help="写出章节 txt 的目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 打印摘要")
    args = parser.parse_args(argv)

    chapters = generate_corpus(args.tier, seed=args.seed)
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        for index, chapter in enumerate(chapters, start=1):
            (out_dir / f"chapter-{index:04d}.txt").write_text(
                f"{chapter['title']}\n\n{chapter['content']}\n", encoding="utf-8"
            )
    import json

    summary = corpus_summary(args.tier, seed=args.seed)
    print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
