from pathlib import Path

import yaml


def test_backend_tags_are_product_scoped():
    workflow = yaml.safe_load(Path(".github/workflows/release.yml").read_text("utf-8"))
    jobs = workflow["jobs"]
    metadata = next(s["with"] for s in jobs["docker"]["steps"] if s.get("id") == "meta")
    assert metadata["flavor"] == "latest=false"
    assert metadata["tags"].strip() == "type=raw,value=release-${{ steps.version.outputs.version }}"
    assert jobs["sync_release_tag"]["needs"] == "smoke_test"
    assert jobs["smoke_test"]["if"] == "github.ref == 'refs/heads/main'"
    compose = yaml.safe_load(Path("docker-compose.yml").read_text("utf-8"))
    images = [service.get("image", "") for service in compose["services"].values()]
    version = Path("VERSION").read_text().strip()
    assert f"ghcr.io/nekosuneprojects/nekosuneai:release-{version}" in images
