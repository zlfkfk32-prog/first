"""Validated, dated public contractor watchlist; never guess TOP100 membership."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "assets" / "contractors-top100.json"


@dataclass(frozen=True)
class Contractor:
    rank: int
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Roster:
    year: int
    source_url: str
    source_sha256: str
    contractors: tuple[Contractor, ...]
    demo: bool = False

    def matches(self, text: str) -> tuple[Contractor, ...]:
        return tuple(company for company in self.contractors if any(
            company_mentioned(text, alias) for alias in (company.name, *company.aliases)
        ))

    def queries(self, size: int = 5) -> list[str]:
        # Separate batches cover all 100 names instead of truncating one long search query.
        aliases = list(dict.fromkeys(alias for company in self.contractors for alias in (company.name, *company.aliases)))
        return ["(" + " OR ".join('"' + alias + '"' for alias in aliases[i:i + size]) + ") "
                "(수주 OR PF OR 신용 OR 부실 OR 유동성 OR 실적 OR 안전 OR 분양 OR 경영 OR 인사) -배구 -농구"
                for i in range(0, len(aliases), size)]


def company_mentioned(text: str, name: str) -> bool:
    # Do not match 한양대학교 as 한양, or 대방산업개발 as 대방건설.
    normalized = re.sub(r"(?:\(주\)|㈜|주식회사)", "", name).strip()
    escaped = r"\s*".join(re.escape(part) for part in normalized.split())
    pattern = r"(?<![가-힣A-Za-z0-9])" + escaped + (
        r"(?=$|[^가-힣A-Za-z0-9]|(?:은|는|이|가|의|과|와|에서|에|도|을|를)(?=$|[^가-힣A-Za-z0-9]))"
    )
    return bool(re.search(pattern, text, re.I))


def load_roster(path: Path = DEFAULT_PATH) -> Roster:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("verified") is not True:
        raise ValueError("공식 TOP100 명단 확인 대기")
    if data.get("category") != "토목건축공사업":
        raise ValueError("토목건축공사업 시공능력평가 명단이 필요합니다")
    year = data.get("year")
    if not isinstance(year, int) or not 2000 <= year <= 2100:
        raise ValueError("시공능력평가 연도가 잘못되었습니다")
    source = urlsplit(data.get("source_url", ""))
    if source.username or source.password or source.scheme != "https" or source.hostname not in {
        "www.molit.go.kr", "www.cak.or.kr", "www.kiscon.net", "molit.go.kr", "cak.or.kr", "kiscon.net",
    }:
        raise ValueError("공식 공개 순위 자료의 HTTPS 출처가 필요합니다")
    source_file = (path.parent / data.get("source_file", "")).resolve()
    if not source_file.is_relative_to(path.parent.resolve()) or not source_file.is_file():
        raise ValueError("명단과 대조한 공개 원본 파일이 없습니다")
    digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
    if data.get("source_sha256") != digest:
        raise ValueError("순위 원본 파일 체크섬이 일치하지 않습니다")
    raw = data.get("contractors", [])
    if not isinstance(raw, list) or len(raw) != 100 or not all(isinstance(c, dict) and type(c.get("rank")) is int for c in raw) or {c.get("rank") for c in raw} != set(range(1, 101)):
        raise ValueError("TOP100은 1~100위가 빠짐없이 한 번씩 있어야 합니다")
    contractors = []
    used_aliases = {}
    for item in sorted(raw, key=lambda c: c["rank"]):
        if not isinstance(item.get("name"), str) or not isinstance(item.get("aliases", []), list):
            raise ValueError("시공사명/별칭 형식이 잘못되었습니다")
        name = item["name"].strip()
        aliases = tuple(item.get("aliases", []))
        for alias in (name, *aliases):
            if not isinstance(alias, str) or not alias.strip() or re.search(r'["\n\r]', alias):
                raise ValueError("시공사명/별칭이 잘못되었습니다")
            normalized = re.sub(r"(?:\(주\)|㈜|주식회사|\s+)", "", alias).lower()
            if normalized in used_aliases and used_aliases[normalized] != item["rank"]:
                raise ValueError("시공사명/별칭이 중복 또는 모호합니다")
            used_aliases[normalized] = item["rank"]
        contractors.append(Contractor(item["rank"], name, aliases))
    return Roster(year, data["source_url"], digest, tuple(contractors))


def demo_roster(year: int) -> Roster:
    # Entirely fictional: never used by live collection or persisted as verified rankings.
    return Roster(year, "https://example.com/fictional-rankings", "", tuple(
        Contractor(i, f"샘플건설{i:03d}") for i in range(1, 101)
    ), demo=True)
