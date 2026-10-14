"""Import a manually source-checked public TOP100 CSV with its official source snapshot."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cardletter.rankings import load_roster


def main():
    parser = argparse.ArgumentParser(description="공식 공개 원본과 대조한 TOP100 CSV 가져오기")
    parser.add_argument("--csv", type=Path, required=True, help="rank,name,aliases 열; aliases는 | 구분")
    parser.add_argument("--source-file", type=Path, required=True, help="공식 공개 PDF/XLSX 등 대조 원본")
    parser.add_argument("--source-url", required=True, help="국토부/대한건설협회/KISCON 공식 HTTPS 주소")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--output", type=Path, default=Path("assets/contractors-top100.json"))
    parser.add_argument("--source-checked", action="store_true", help="100개사와 순위를 원본에 대조했음을 명시")
    args = parser.parse_args()
    if not args.source_checked:
        parser.error("공식 원본에 100개사 순위를 대조한 후 --source-checked를 지정하세요")
    with args.csv.open(encoding=args.encoding, newline="") as stream:
        companies = [{"rank": int(row["rank"]), "name": row["name"].strip(),
                      "aliases": [a.strip() for a in row.get("aliases", "").split("|") if a.strip()]}
                     for row in csv.DictReader(stream)]
    source_data = args.source_file.read_bytes()
    if not source_data:
        parser.error("공식 대조 원본이 비어 있습니다")
    digest = hashlib.sha256(source_data).hexdigest()
    filename = f"rankings-{args.year}-{digest[:12]}{args.source_file.suffix}"
    data = {"verified": True, "category": "토목건축공사업", "year": args.year,
            "source_url": args.source_url, "source_file": filename, "source_sha256": digest,
            "contractors": companies}
    # Validate completely before changing the saved watchlist. Never fabricate missing ranks.
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        (temp / filename).write_bytes(source_data)
        (temp / "rankings.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        load_roster(temp / "rankings.json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        previous = args.output.read_bytes()
        backup = args.output.with_name(args.output.name + "." + hashlib.sha256(previous).hexdigest()[:12] + ".bak")
        if not backup.exists():
            backup.write_bytes(previous)
    target_source = args.output.parent / filename
    if target_source.exists() and target_source.read_bytes() != source_data:
        parser.error("동일 경로에 다른 원본 파일이 있습니다")
    if not target_source.exists():
        shutil.copyfile(args.source_file, target_source)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved: {args.output} ({args.year}년 / 100개사)")


if __name__ == "__main__":
    main()
