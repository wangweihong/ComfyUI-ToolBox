"""Queue the recommended semantic workflows against local models and an input image."""
import argparse
import json
from pathlib import Path
import time
import urllib.request

from generate_stocking_unified_workflows import graphs


def request(url, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url.rstrip("/") + path, data, {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def run(url, title, prompt):
    queued = request(url, "/prompt", {"prompt": prompt})
    prompt_id = queued["prompt_id"]
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        history = request(url, "/history/" + prompt_id)
        if history:
            entry = history[prompt_id]
            errors = [m[1].get("exception_message") for m in entry["status"]["messages"] if m[0] == "execution_error"]
            if entry["status"]["status_str"] != "success":
                raise RuntimeError(f"{title}: {'; '.join(errors)}")
            reports = [n["nf_stocking"][0]["report"] for n in entry["outputs"].values() if "nf_stocking" in n]
            for report in reports:
                assert [r["input_index"] for r in report] == list(range(len(report)))
                assert all(r["changed_pixels"] > 0 for r in report if r["output_index"] is not None)
            result = {"workflow": title, "prompt_id": prompt_id, "reports": reports}
            print(title + ": passed", flush=True)
            return result
        time.sleep(0.5)
    raise TimeoutError(f"{title}: queue timed out")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--image", required=True, help="Existing ComfyUI input filename containing stockings")
    parser.add_argument("--guides", type=Path, help="Optional saved v2 guides for the manual recipe")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    items = graphs(args.image, args.guides.read_text() if args.guides else "{}")
    if args.guides is None:
        items = items[1:]
    results = [run(args.url, title, prompt) for title, prompt in items]
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
