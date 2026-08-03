import json
from io import BytesIO
from pathlib import Path
from urllib import request


def post_json(url, data):
    req = request.Request(
        url,
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req) as r:
        return json.loads(r.read().decode())


def get(url):
    with request.urlopen(url) as r:
        return json.loads(r.read().decode())


def main():
    print("health", get("http://127.0.0.1:8765/api/health"))
    cats = get("http://127.0.0.1:8765/api/categories")["items"]
    leaf = None
    for c in cats:
        if c.get("name") == "华东区" or (c.get("path_label") or "").endswith("华东区"):
            leaf = c
            break
    if not leaf:
        root = post_json(
            "http://127.0.0.1:8765/api/categories",
            {"name": "业务线", "path": "", "description": "p"},
        )
        mid = post_json(
            "http://127.0.0.1:8765/api/categories",
            {"name": "招标", "path": "", "description": "m", "parent_id": root["id"]},
        )
        leaf_path = str((Path("data/documents") / "业务线" / "招标" / "华东区").resolve())
        leaf = post_json(
            "http://127.0.0.1:8765/api/categories",
            {
                "name": "华东区",
                "path": leaf_path,
                "description": "l",
                "parent_id": mid["id"],
            },
        )
    print("leaf", leaf["id"], leaf.get("path_label"), leaf.get("path"))

    boundary = "----x"
    fields = {
        "content": "第三个项目内容",
        "category_id": str(leaf["id"]),
        "title": "项目丙",
        "time_modes": "week,month,quarter",
    }
    body = BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        body.write(v.encode("utf-8"))
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    req = request.Request(
        "http://127.0.0.1:8765/api/projects",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req) as r:
        p = json.loads(r.read().decode())
    print(
        "saved",
        p["id"],
        [
            (x["period_type"], x["project_count"])
            for x in p.get("period_files") or []
        ],
    )

    leaf_dir = Path(leaf.get("resolved_path") or leaf.get("path"))
    docs = list(leaf_dir.rglob("*.docx"))
    print("docx", len(docs))
    for d in docs:
        print(" ", d)

    draft = post_json(
        "http://127.0.0.1:8765/api/projects/autosave",
        {
            "title": "草稿2",
            "category_id": leaf["id"],
            "content": "auto",
            "time_modes": ["month"],
        },
    )
    print("draft", draft["project"]["id"], draft["project"]["status"])
    print("projects", get("http://127.0.0.1:8765/api/projects?include_draft=true")["total"])
    print("period-files", len(get("http://127.0.0.1:8765/api/period-files")["items"]))
    print("OK")


if __name__ == "__main__":
    main()
