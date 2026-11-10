"""Print saved findings for reading: python benchmarks/show.py <out_dir> [name ...] [--check ID]"""
import glob, json, os, sys
args = sys.argv[1:]
check = None
if "--check" in args:
    i = args.index("--check"); check = args[i + 1]; del args[i:i + 2]
out_dir, names = args[0], args[1:]
paths = [os.path.join(out_dir, n + ".json") for n in names] or sorted(glob.glob(os.path.join(out_dir, "*.json")))
for p in paths:
    d = json.load(open(p, encoding="utf-8"))
    print("=====", d["repo"], d["sha"][:10], "not_reported:", d["not_reported"], d["notes"])
    for f in d["findings"]:
        if check and f["check"] != check:
            continue
        print(" ", f["id"], f["check"], f["confidence"], f["doc"], "|", f["doc_quote"][:120])
        print("     ", f["problem"][:220])
        if f.get("code"):
            print("      code:", f["code"], f.get("code_quote", "")[:100])
