"""Build an allowlisted install ZIP without local settings, caches or test outputs."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
NAME = "astrbot_plugin_attention"
FILES = (
    "main.py",
    "attention.py",
    "metadata.yaml",
    "_conf_schema.json",
    "requirements.txt",
    "README.md",
    "LICENSE",
)


def main():
    import yaml

    metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    assert metadata["name"] == NAME
    version = str(metadata["version"]).removeprefix("v")
    output = ROOT / "dist" / f"{NAME}-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for filename in FILES:
            archive.write(ROOT / filename, f"{NAME}/{filename}")
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {f"{NAME}/{filename}" for filename in FILES}
    print(
        json.dumps(
            {
                "path": str(output),
                "bytes": output.stat().st_size,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
